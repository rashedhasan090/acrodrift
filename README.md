# acrodrift

Catch acronym drift in LaTeX papers and Markdown docs before a reviewer does.

`acrodrift` reads a paper the way a reader does, in order, following `\input` and `\include`, and tracks the life of every acronym: where it is defined, whether the expansion actually spells it, whether it was used before that, whether a later section quietly expands it differently, and whether the abstract's definitions are leaking into the body. It is an offline, standard-library Python CLI with no dependencies.

## What's novel

Spell checkers and `chktex` don't track acronyms at all, and the `acronym`/`glossaries` packages only help if every use goes through their macros. acrodrift checks plain prose:

- **Expansion verification.** Definitions like `Large Language Models (LLMs)` are detected with the Schwartz and Hearst (2003) abbreviation algorithm plus a stricter initials check, so `Retrieval Augmented Generation (RGA)` or `Graph Network (GNN)` is flagged as a **mismatch** instead of silently accepted.
- **Document-order lifecycle across files.** Uses before the definition are reported even when the use is in `sections/intro.tex` and the definition is three `\input`s later, with real file and line numbers.
- **Cross-section conflicts.** The same acronym expanded two different ways (`GNN` as "Graph Neural Network" and later "Graph Network") is an error.
- **Abstract scope.** Many venues require acronyms to be defined again in the body. Definitions inside `\begin{abstract}` do not count for the body unless you pass `--no-abstract-scope`.
- **Glossary bypass.** If an acronym is declared with `\newacronym` or `\acro`/`\DeclareAcronym` but also typed raw in the text, first-use expansion breaks. That is reported as **raw-use**; unused glossary entries are reported too.
- **Style hygiene.** Acronyms defined but never used again, redefined in the same scope, or spelled out again after being defined.

Math, comments, `\cite`, `\ref`, `\label`, URLs, verbatim and code blocks are masked so `\ref{tab:RES}` or `$O(NM)$` never shows up as an acronym.

## Finding kinds

| kind | severity | meaning |
| --- | --- | --- |
| `mismatch` | error | the expansion before `(ABC)` does not spell ABC |
| `conflict` | error | the acronym is expanded differently somewhere else |
| `undefined` | warning | used but never defined in this scope |
| `used-before-definition` | warning | first use comes before the definition |
| `raw-use` | warning | glossary-managed acronym typed as plain text |
| `redefined` | info | defined again with the same expansion in the same scope |
| `unused` | info | defined but never used afterwards |
| `re-expanded` | info | long form spelled out again after definition |

## Install

```bash
pip install git+https://github.com/rashedhasan090/acrodrift
# or, from a clone, no install needed:
python3 -m acrodrift paper.tex
```

Requires Python 3.8+. No dependencies.

## Usage

```bash
acrodrift main.tex                    # follows \input / \include
acrodrift main.tex --table            # also print the acronym table
acrodrift README.md docs/*.md         # Markdown works too
acrodrift main.tex --format json      # machine-readable
acrodrift main.tex --allow SOTA --allow-file acronyms.txt
acrodrift main.tex --fail-on warning  # CI gate (default: error)
acrodrift main.tex --ignore-kind unused --no-abstract-scope
```

Exit codes are 0 for clean (below the `--fail-on` threshold), 1 when findings meet it, and 2 for usage errors.

## Demo

`examples/paper.tex` pulls in `examples/sections/intro.tex` and contains the usual mistakes.

```text
$ acrodrift examples/paper.tex --table
paper.tex:5: info [unused] MCP is defined but never used afterwards in the abstract; the expansion alone is enough
paper.tex:11: error [mismatch] "Retrieval Augmented Generation" does not spell RGA; check the letters or the expansion
paper.tex:13: info [redefined] MCP is defined again in the body (first at sections/intro.tex:4)
paper.tex:13: info [re-expanded] "Retrieval Augmented Generation" is spelled out again 1 time(s) after RAG was defined; consider using RAG
paper.tex:14: info [unused] TEE is defined but never used afterwards in the body; the expansion alone is enough
paper.tex:17: error [mismatch] "Graph Network" does not spell GNN; check the letters or the expansion
paper.tex:17: error [conflict] GNN expanded as "Graph Network" but earlier as "Graph Neural Network" (paper.tex:16)
sections/intro.tex:2: warning [undefined] LLM is never defined in the body (only defined in the abstract at paper.tex:4); used 1 time(s)
sections/intro.tex:3: warning [used-before-definition] MCP is used before its definition at sections/intro.tex:4
sections/intro.tex:3: warning [undefined] SOTA is never defined; used 1 time(s)

  GNN  Graph Neural Network  (defined paper.tex:16, 1 use(s))
  LLM  Large Language Models  (defined paper.tex:4, 2 use(s))
  MCP  Model Context Protocol  (defined paper.tex:5, 2 use(s))
  RAG  Retrieval Augmented Generation  (defined sections/intro.tex:2, 1 use(s))
  RGA  Retrieval Augmented Generation  (defined paper.tex:11, 0 use(s))
  TEE  Trusted Execution Environment  (defined paper.tex:14, 0 use(s))

acrodrift: 3 error(s), 3 warning(s), 4 info across 2 file(s), 6 acronym(s) defined
```

## Limitations

Acronyms are tokens of 2 to 10 characters that start with an uppercase letter and contain at least two uppercase letters (an optional plural `s` is fine). Mixed-case names like `LoRA` or `RoBERTa` are not tracked yet. A small built-in allowlist (PDF, URL, HTTP, JSON, roman numerals, and similar) is ignored by default; turn it off with `--no-default-allow`.

## Tests

```bash
python3 -m unittest discover -s tests
```

## License

MIT
