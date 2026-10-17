"""Core analysis for acrodrift: acronym lifecycle checks for LaTeX and Markdown."""
from __future__ import annotations

import bisect
import os
import re
from dataclasses import dataclass, field, asdict

STOPWORDS = {"of", "and", "for", "the", "in", "on", "to", "a", "an", "with", "via", "by", "from", "at", "or"}

DEFAULT_ALLOW = {
    "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII",
    "OK", "TODO", "FIXME", "XXX", "PDF", "URL", "URLs", "HTTP", "HTTPS", "HTML",
    "JSON", "XML", "CSV", "SQL", "USB", "ASCII", "UTF",
}

SEVERITY = {"error": 3, "warning": 2, "info": 1}

KIND_SEVERITY = {
    "mismatch": "error",
    "conflict": "error",
    "undefined": "warning",
    "used-before-definition": "warning",
    "raw-use": "warning",
    "redefined": "info",
    "unused": "info",
    "re-expanded": "info",
}

# An acronym token: 2-10 chars, starts uppercase, at least two uppercase letters, optional plural "s".
TOKEN_RE = re.compile(r"(?<![A-Za-z0-9\\])([A-Z][A-Z0-9]{1,9})(s?)(?![A-Za-z0-9])")
DEF_PAREN_RE = re.compile(r"\(\s*([A-Z][A-Z0-9]{1,9})(s?)\s*\)")
WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]*")

INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")
NEWACRONYM_RE = re.compile(r"\\newacronym\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}\s*\{([^}]*)\}\s*\{([^}]*)\}")
ACRO_RE = re.compile(r"\\(?:acro|acrodef|DeclareAcronym)\s*\{([^}]*)\}\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}")
GLS_USE_RE = re.compile(r"\\(?:ac|acs|acl|acf|acp|acsp|aclp|acfp|Ac|Acl|Acf|gls|Gls|glspl|Glspl|acrshort|acrlong|acrfull)\*?\s*\{([^}]*)\}")

MASK_ENVS = ("verbatim", "lstlisting", "minted", "equation", "align", "gather", "multline",
             "displaymath", "math", "comment", "tikzpicture", "tabular")
ARG_CMDS = r"cite\w*|ref|eqref|autoref|cref|Cref|pageref|label|url|href|includegraphics|input|include|subfile|usepackage|RequirePackage|documentclass|bibliography|bibliographystyle|begin|end|newacronym|acro|acrodef|DeclareAcronym|ac|acs|acl|acf|acp|acsp|aclp|acfp|Ac|Acl|Acf|gls|Gls|glspl|Glspl|acrshort|acrlong|acrfull|newcommand|renewcommand|def"


@dataclass
class Finding:
    kind: str
    severity: str
    acronym: str
    file: str
    line: int
    message: str


@dataclass
class Definition:
    acronym: str
    long_form: str
    file: str
    line: int
    pos: int
    scope: str
    source: str  # "inline" or "glossary"
    matched: bool = True


@dataclass
class Use:
    acronym: str
    file: str
    line: int
    pos: int
    scope: str


@dataclass
class Report:
    findings: list = field(default_factory=list)
    definitions: list = field(default_factory=list)
    uses: list = field(default_factory=list)
    files: list = field(default_factory=list)

    def to_dict(self):
        table = {}
        for d in self.definitions:
            table.setdefault(d.acronym, {"acronym": d.acronym, "long_form": d.long_form,
                                         "defined_at": f"{d.file}:{d.line}", "uses": 0})
        for u in self.uses:
            if u.acronym in table:
                table[u.acronym]["uses"] += 1
        return {
            "files": self.files,
            "findings": [asdict(f) for f in self.findings],
            "acronyms": sorted(table.values(), key=lambda r: r["acronym"]),
            "summary": summarize(self.findings),
        }


def summarize(findings):
    out = {"error": 0, "warning": 0, "info": 0}
    for f in findings:
        out[f.severity] += 1
    return out


# ---------------------------------------------------------------- masking

def _blank(text: str, start: int, end: int) -> str:
    seg = text[start:end]
    return text[:start] + re.sub(r"[^\n]", " ", seg) + text[end:]


def strip_tex_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        m = re.search(r"(?<!\\)%", line)
        if m:
            line = line[: m.start()] + " " * (len(line) - m.start())
        out.append(line)
    return "\n".join(out)


def _mask_regex(text: str, pattern: str, flags=0) -> str:
    for m in list(re.finditer(pattern, text, flags)):
        text = _blank(text, m.start(), m.end())
    return text


