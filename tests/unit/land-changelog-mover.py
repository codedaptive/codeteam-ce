#!/usr/bin/env -S python3 -u
"""The stamp moves a document's `## Changelog` section to its changelog file: the real heading, never an example inside
a fenced code block (2026-11-11: VERSIONING.md 4.1's example was taken, with the 4.2 heading after it)."""
import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_mover", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

FENCED = """---
version: 4.3.0
---

# Versioning

## 4.1 Where entries go

A document ends with its changelog:

```markdown
## Changelog

### 1.0.0 -- 2026-01-01
```

## 4.2 Levels

Text of 4.2.

## 4.3 Stamps

Text of 4.3.

## Changelog

### 4.3.0 -- 2026-11-10

Real entry.
"""


def test_the_heading_inside_a_code_block_is_not_the_section():
    rest, section = cl.take_changelog_section(FENCED)
    assert section == "### 4.3.0 -- 2026-11-10\n\nReal entry."
    assert "## 4.2 Levels" in rest and "## 4.3 Stamps" in rest and "Text of 4.3." in rest
    assert "```markdown\n## Changelog\n\n### 1.0.0" in rest
    assert rest.rstrip().endswith("Text of 4.3.")


def test_a_section_followed_by_another_keeps_the_later_one():
    rest, section = cl.take_changelog_section("# D\n\n## Changelog\n\n- one\n\n## Notes\n\nkept\n")
    assert section == "- one"
    assert rest == "# D\n\n## Notes\n\nkept\n"


def test_only_a_fenced_heading_means_no_section():
    text = "# D\n\n~~~\n## Changelog\n~~~\n\nbody\n"
    assert cl.take_changelog_section(text) == (text, "")


def test_a_longer_fence_closes_only_on_its_own_length():
    text = "# D\n\n````\n```\n## Changelog\n```\n````\n\n## Changelog\n\n- real\n"
    rest, section = cl.take_changelog_section(text)
    assert section == "- real" and "````\n```\n## Changelog" in rest


def test_no_section_leaves_the_text_alone():
    assert cl.take_changelog_section("# D\n\nbody\n") == ("# D\n\nbody\n", "")


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
