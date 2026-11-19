import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_doc_fix_refusal import doc_fix_refusal


def test_wrong_branch_precedes_all_other_refusals():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": False,
             "head": "aaaaaaaaaaaa", "tip": "bbbbbbbbbbbb", "changed": [],
             "outside": ["outside.md"], "code": ["code.py"]}
    assert doc_fix_refusal(facts) == (
        "docfix: its tree is not on its branch feature (a land's set merge?); put it back first"
    )


def test_wrong_head_precedes_empty_delta_and_names_short_tips():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "0123456789abcdef", "tip": "fedcba9876543210", "changed": [],
             "outside": ["outside.md"], "code": ["code.py"]}
    assert doc_fix_refusal(facts) == (
        "docfix: its tree's HEAD 0123456789 is not its reviewed tip fedcba9876; "
        "doc-fix commits only on the reviewed tip"
    )


def test_empty_delta_precedes_wall_and_code_refusals():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": [],
             "outside": ["outside.md"], "code": ["code.py"]}
    assert doc_fix_refusal(facts) == "docfix: nothing to commit"


def test_outside_files_precede_code_and_are_each_named():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": ["a.md", "b.md", "code.py"],
             "outside": ["a.md", "b.md"], "code": ["code.py"]}
    assert doc_fix_refusal(facts) == (
        "docfix: changes files outside its zone (walls):\n  a.md\n  b.md"
    )


def test_code_files_are_each_named():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": ["a.py", "b.rs"],
             "outside": [], "code": ["a.py", "b.rs"]}
    assert doc_fix_refusal(facts) == (
        "docfix: not comment- or doc-only (these read as code; file them as findings):"
        "\n  a.py\n  b.rs"
    )


def test_unit_move_is_refused_and_path_named():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": ["tests/unit/test_x.py"],
             "outside": [], "code": [], "unit_moves": ["tests/unit/test_x.py"]}
    reason = doc_fix_refusal(facts)
    assert reason is not None
    assert reason.startswith("docfix: moves tests into the unit group")
    assert "tests/unit/test_x.py" in reason


def test_outside_refusal_precedes_unit_move():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": ["tests/unit/test_x.py"],
             "outside": ["outside.py"], "code": ["tests/unit/test_x.py"],
             "unit_moves": ["tests/unit/test_x.py"]}
    assert doc_fix_refusal(facts).startswith("docfix: changes files outside its zone")


def test_unit_move_refusal_precedes_code():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": ["tests/unit/test_x.py"],
             "outside": [], "code": ["tests/unit/test_x.py"],
             "unit_moves": ["tests/unit/test_x.py"]}
    assert doc_fix_refusal(facts).startswith("docfix: moves tests into the unit group")


def test_doc_and_comment_only_delta_is_allowed():
    facts = {"wo": "docfix", "branch": "feature", "on_branch": True,
             "head": "old", "tip": "old", "changed": ["guide.md", "comment.py"],
             "outside": [], "code": []}
    assert doc_fix_refusal(facts) is None