def mask_tex(text: str) -> str:
    """Blank out regions that must not be scanned, keeping offsets and newlines intact."""
    for env in MASK_ENVS:
        text = _mask_regex(text, r"\\begin\{%s\*?\}.*?\\end\{%s\*?\}" % (env, env), re.S)
    text = _mask_regex(text, r"\$\$.*?\$\$", re.S)
    text = _mask_regex(text, r"\\\[.*?\\\]", re.S)
    text = _mask_regex(text, r"\\\(.*?\\\)", re.S)
    text = _mask_regex(text, r"(?<!\\)\$.*?(?<!\\)\$", re.S)
    text = _mask_regex(text, r"\\(?:%s)\*?\s*(?:\[[^\]]*\]\s*)*(?:\{[^}]*\}\s*){1,3}" % ARG_CMDS)
    text = _mask_regex(text, r"\\[A-Za-z@]+\*?")
    text = _mask_regex(text, r"https?://\S+")
    return text


def mask_markdown(text: str) -> str:
    text = _mask_regex(text, r"```.*?```", re.S)
    text = _mask_regex(text, r"~~~.*?~~~", re.S)
    text = _mask_regex(text, r"`[^`\n]*`")
    text = _mask_regex(text, r"\]\([^)]*\)")
    text = _mask_regex(text, r"https?://\S+")
    text = _mask_regex(text, r"<!--.*?-->", re.S)
    return text


# ---------------------------------------------------------------- loading

@dataclass
class Chunk:
    path: str
    text: str          # comment-stripped original text (for glossary parsing)
    masked: str        # scan text
    start_line: int
    base: int          # global position of chunk start
    is_tex: bool
    abstract_spans: list


def _load_chunks(path, display_root, chunks, seen, base_counter):
    real = os.path.realpath(path)
    if real in seen:
        return
    seen.add(real)
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    is_tex = path.endswith((".tex", ".ltx", ".sty", ".cls"))
    disp = os.path.relpath(path, display_root)
    if not is_tex:
        _add_chunk(chunks, disp, raw, 1, False, base_counter)
        return
    text = strip_tex_comments(raw)
    cursor = 0
    for m in INPUT_RE.finditer(text):
        _add_chunk(chunks, disp, text[cursor:m.start()], text[:cursor].count("\n") + 1, True, base_counter)
        target = m.group(1).strip()
        cand = os.path.join(os.path.dirname(path), target)
        if not os.path.exists(cand) and os.path.exists(cand + ".tex"):
            cand = cand + ".tex"
        if os.path.exists(cand):
            _load_chunks(cand, display_root, chunks, seen, base_counter)
        # keep the \input text itself as a blank-ish chunk so line numbers stay right
        cursor = m.start()
    _add_chunk(chunks, disp, text[cursor:], text[:cursor].count("\n") + 1, True, base_counter)


def _add_chunk(chunks, disp, text, start_line, is_tex, base_counter):
    if is_tex:
        spans = [(m.start(), m.end()) for m in re.finditer(r"\\begin\{abstract\}.*?\\end\{abstract\}", text, re.S)]
        masked = mask_tex(text)
    else:
        spans = []
        masked = mask_markdown(text)
    chunks.append(Chunk(disp, text, masked, start_line, base_counter[0], is_tex, spans))
    base_counter[0] += len(text) + 1


# ---------------------------------------------------------------- long-form detection

def schwartz_hearst(sf: str, lf: str):
    """Return the shortest suffix of lf whose characters spell sf (Schwartz & Hearst, 2003)."""
    s_index = len(sf) - 1
    l_index = len(lf) - 1
    while s_index >= 0:
        c = sf[s_index].lower()
        if not c.isalnum():
            s_index -= 1
            continue
        while (l_index >= 0 and lf[l_index].lower() != c) or (
            s_index == 0 and l_index > 0 and lf[l_index - 1].isalnum()
        ):
            l_index -= 1
        if l_index < 0:
            return None
        l_index -= 1
        s_index -= 1
    start = lf.rfind(" ", 0, l_index + 1) + 1
    return lf[start:].strip()


def _initials_ok(sf: str, long_form: str) -> bool:
    """Stricter sanity check: first letter must start the long form and every content word
    must contribute at least one letter of the short form, in order."""
    words = [w for w in re.split(r"[\s-]+", long_form) if w]
    if not words or words[0][0].lower() != sf[0].lower():
        return False
    letters = sf.lower()
    i = 0
    for w in words:
        wl = w.lower()
        if wl in STOPWORDS and (i >= len(letters) or wl[0] != letters[i]):
            continue
        if i >= len(letters) or wl[0] != letters[i]:
            return False
        i += 1
        j = 1
        while i < len(letters) and j < len(wl):
            # allow multi-letter take from one word (e.g. "PyTorch" -> PT, "Ethernet" -> ETH)
            if wl[j] == letters[i] and (w[j].isupper() or not _next_word_starts(words, w, letters[i])):
                i += 1
            j += 1
    return i == len(letters)


