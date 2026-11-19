#!/usr/bin/env -S python3 -u
"""Comment-only work orders: code_text takes the comments out of a file by its
language, and two versions with the same result differ only in comments. What a tool reads stays code: Rust doc
comments that hold a code block, Swift doc comments with a compiled snippet, Python docstrings and directive
comments. Pure functions, no git."""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_comment_only", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)
cl.v54_unmoved = Mock(return_value=False)


class Same(unittest.TestCase):
    """same(path, a, b): True when a and b differ only in comments; None when the file has no rule or cannot be read."""

    def same(self, path, a, b):
        x, y = cl.code_text(path, a), cl.code_text(path, b)
        return None if x is None or y is None else x == y

    def comment(self, path, a, b):
        self.assertIs(self.same(path, a, b), True, (cl.code_text(path, a), cl.code_text(path, b)))

    def code(self, path, a, b):
        self.assertIsNot(self.same(path, a, b), True, (cl.code_text(path, a), cl.code_text(path, b)))


class Rust(Same):
    def test_line_comment_change_is_comment_only(self):
        self.comment("a.rs", "fn f() {} // one\n", "fn f() {} // two\n")

    def test_added_and_removed_comment_lines_are_comment_only(self):
        self.comment("a.rs", "fn f() {\n    let x = 1;\n}\n", "// header\nfn f() {\n    // why\n    let x = 1;\n}\n")

    def test_nested_block_comment_is_comment_only(self):
        self.comment("a.rs", "fn f() { /* a /* b */ c */ g(); }\n", "fn f() { /* changed /* inner */ too */ g(); }\n")

    def test_doc_comment_without_a_code_block_is_comment_only(self):
        self.comment("a.rs", "/// Reads a row.\npub fn read() {}\n", "/// Reads one row, or none.\npub fn read() {}\n")
        self.comment("a.rs", "//! The crate.\nfn f() {}\n", "//! The crate, said better.\nfn f() {}\n")

    def test_comment_change_inside_a_doc_test_block_is_code(self):
        # The first case asked for: a doc test is compiled and run, so a change inside its block lands normally.
        base = "/// Reads.\n///\n/// ```\n/// let x = read(); // one\n/// ```\npub fn read() {}\n"
        self.code("a.rs", base, base.replace("// one", "// two"))

    def test_prose_change_in_a_doc_comment_with_a_code_block_is_code(self):
        base = "/// Reads.\n///\n/// ```\n/// read();\n/// ```\npub fn read() {}\n"
        self.code("a.rs", base, base.replace("Reads.", "Reads a row."))

    def test_doc_block_split_by_a_blank_line_is_one_group(self):
        base = "/// ```\n\n/// let x = 1;\n/// ```\npub fn read() {}\n"
        self.code("a.rs", base, base.replace("x = 1", "x = 2"))

    def test_a_new_doc_test_is_code(self):
        self.code("a.rs", "/// Reads.\npub fn read() {}\n", "/// Reads.\n/// ```\n/// read();\n/// ```\npub fn read() {}\n")

    def test_tilde_fence_and_indented_block_and_inner_doc_are_code(self):
        self.code("a.rs", "//! ~~~\n//! a();\n//! ~~~\n", "//! ~~~\n//! b();\n//! ~~~\n")
        self.code("a.rs", "/// Text.\n///\n///     a();\nfn f() {}\n", "/// Text.\n///\n///     b();\nfn f() {}\n")
        self.code("a.rs", "/** ```\n a();\n``` */\nfn f() {}\n", "/** ```\n b();\n``` */\nfn f() {}\n")

    def test_four_slashes_and_plain_blocks_are_ordinary_comments(self):
        self.comment("a.rs", "//// ```\n//// a\nfn f() {}\n", "//// ```\n//// b\nfn f() {}\n")
        self.comment("a.rs", "/*** ``` a */ fn f() {}\n", "/*** ``` b */ fn f() {}\n")

    def test_slashes_inside_a_string_are_code(self):
        self.code("a.rs", 'let u = "http://a";\n', 'let u = "http://b";\n')
        self.code("a.rs", 'let u = "a \\" // b";\n', 'let u = "a \\" // c";\n')

    def test_slashes_inside_a_raw_string_are_code(self):
        self.code("a.rs", 'let u = r#"say "x" // a"#;\n', 'let u = r#"say "x" // b"#;\n')
        self.code("a.rs", 'let u = br"// a";\n', 'let u = br"// b";\n')

    def test_a_quote_char_literal_does_not_open_a_string(self):
        self.comment("a.rs", "let q = '\"'; // a\nlet r = 1;\n", "let q = '\"'; // b\nlet r = 1;\n")
        self.code("a.rs", "let q = '\"'; // a\nlet r = 1;\n", "let q = '\"'; // a\nlet r = 2;\n")

    def test_a_lifetime_is_code_and_a_comment_beside_it_is_not(self):
        self.comment("a.rs", "fn f<'a>(x: &'a str) {} // a\n", "fn f<'a>(x: &'a str) {} // b\n")
        self.code("a.rs", "fn f<'a>(x: &'a str) {}\n", "fn f<'b>(x: &'b str) {}\n")

    def test_a_code_change_is_code(self):
        self.code("a.rs", "fn f() { g(); }\n", "fn f() { h(); }\n")

    def test_an_unterminated_comment_cannot_be_read(self):
        self.assertIsNone(cl.code_text("a.rs", "fn f() {} /* open\n"))
        self.assertIsNone(cl.code_text("a.rs", 'let s = "open;\n'))


