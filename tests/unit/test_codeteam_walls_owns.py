"""share/codeteam_walls_owns.py alone: 12 or fewer owned entries render as given; past 12, the files of a folder
holding more than 3 owned files become one item with the folder, the count and the manifest path; folders and globs
are never counted. The call site: render_roles in bin/codeteam.
"""
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("codeteam_walls_owns", ROOT / "share" / "codeteam_walls_owns.py")
module = importlib.util.module_from_spec(spec)
dont_write_bytecode = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
finally:
    sys.dont_write_bytecode = dont_write_bytecode


def test_a_codegraph_host_shaped_lane():
    assert module.walls_owns(
        [
            "src/mcp", "src/sync", "src/bin", "src/db/wal-valve.ts", "src/extensions/host",
            "__tests__/extensions/host", "__tests__/helpers", "__tests__/fixtures",
            "__tests__/a.test.ts", "__tests__/b.test.ts", "__tests__/c.test.ts", "__tests__/d.test.ts",
            "__tests__/e.test.ts", "__tests__/f.test.ts", "__tests__/g.test.ts", "__tests__/h.test.ts",
            "__tests__/i.test.ts", "__tests__/j.test.ts", "__tests__/k.test.ts", "__tests__/l.test.ts",
            "__tests__/m.test.ts", "__tests__/n.test.ts", "__tests__/o.test.ts", "__tests__/p.test.ts",
            "__tests__/q.test.ts", "__tests__/r.test.ts", "__tests__/s.test.ts", "__tests__/t.test.ts",
        ],
        "teams/graph.toml",
    ) == (
        "`src/mcp`, `src/sync`, `src/bin`, `src/db/wal-valve.ts`, `src/extensions/host`, "
        "`__tests__/extensions/host`, `__tests__/helpers`, `__tests__/fixtures`, "
        "`__tests__/`: 20 files (the lane's `owns` in teams/graph.toml)"
    )


def test_a_trailing_slash_entry_is_a_folder_even_with_a_dot():
    assert module.walls_owns(
        [
            "docs", "src/v1.2/", "src/a.py", "src/b.py", "src/c.py", "src/d.py",
            "bin", "tools", "assets", "config", "scripts", "share", "examples",
        ],
        "teams/example.toml",
    ) == (
        "`docs`, `src/v1.2/`, `src/`: 4 files (the lane's `owns` in teams/example.toml), "
        "`bin`, `tools`, `assets`, `config`, `scripts`, `share`, `examples`"
    )


def test_empty_owns_returns_empty_text():
    assert module.walls_owns([], "teams/example.toml") == ""


def test_short_mixed_owns_are_unchanged():
    assert module.walls_owns(
        ["share/a.py", "share/b.py", "share/c.py", "share/d.py", "share/*.py", "docs"],
        "teams/example.toml",
    ) == "`share/a.py`, `share/b.py`, `share/c.py`, `share/d.py`, `share/*.py`, `docs`"


def test_twelve_files_in_one_folder_are_not_collapsed():
    assert module.walls_owns(
        [
            "pkg/a.py", "pkg/b.py", "pkg/c.py", "pkg/d.py", "pkg/e.py", "pkg/f.py",
            "pkg/g.py", "pkg/h.py", "pkg/i.py", "pkg/j.py", "pkg/k.py", "pkg/l.py",
        ],
        "teams/example.toml",
    ) == (
        "`pkg/a.py`, `pkg/b.py`, `pkg/c.py`, `pkg/d.py`, `pkg/e.py`, `pkg/f.py`, "
        "`pkg/g.py`, `pkg/h.py`, `pkg/i.py`, `pkg/j.py`, `pkg/k.py`, `pkg/l.py`"
    )


def test_crowded_folder_collapses_at_first_file_with_count_and_path_manifest():
    assert module.walls_owns(
        [
            "docs", "pkg/a.py", "other/one.py", "pkg/b.py", "lib", "pkg/c.py",
            "pkg/d.py", "pkg/e.py", "tail/one.py", "tail/two.py", "assets", "tools", "bin",
        ],
        Path("teams/example.toml"),
    ) == (
        "`docs`, `pkg/`: 5 files (the lane's `owns` in teams/example.toml), `other/one.py`, "
        "`lib`, `tail/one.py`, `tail/two.py`, `assets`, `tools`, `bin`"
    )


def test_folder_equal_to_crowded_parent_stays_a_separate_item():
    assert module.walls_owns(
        [
            "__tests__/helpers", "__tests__/helpers/a.test.ts", "readme.md",
            "__tests__/helpers/b.test.ts", "src", "__tests__/helpers/c.test.ts",
            "__tests__/helpers/d.test.ts", "docs", "bin", "share", "assets", "config", "scripts",
        ],
        "teams/example.toml",
    ) == (
        "`__tests__/helpers`, `__tests__/helpers/`: 4 files (the lane's `owns` in teams/example.toml), "
        "`readme.md`, `src`, `docs`, `bin`, `share`, `assets`, `config`, `scripts`"
    )


def test_three_files_in_a_folder_are_not_collapsed_in_a_long_list():
    assert module.walls_owns(
        [
            "small/a.py", "small/b.py", "small/c.py", "one", "two", "three", "four",
            "five", "six", "seven", "eight", "nine", "ten",
        ],
        "teams/example.toml",
    ) == (
        "`small/a.py`, `small/b.py`, `small/c.py`, `one`, `two`, `three`, `four`, "
        "`five`, `six`, `seven`, `eight`, `nine`, `ten`"
    )


def test_two_crowded_folders_collapse_separately_in_first_file_order():
    assert module.walls_owns(
        [
            "start", "alpha/a.py", "beta/a.py", "alpha/b.py", "beta/b.py", "middle",
            "beta/c.py", "alpha/c.py", "beta/d.py", "alpha/d.py", "beta/e.py", "end", "solo.txt",
        ],
        "config/lane manifest.toml",
    ) == (
        "`start`, `alpha/`: 4 files (the lane's `owns` in config/lane manifest.toml), "
        "`beta/`: 5 files (the lane's `owns` in config/lane manifest.toml), "
        "`middle`, `end`, `solo.txt`"
    )


def test_globs_are_not_counted_as_files_even_with_suffixes():
    assert module.walls_owns(
        [
            "share/a.py", "share/*.py", "share/b.py", "share/?.py", "share/c.py",
            "share/[ab].py", "docs", "bin", "tools", "src", "assets", "config", "scripts",
        ],
        "teams/example.toml",
    ) == (
        "`share/a.py`, `share/*.py`, `share/b.py`, `share/?.py`, `share/c.py`, "
        "`share/[ab].py`, `docs`, `bin`, `tools`, `src`, `assets`, `config`, `scripts`"
    )