def _next_word_starts(words, current, letter):
    idx = words.index(current)
    return any(w[0].lower() == letter for w in words[idx + 1:])


def find_long_form(sf: str, before: str):
    words = WORD_RE.findall(before)
    limit = min(len(sf) + 5, len(sf) * 2)
    window_words = words[-limit:]
    if not window_words:
        return None, None
    # rebuild the candidate from the raw tail so hyphens survive
    tail = " ".join(window_words)
    lf = schwartz_hearst(sf, tail)
    if lf and _initials_ok(sf, lf):
        return lf, True
    # fallback: maybe the author intended a definition but the letters don't line up
    # walk back over a run of Title-Case words (stopwords allowed inside the run)
    run = []
    for w in reversed(window_words[-(len(sf) + 2):]):
        if w[0].isupper() and not TOKEN_RE.fullmatch(w):
            run.append(w)
        elif w.lower() in STOPWORDS and run:
            run.append(w)
        else:
            break
    while run and run[-1].lower() in STOPWORDS:
        run.pop()
    run.reverse()
    if len(run) >= 2:
        return " ".join(run), False
    return None, None


def norm_long(lf: str) -> str:
    s = re.sub(r"[\s-]+", " ", lf.lower()).strip()
    return re.sub(r"s\b", "", s)


# ---------------------------------------------------------------- analysis

