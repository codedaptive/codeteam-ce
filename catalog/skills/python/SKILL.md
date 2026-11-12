---
name: python
description: Python rules for coders, test writers and reviewers - run through the repo's make targets or recorded scripts, tests with pytest, typed and plain code.
---

# Python

- **Run through the repo's make targets or recorded scripts** (the product layer names them), never a one-off
  command whose output nobody can regenerate.
- Tests with `pytest`, beside the code they test or under the folder the product layer names. One behaviour per test.
- Standard library first; a new dependency only if your brief names it, pinned where the repo pins.
- Type hints on public functions. No bare `except:`; catch what you handle and let the rest raise.
- Paths with `pathlib`, never string concatenation. No hardcoded absolute paths to a person's machine in committed code.
- Edit JSON, YAML and TOML with a parser (`json`, `tomllib`), never regex.
- Scripts that produce numbers write their inputs, outputs and the command line where the product layer says
  receipts go, so the run can be repeated.