class Swift(Same):
    def test_line_and_nested_block_comment_change_is_comment_only(self):
        self.comment("a.swift", "func f() {} // a\n/* x /* y */ z */\n", "func f() {} // b\n/* p /* q */ r */\n")

    def test_a_doc_comment_change_is_comment_only_code_block_or_not(self):
        # Swift compiles no block in a doc comment, only a snippet file named by @Snippet (the rule:
        # "Swift /// doc comments with compiled snippets").
        base = "/// Opens.\n///\n/// ```swift\n/// open()\n/// ```\npublic func open() {}\n"
        self.comment("a.swift", base, base.replace("open()\n///", "open(1)\n///"))
        self.comment("a.swift", base, base.replace("Opens.", "Opens the store."))
        self.comment("a.swift", "/// Opens.\npublic func open() {}\n", "/// Opens it.\npublic func open() {}\n")
        self.code("a.swift", base, base.replace("open() {}", "open(_ x: Int) {}"))

    def test_prose_around_a_fenced_table_is_comment_only(self):
        # LocusKit's AssociationOperational.swift, a bit-layout table fenced in its type's doc comment
        # and the prose below it reworded.
        base = ("/// Three axes pack into the low 20 bits:\n///\n/// ```\n/// bits 0-11   signal_sources_seen\n"
                "/// bits 12-17  decay_class\n/// ```\n///\n/// more than one source can be set at once (an\n"
                "/// association seen by both carries both bits).\npublic struct S {}\n")
        self.comment("a.swift", base, base.replace("(an\n/// association seen by both carries both bits)",
                                                     "(a value with both\n/// bits set holds both)"))

    def test_snippet_directive_is_code(self):
        self.code("a.swift", "/// @Snippet(path: \"a\")\nfunc f() {}\n", "/// @Snippet(path: \"b\")\nfunc f() {}\n")
        snippet = "/// Opens.\n///\n/// @Snippet(path: \"a\")\npublic func open() {}\n"
        self.code("a.swift", snippet, snippet.replace("Opens.", "Opens the store."))

    def test_interpolation_holding_slashes_then_a_code_change_is_code(self):
        a = 'let s = "\\(f("//"))"\nlet x = 1\n'
        self.code("a.swift", a, a.replace("x = 1", "x = 2"))
        self.comment("a.swift", a, a.replace("let x = 1", "let x = 1 // note"))

    def test_multiline_and_raw_strings_are_code(self):
        self.code("a.swift", 'let s = """\n// a\n"""\n', 'let s = """\n// b\n"""\n')
        self.code("a.swift", 'let s = #"say "x" // a"#\n', 'let s = #"say "x" // b"#\n')

    def test_extended_regex_holding_slashes_then_a_code_change_is_code(self):
        a = "let r = #/http://x/#\nlet y = 1\n"
        self.code("a.swift", a, a.replace("y = 1", "y = 2"))
        self.code("a.swift", a, a.replace("http://x", "http://z"))

    def test_swiftlint_directive_is_code(self):
        self.code("a.swift", "// swiftlint:disable all\nfunc f() {}\n", "// swiftlint:disable:next all\nfunc f() {}\n")

    def test_a_space_removed_between_operator_and_operand_is_code(self):
        self.code("a.swift", "let x = a - b\n", "let x = a -b\n")