def analyze(paths, allow=None, use_default_allow=True, abstract_scope=True, reexpand=True):
    allow = set(allow or [])
    if use_default_allow:
        allow |= DEFAULT_ALLOW
    chunks = []
    seen = set()
    counter = [0]
    root = os.path.commonpath([os.path.dirname(os.path.abspath(p)) for p in paths]) if paths else "."
    for p in paths:
        _load_chunks(os.path.abspath(p), root, chunks, seen, counter)

    report = Report(files=sorted({c.path for c in chunks}))
    glossary = {}      # short form -> Definition (glossary-managed)
    gls_keys = {}      # key -> short form
    gls_used = set()

    defs, uses = [], []
    def_spans = []  # (global start, global end) of inline definitions to exclude from re-expansion

    for ch in chunks:
        nl = [i for i, c in enumerate(ch.text) if c == "\n"]

        def line_of(off, nl=nl, ch=ch):
            return ch.start_line + bisect.bisect_right(nl, off - 1)

        def scope_of(off, ch=ch):
            if abstract_scope and any(a <= off < b for a, b in ch.abstract_spans):
                return "abstract"
            return "body"

        if ch.is_tex:
            for m in NEWACRONYM_RE.finditer(ch.text):
                key, short, long_ = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                d = Definition(short, long_, ch.path, line_of(m.start()), ch.base + m.start(), "global", "glossary")
                glossary.setdefault(short, d)
                gls_keys[key] = short
                defs.append(d)
            for m in ACRO_RE.finditer(ch.text):
                key = m.group(1).strip()
                short = (m.group(2) or key).strip()
                long_ = m.group(3).strip()
                d = Definition(short, long_, ch.path, line_of(m.start()), ch.base + m.start(), "global", "glossary")
                glossary.setdefault(short, d)
                gls_keys[key] = short
                defs.append(d)
            for m in GLS_USE_RE.finditer(ch.text):
                gls_used.add(m.group(1).strip())

        text = ch.masked
        def_tokens = set()
        for m in DEF_PAREN_RE.finditer(text):
            sf = m.group(1)
            before = text[max(0, m.start() - 400):m.start()]
            lf, ok = find_long_form(sf, before)
            if lf is None:
                continue
            d = Definition(sf, lf, ch.path, line_of(m.start(1)), ch.base + m.start(1), scope_of(m.start()), "inline", ok)
            defs.append(d)
            def_tokens.add(m.start(1))
            lf_start = before.lower().rfind(lf.split()[0].lower())
            def_spans.append((ch.base + max(0, m.start() - 400) + max(lf_start, 0), ch.base + m.end()))
        for m in TOKEN_RE.finditer(text):
            sf = m.group(1)
            if m.start(1) in def_tokens:
                continue
            if sf in allow or (sf + m.group(2)) in allow:
                continue
            if sum(1 for c in sf if c.isupper()) < 2:
                continue
            uses.append(Use(sf, ch.path, line_of(m.start(1)), ch.base + m.start(1), scope_of(m.start(1))))

    report.definitions = defs
    report.uses = uses
    findings = []

    def add(kind, acr, file, line, msg):
        findings.append(Finding(kind, KIND_SEVERITY[kind], acr, file, line, msg))

    inline_defs = [d for d in defs if d.source == "inline"]

    # mismatches
    for d in inline_defs:
        if not d.matched:
            add("mismatch", d.acronym, d.file, d.line,
                f'"{d.long_form}" does not spell {d.acronym}; check the letters or the expansion')

    # conflicts / redefinitions
    by_acr = {}
    for d in sorted(defs, key=lambda d: d.pos):
        by_acr.setdefault(d.acronym, []).append(d)
    for acr, ds in by_acr.items():
        first = ds[0]
        for i, d in enumerate(ds[1:], start=1):
            if norm_long(d.long_form) != norm_long(first.long_form):
                add("conflict", acr, d.file, d.line,
                    f'{acr} expanded as "{d.long_form}" but earlier as "{first.long_form}" ({first.file}:{first.line})')
                continue
            prev = [x for x in ds[:i] if x.scope == d.scope and x.source == "inline"]
            if d.source == "inline" and prev:
                add("redefined", acr, d.file, d.line,
                    f"{acr} is defined again in the {d.scope} (first at {prev[0].file}:{prev[0].line})")

    # uses: glossary-managed vs inline
    for scope in ("abstract", "body"):
        scope_uses = [u for u in uses if u.scope == scope]
        scope_defs = [d for d in inline_defs if d.scope == scope]
        first_def = {}
        for d in sorted(scope_defs, key=lambda d: d.pos):
            if d.matched:
                first_def.setdefault(d.acronym, d)
        for d in sorted(scope_defs, key=lambda d: d.pos):
            first_def.setdefault(d.acronym, d)  # mismatched-only acronyms still count as defined
        reported_undefined = set()
        reported_before = set()
        for u in sorted(scope_uses, key=lambda u: u.pos):
            if u.acronym in glossary:
                continue
            d = first_def.get(u.acronym)
            if d is None:
                if u.acronym not in reported_undefined:
                    reported_undefined.add(u.acronym)
                    elsewhere = [x for x in inline_defs if x.acronym == u.acronym]
                    hint = ""
                    if elsewhere:
                        hint = f" in the {scope} (only defined in the {elsewhere[0].scope} at {elsewhere[0].file}:{elsewhere[0].line})"
                    n = sum(1 for x in scope_uses if x.acronym == u.acronym)
                    add("undefined", u.acronym, u.file, u.line,
                        f"{u.acronym} is never defined{hint}; used {n} time(s)")
            elif u.pos < d.pos and u.acronym not in reported_before:
                reported_before.add(u.acronym)
                add("used-before-definition", u.acronym, u.file, u.line,
                    f"{u.acronym} is used before its definition at {d.file}:{d.line}")
        for acr, d in first_def.items():
            if not d.matched:
                continue
            later = [u for u in scope_uses if u.acronym == acr and u.pos > d.pos]
            if not later:
                add("unused", acr, d.file, d.line,
                    f"{acr} is defined but never used afterwards in the {scope}; the expansion alone is enough")

    # raw use of glossary-managed acronyms
    raw_reported = set()
    for u in sorted(uses, key=lambda u: u.pos):
        if u.acronym in glossary and u.acronym not in raw_reported:
            raw_reported.add(u.acronym)
            g = glossary[u.acronym]
            add("raw-use", u.acronym, u.file, u.line,
                f"{u.acronym} is managed by the glossary ({g.file}:{g.line}) but typed as plain text; use \\ac{{...}} so first-use expansion stays correct")

    # glossary entries never referenced
    for key, short in gls_keys.items():
        if key not in gls_used and not any(u.acronym == short for u in uses):
            g = glossary[short]
            add("unused", short, g.file, g.line, f"glossary acronym {short} ({key}) is declared but never used")

    # re-expansion after definition
    if reexpand:
        for acr, d in ((a, ds[0]) for a, ds in by_acr.items()):
            if d.source != "inline" or not d.matched:
                continue
            pat = re.compile(r"(?<![A-Za-z])" + r"[\s-]+".join(re.escape(w) for w in re.split(r"[\s-]+", d.long_form)) + r"s?(?![A-Za-z])", re.I)
            hits = []
            for ch in chunks:
                for m in pat.finditer(ch.masked):
                    g = ch.base + m.start()
                    if g <= d.pos or any(a <= g < b for a, b in def_spans):
                        continue
                    nl_count = ch.text[:m.start()].count("\n")
                    hits.append((ch.path, ch.start_line + nl_count))
            if hits:
                f, ln = hits[0]
                add("re-expanded", acr, f, ln,
                    f'"{d.long_form}" is spelled out again {len(hits)} time(s) after {acr} was defined; consider using {acr}')

    findings.sort(key=lambda f: (f.file, f.line, -SEVERITY[f.severity], f.acronym))
    report.findings = findings
    return report
