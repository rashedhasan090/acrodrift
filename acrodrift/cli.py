"""Command-line interface for acrodrift."""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import __version__
from .core import SEVERITY, analyze, KIND_SEVERITY


def _read_allow(path):
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.split("#", 1)[0].strip()
            if line:
                out.add(line)
    return out


def build_parser():
    p = argparse.ArgumentParser(
        prog="acrodrift",
        description="Catch acronym drift in LaTeX papers and Markdown docs: undefined, "
                    "used-before-definition, misspelled expansions, conflicting expansions, "
                    "abstract/body scope leaks, re-expansions, and glossary bypasses.",
    )
    p.add_argument("paths", nargs="+", help="main .tex file(s) or .md files; \\input/\\include are followed")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument("--table", action="store_true", help="also print the acronym table (text mode)")
    p.add_argument("--allow", action="append", default=[], help="acronym to ignore (repeatable)")
    p.add_argument("--allow-file", help="file with one acronym per line to ignore")
    p.add_argument("--no-default-allow", action="store_true", help="do not ignore built-in common acronyms (PDF, URL, ...)")
    p.add_argument("--no-abstract-scope", action="store_true",
                   help="let definitions made in the abstract count for the body")
    p.add_argument("--no-reexpand", action="store_true", help="skip the re-expanded check")
    p.add_argument("--ignore-kind", action="append", default=[], choices=sorted(KIND_SEVERITY),
                   help="drop a finding kind (repeatable)")
    p.add_argument("--fail-on", choices=["error", "warning", "info", "never"], default="error",
                   help="exit 1 when a finding at or above this severity exists (default: error)")
    p.add_argument("--version", action="version", version=f"acrodrift {__version__}")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    for path in args.paths:
        if not os.path.isfile(path):
            print(f"acrodrift: no such file: {path}", file=sys.stderr)
            return 2
    allow = set(args.allow)
    if args.allow_file:
        allow |= _read_allow(args.allow_file)
    report = analyze(args.paths, allow=allow, use_default_allow=not args.no_default_allow,
                     abstract_scope=not args.no_abstract_scope, reexpand=not args.no_reexpand)
    report.findings = [f for f in report.findings if f.kind not in set(args.ignore_kind)]
    data = report.to_dict()

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        for f in report.findings:
            print(f"{f.file}:{f.line}: {f.severity} [{f.kind}] {f.message}")
        if args.table and data["acronyms"]:
            print()
            w = max(len(r["acronym"]) for r in data["acronyms"])
            for r in data["acronyms"]:
                print(f"  {r['acronym']:<{w}}  {r['long_form']}  (defined {r['defined_at']}, {r['uses']} use(s))")
        s = data["summary"]
        print(f"\nacrodrift: {s['error']} error(s), {s['warning']} warning(s), {s['info']} info "
              f"across {len(data['files'])} file(s), {len(data['acronyms'])} acronym(s) defined")

    if args.fail_on == "never":
        return 0
    threshold = SEVERITY[args.fail_on]
    return 1 if any(SEVERITY[f.severity] >= threshold for f in report.findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
