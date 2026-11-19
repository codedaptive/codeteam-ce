"""share/codeteam_program_modules.py (D558): the share/ modules a codeteam program loads, read from its own import
lines, so a promote's restart list follows the code. Unit tests (rule 11): a tree of files written in a temp folder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_program_modules import program_modules


def tree(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def test_the_program_and_its_direct_and_indirect_imports(tmp_path):
    root = tree(tmp_path, {"bin/prog": "import os\nimport codeteam_a\n    from codeteam_b import f\n",
                           "share/codeteam_a.py": "from codeteam_c import g\n",
                           "share/codeteam_b.py": "x = 1\n",
                           "share/codeteam_c.py": "import codeteam_a\n"})
    assert program_modules(root, "bin/prog") == {"bin/prog", "share/codeteam_a.py", "share/codeteam_b.py",
                                                 "share/codeteam_c.py"}


def test_a_module_named_but_not_in_share_is_left_out(tmp_path):
    root = tree(tmp_path, {"bin/prog": "import codeteam_gone\nimport codeteamish\n"})
    assert program_modules(root, "bin/prog") == {"bin/prog"}


def test_a_name_in_a_string_or_a_comment_mid_line_is_not_an_import(tmp_path):
    root = tree(tmp_path, {"bin/prog": "x = 'import codeteam_a'  # from codeteam_b import\n",
                           "share/codeteam_a.py": "", "share/codeteam_b.py": ""})
    assert program_modules(root, "bin/prog") == {"bin/prog"}


def test_a_missing_program_has_no_modules(tmp_path):
    assert program_modules(tmp_path, "bin/codeteam-buildq") == set()
