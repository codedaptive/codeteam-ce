"""Which repo test scripts a change reaches (D491, creator #4379 Q-stage2-reach2; D562).

A repo's tests/integration folder holds scripts with no package manifest, so zone-tool's scope cannot narrow it. A
script reaches what it names, and what those name in turn: a tracked file is named by its repo path anywhere in the
text, by its base name as a whole token, or, for a Python module, by `import <stem>` or `from <stem> import`. Every
doubt runs more: a changed non-test file nothing names (a manifest, a data file read through a computed path) or a
changed helper beside the scripts runs the whole folder, and a script that names nothing tracked always runs. A changed
test file nothing names (codeteam_test_file.is_test_file) reaches no script (D562): it runs with its own zone's tests.
"""
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from codeteam_test_file import is_test_file

TOKEN = re.compile(r"[\w.-]+")
PATHLIKE = re.compile(r"[\w./-]+")
IMPORT = re.compile(r"(?<![\w.])(?:import\s+(\w+)|from\s+(\w+)\s+import\b)")


def _trie(paths):
    root = {}
    for path in paths:
        node = root
        for ch in path:
            node = node.setdefault(ch, {})
        node[""] = path
    return root


def _named(text: str, trie: dict, odd: list[str], by_base: dict, by_stem: dict) -> set[str]:
    """The paths `text` names. A path of [\\w./-] with a folder lies inside a run of those characters holding a "/",
    so walking the trie from every position of such a run finds every occurrence; other paths are looked for one by
    one."""
    found = {path for path in odd if path in text}
    for run in PATHLIKE.findall(text):
        if "/" not in run:
            continue
        for start in range(len(run)):
            node = trie
            for ch in run[start:]:
                node = node.get(ch)
                if node is None:
                    break
                if "" in node:
                    found.add(node[""])
    for token in set(TOKEN.findall(text)):
        found |= by_base.get(token, set())
    for match in IMPORT.finditer(text):
        found |= by_stem.get(match.group(1) or match.group(2), set())
    return found


def _scripts(root: Path, folder: str, prefix: str) -> list[str]:
    """The folder's top-level *.py and *.sh but conftest.py and __init__.py, sorted repo paths."""
    return sorted(f"{prefix}{p.name}" for pattern in ("*.py", "*.sh") for p in (root / folder).glob(pattern)
                  if p.is_file() and p.name not in ("conftest.py", "__init__.py"))


def _nodes(tree, docs: tuple[str, ...], tests: list[str], changed: list[str]) -> list[str]:
    """Every tracked non-doc file, plus the scripts and the changed files, sorted."""
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=tree, capture_output=True, text=True, check=True).stdout
    return sorted({p for p in listed.split("\0") if p and not p.endswith(docs)} | set(tests) | set(changed))


def _lookups(nodes: list[str]) -> tuple[dict, list[str], dict, dict]:
    """_named's lookups over `nodes`: the trie of folder paths of [\\w./-], the other paths, and the paths by base name
    and by Python stem."""
    by_base, by_stem = defaultdict(set), defaultdict(set)
    for path in nodes:
        base = path.rsplit("/", 1)[-1]
        by_base[base].add(path)
        if base.endswith(".py"):
            by_stem[base[:-3]].add(path)
    simple = [p for p in nodes if "/" in p and PATHLIKE.fullmatch(p)]
    return _trie(simple), sorted(set(nodes) - set(simple)), by_base, by_stem


def _namers(root: Path, nodes: list[str]) -> tuple[defaultdict, set[str]]:
    """Each node's namers, and the nodes that name nothing or cannot be read (those always run)."""
    trie, odd, by_base, by_stem = _lookups(nodes)
    namers, runs_always = defaultdict(set), set()
    for path in nodes:
        try:
            text = (root / path).read_text(errors="replace")
        except OSError:
            runs_always.add(path)
            continue
        named = _named(text, trie, odd, by_base, by_stem) - {path}
        if not named:
            runs_always.add(path)
        for target in named:
            namers[target].add(path)
    return namers, runs_always


def _selected(tests: list[str], changed: list[str], namers: defaultdict, runs_always: set[str]) -> list[str]:
    """The scripts in `tests` that are changed or name a changed file, directly or through files that name it in turn,
    and those that always run."""
    reaching, todo = set(changed), list(changed)
    while todo:
        for namer in namers[todo.pop()] - reaching:
            reaching.add(namer)
            todo.append(namer)
    return [t for t in tests if t in reaching or t in runs_always]


def _unnamed_non_test(changed: list[str], tests: list[str], namers: defaultdict) -> bool:
    """Whether a changed file other than a script is named by nothing and is no test file (D562: an unnamed test file
    runs with its own zone's tests and reaches no script)."""
    return any(not namers[f] and f not in tests and not is_test_file(f) for f in changed)


def reaching_tests(tree, folder: str, files: list[str], docs: tuple[str, ...]) -> list[str] | None:
    """The test files in `folder` (its top-level *.py and *.sh but conftest.py and __init__.py), sorted repo paths,
    whose reach holds a changed non-doc file in `files`, plus the scripts that name nothing tracked; None to run the
    whole folder (a changed file in `folder` that is not one of its scripts, or a changed non-test file nothing
    names); [] when only documents changed. A changed test file nothing names reaches no script (D562)."""
    changed = [f for f in files if not f.endswith(docs)]
    if not changed:
        return []
    root, prefix = Path(tree), folder.strip("/") + "/"
    tests = _scripts(root, folder, prefix)
    if any(f.startswith(prefix) and f not in tests for f in changed):
        return None
    namers, runs_always = _namers(root, _nodes(tree, docs, tests, changed))
    if _unnamed_non_test(changed, tests, namers):
        return None
    return _selected(tests, changed, namers, runs_always)