class Python(Same):
    def test_comment_change_is_comment_only(self):
        self.comment("a.py", "x = 1  # one\n\n# block\ndef f():\n    return x\n",
                     "x = 1  # two\n\ndef f():\n    # inside\n    return x\n")

    def test_docstring_change_is_code(self):
        self.code("a.py", 'def f():\n    """One."""\n', 'def f():\n    """Two."""\n')

    def test_directive_comments_are_code(self):
        self.code("a.py", "import a  # noqa\n", "import a\n")
        self.code("a.py", "x = f()  # type: ignore\n", "x = f()\n")
        self.code("a.py", "x = []  # type: list[int]\n", "x = []  # type: list[str]\n")
        self.code("a.py", "# -*- coding: utf-8 -*-\nx = 1\n", "# -*- coding: latin-1 -*-\nx = 1\n")
        self.code("a.py", "#!/usr/bin/env python3\nx = 1\n", "#!/usr/bin/env python3.11\nx = 1\n")
        self.code("a.py", "x = 1  # pragma: no cover\n", "x = 1\n")

    def test_hash_inside_a_string_is_code(self):
        self.code("a.py", 'x = "# a"\n', 'x = "# b"\n')

    def test_indentation_is_code(self):
        self.code("a.py", "if a:\n    b()\nc()\n", "if a:\n    b()\n    c()\n")

    def test_unreadable_python_is_not_comment_only(self):
        self.assertIsNone(cl.code_text("a.py", 'x = """open\n'))


class Toml(Same):
    def test_comment_change_is_comment_only(self):
        self.comment("Cargo.toml", '[dependencies]\nserde = "1" # one\n', '# top\n[dependencies]\nserde = "1" # two\n')

    def test_hash_inside_strings_is_code(self):
        self.code("Cargo.toml", 'a = "x # one"\n', 'a = "x # two"\n')
        self.code("Cargo.toml", "a = 'x # one'\n", "a = 'x # two'\n")
        self.code("Cargo.toml", 'a = """\n# one\n"""\n', 'a = """\n# two\n"""\n')


class NoRule(Same):
    def test_a_language_without_a_rule_counts_as_code(self):
        for path in ("run.sh", "a.ts", "a.js", "ci.yaml", "Makefile", "bin/codeteam-land"):
            self.assertIsNone(cl.code_text(path, "# a\n"), path)


class Kind(unittest.TestCase):
    """no_build_kind: documents alone are docs-only; otherwise comment_only decides, measured from the tree's own base."""

    def setUp(self):
        self.moves_patch = patch.object(cl, "diff_test_moves", return_value=None, create=True)
        self.moves = self.moves_patch.start()
        self.addCleanup(self.moves_patch.stop)
        self.diff_patch = patch.object(cl, "diff_code_files", return_value=(["a.rs"], ["a.rs"]))
        self.diff_patch.start()
        self.addCleanup(self.diff_patch.stop)

    def team(self):
        team = Mock()
        team.c.side_effect = lambda key, default: default
        return team

    def test_documents_alone_are_docs_only_without_reading_git(self):
        with patch.object(cl, "comment_only") as asked:
            self.assertEqual(cl.no_build_kind(self.team(), {"tree": "/t"}, ["a.md"]), "docs-only")
            self.assertEqual(cl.no_build_kind(self.team(), {"tree": "/t"}, []), "docs-only")
        asked.assert_not_called()

    def test_code_files_ask_comment_only_from_the_own_base(self):
        with patch.object(cl, "own_base", return_value="B") as base, \
                patch.object(cl, "comment_only", return_value=True) as asked:
            self.assertEqual(cl.no_build_kind(self.team(), {"tree": "/t"}, ["a.rs", "a.md"]), "comment-only")
        base.assert_called_once()
        asked.assert_called_once_with("/t", "B", (".md",))
        with patch.object(cl, "own_base", return_value="B"), patch.object(cl, "comment_only", return_value=False):
            self.assertIsNone(cl.no_build_kind(self.team(), {"tree": "/t"}, ["a.rs"]))

    def test_integration_move_skips_build_and_records_moves(self):
        move = {"path": "tests/integration/test_x.py", "from": "tests/unit/test_x.py",
                "to": "tests/integration/test_x.py", "group": "integration"}
        self.moves.return_value = ([move], [])
        rec = {"tree": "/t"}
        with patch.object(cl, "own_base", return_value="B"), patch.object(cl, "comment_only", return_value=False):
            self.assertEqual(cl.no_build_kind(self.team(), rec, [move["path"]]), "test-move")
        self.assertEqual(rec["moved_tests"], [move])

    def test_unit_move_with_code_left_builds(self):
        move = {"path": "tests/unit/test_x.py", "from": "tests/integration/test_x.py",
                "to": "tests/unit/test_x.py", "group": "unit"}
        self.moves.return_value = ([move], [move["path"]])
        with patch.object(cl, "own_base", return_value="B"), patch.object(cl, "comment_only", return_value=False):
            self.assertIsNone(cl.no_build_kind(self.team(), {"tree": "/t"}, [move["path"]]))

    def test_validation_move_skips_build(self):
        move = {"path": "tests/validation/test_x.py", "from": "tests/unit/test_x.py",
                "to": "tests/validation/test_x.py", "group": "validation"}
        self.moves.return_value = ([move], [])
        with patch.object(cl, "own_base", return_value="B"), patch.object(cl, "comment_only", return_value=False):
            self.assertEqual(cl.no_build_kind(self.team(), {"tree": "/t"}, [move["path"]]), "test-move")

    def test_failed_move_diff_builds(self):
        self.moves.return_value = None
        with patch.object(cl, "own_base", return_value="B"), patch.object(cl, "comment_only", return_value=False):
            self.assertIsNone(cl.no_build_kind(self.team(), {"tree": "/t"}, ["a.rs"]))

    def test_a_git_failure_is_a_normal_landing(self):
        with patch.object(cl, "own_base", return_value="B"), patch.object(cl, "comment_only", side_effect=OSError):
            self.assertIsNone(cl.no_build_kind(self.team(), {"tree": "/t"}, ["a.rs"]))


