import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from acrodrift.core import analyze, schwartz_hearst, find_long_form  # noqa: E402
from acrodrift.cli import main  # noqa: E402


def write(d, name, text):
    path = os.path.join(d, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(textwrap.dedent(text))
    return path


def kinds(report, acr=None):
    return sorted((f.kind, f.acronym) for f in report.findings if acr is None or f.acronym == acr)


class LongFormTests(unittest.TestCase):
    def test_schwartz_hearst_basic(self):
        self.assertEqual(schwartz_hearst("MCP", "tools through the Model Context Protocol"), "Model Context Protocol")

    def test_plural_lowercase(self):
        lf, ok = find_long_form("LLM", "we study large language models")
        self.assertEqual(lf, "large language models")
        self.assertTrue(ok)

    def test_out_of_order_letters_is_mismatch(self):
        lf, ok = find_long_form("RGA", "evaluate with Retrieval Augmented Generation")
        self.assertEqual(lf, "Retrieval Augmented Generation")
        self.assertFalse(ok)

    def test_parenthetical_use_is_not_definition(self):
        lf, ok = find_long_form("GPU", "runs on a commodity accelerator, e.g.,")
        self.assertIsNone(lf)


class AnalyzeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def run_tex(self, body, **kw):
        p = write(self.d, "main.tex", body)
        return analyze([p], **kw)

    def test_clean_document_has_no_findings(self):
        r = self.run_tex(r"""
        We use Retrieval-Augmented Generation (RAG). RAG helps, and RAG is cheap.
        """)
        self.assertEqual(r.findings, [])

    def test_undefined_and_before_definition(self):
        r = self.run_tex(r"""
        The SOTA method uses RAG. Later, Retrieval Augmented Generation (RAG) is defined. RAG again.
        """)
        self.assertIn(("undefined", "SOTA"), kinds(r))
        self.assertIn(("used-before-definition", "RAG"), kinds(r))

    def test_conflict_between_expansions(self):
        r = self.run_tex(r"""
        A Graph Neural Network (GNN) is used. The GNN works.
        Later the Generative Neural Network (GNN) appears. GNN.
        """)
        self.assertIn(("conflict", "GNN"), kinds(r))

    def test_plural_definition_counts(self):
        r = self.run_tex(r"""
        Large language models (LLMs) are big. LLMs and an LLM.
        """)
        self.assertEqual(kinds(r), [])

    def test_abstract_scope(self):
        r = self.run_tex(r"""
        \begin{abstract}
        We study Large Language Models (LLMs). LLMs matter.
        \end{abstract}
        In the body, LLM agents are everywhere.
        """)
        self.assertIn(("undefined", "LLM"), kinds(r))
        r2 = analyze([os.path.join(self.d, "main.tex")], abstract_scope=False)
        self.assertNotIn(("undefined", "LLM"), kinds(r2))

    def test_masking_comments_math_refs_cites(self):
        r = self.run_tex(r"""
        Text % ZZZ in a comment
        see Table~\ref{tab:RES} and \cite{KDD2024} with $O(NM)$ and
        \begin{equation} XY = Z \end{equation}
        \url{https://example.com/ABC} done.
        """)
        self.assertEqual(kinds(r), [])

    def test_input_following_preserves_order_and_lines(self):
        write(self.d, "sec/a.tex", "\nHere TEE is used first.\n")
        p = write(self.d, "main.tex", r"""\input{sec/a}
        A Trusted Execution Environment (TEE) is used. TEE again.
        """)
        r = analyze([p])
        f = [x for x in r.findings if x.kind == "used-before-definition"][0]
        self.assertEqual(f.file, os.path.join("sec", "a.tex"))
        self.assertEqual(f.line, 2)

    def test_unused_definition(self):
        r = self.run_tex("A Trusted Execution Environment (TEE) appears once.\n")
        self.assertEqual(kinds(r), [("unused", "TEE")])

    def test_redefined_same_scope(self):
        r = self.run_tex("Model Context Protocol (MCP). MCP. Model Context Protocol (MCP). MCP.\n")
        self.assertIn(("redefined", "MCP"), kinds(r))

    def test_reexpanded(self):
        r = self.run_tex("Model Context Protocol (MCP) and MCP. Later the model context protocol again.\n")
        self.assertIn(("re-expanded", "MCP"), kinds(r))

    def test_glossary_raw_use_and_unused(self):
        r = self.run_tex(r"""
        \newacronym{llm}{LLM}{large language model}
        \newacronym{tee}{TEE}{trusted execution environment}
        First \ac{llm}. Then a raw LLM sneaks in.
        """)
        self.assertIn(("raw-use", "LLM"), kinds(r))
        self.assertIn(("unused", "TEE"), kinds(r))
        self.assertNotIn(("undefined", "LLM"), kinds(r))

    def test_allowlist(self):
        r = self.run_tex("The SOTA result.\n", allow={"SOTA"})
        self.assertEqual(kinds(r), [])

    def test_markdown(self):
        p = write(self.d, "README.md", """
        Uses `CLI` inline code and the CI pipeline.

        ```
        ABC in code
        ```
        Continuous Integration (CI) runs. CI again.
        """)
        r = analyze([p])
        self.assertEqual(kinds(r), [("used-before-definition", "CI")])


class CliTests(unittest.TestCase):
    def test_example_json_and_exit_codes(self):
        ex = os.path.join(ROOT, "examples", "paper.tex")
        out = subprocess.run([sys.executable, "-m", "acrodrift", ex, "--format", "json"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 1)
        data = json.loads(out.stdout)
        got = {(f["kind"], f["acronym"]) for f in data["findings"]}
        for want in [("mismatch", "RGA"), ("conflict", "GNN"), ("undefined", "SOTA"),
                     ("undefined", "LLM"), ("used-before-definition", "MCP"), ("re-expanded", "RAG")]:
            self.assertIn(want, got)
        self.assertNotIn(("undefined", "XYZ"), got)

    def test_fail_on_never_and_missing_file(self):
        ex = os.path.join(ROOT, "examples", "paper.tex")
        self.assertEqual(main([ex, "--fail-on", "never", "--format", "json"]), 0)
        self.assertEqual(main([os.path.join(ROOT, "nope.tex")]), 2)


if __name__ == "__main__":
    unittest.main()