class CommentOnlyDiff(unittest.TestCase):
    """comment_only reads git's raw diff: an added, deleted or mode-changed code file is code."""

    def raw(self, *rows):
        return SimpleNamespace(returncode=0, stdout="".join(f"{meta}\0{path}\0" for meta, path in rows), stderr="")

    def run_with(self, rows, blobs):
        with patch.object(cl, "git", return_value=self.raw(*rows)), \
                patch.object(cl, "_blob", side_effect=lambda tree, sha: blobs.get(sha)):
            return cl.comment_only("/t", "B", (".md",))

    def test_modified_file_with_only_a_comment_changed(self):
        rows = [(":100644 100644 aa bb M", "src/a.rs"), (":100644 100644 cc dd M", "README.md")]
        self.assertTrue(self.run_with(rows, {"aa": "fn f() {} // a\n", "bb": "fn f() {} // b\n"}))

    def test_added_deleted_or_mode_changed_code_file_is_code(self):
        blobs = {"aa": "fn f() {}\n", "bb": "fn f() {}\n"}
        self.assertFalse(self.run_with([(":000000 100644 00 bb A", "src/new.rs")], blobs))
        self.assertFalse(self.run_with([(":100644 000000 aa 00 D", "src/old.rs")], blobs))
        self.assertFalse(self.run_with([(":100644 100755 aa bb M", "src/a.rs")], blobs))

    def test_a_file_without_a_rule_or_without_text_is_code(self):
        self.assertFalse(self.run_with([(":100644 100644 aa bb M", "run.sh")], {"aa": "# a\n", "bb": "# b\n"}))
        self.assertFalse(self.run_with([(":100644 100644 aa bb M", "a.rs")], {"aa": None, "bb": "x"}))

    def test_nothing_changed_is_not_comment_only(self):
        self.assertFalse(self.run_with([], {}))


class Records(unittest.TestCase):
    """The landing row says 'comment-only: no build, no tests'; such a landing never triggers another's recheck."""

    def test_intervening_landings_for_a_recheck_skip_comment_only_rows(self):
        # A docs-only row stays: overlapping() drops its documents, so code a merge brought still counts.
        with tempfile.TemporaryDirectory() as tmp:
            team = SimpleNamespace(dir=Path(tmp), repo=Path(tmp))
            rows = [{"hash": "h1", "range": "a..h1", "wos": ["code"]},
                    {"hash": "h2", "range": "h1..h2", "wos": ["comments"], "no_build": "comment-only: no build, no tests"},
                    {"hash": "h3", "range": "h2..h3", "wos": ["docs"], "no_build": "docs-only: no build, no tests"}]
            (Path(tmp) / "landed.log").write_text("".join(json.dumps(r) + "\n" for r in rows))
            # Neither landing is in the base; both are in landing.
            git = lambda cwd, *args, check=True: SimpleNamespace(returncode=1 if args[-1] == "base" else 0, stdout="")
            with patch.object(cl, "git", side_effect=git), patch.object(cl, "out", return_value="A/x.rs"):
                every = cl.intervening_landings(team, "base", "old")
                builds = cl.intervening_landings(team, "base", "old", builds=True)
        self.assertEqual([wo for wo, _ in every], ["code", "comments", "docs"])
        self.assertEqual([wo for wo, _ in builds], ["code", "docs"])

    def test_label(self):
        self.assertEqual(cl.no_build_label("comment-only"), "comment-only: no build, no tests")


if __name__ == "__main__":
    unittest.main(verbosity=1)
