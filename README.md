# codeteam gamma preview

codeteam runs a git repository as a team of standing Claude Code sessions: an orchestrator, a designer, one
coordinator per lane (a lane owns a set of packages or crates), and assistants such as Kong (reviews every change
before it lands) and Nagatha (integration tests and promotion). Each session works in its own git worktree, inside
walls that hooks enforce; messages between sessions go through a store and are delivered only when the recipient is
ready. Every change lands through one tool, `codeteam-land`, which tests it, has it reviewed, merges it, rechecks
and validates it, and promotes proven commits to the base branch.

This is a **gamma preview** of branch flow v5.4 (`docs/SPEC-branch-flow-v5.4.md`) published by
[codedaptive](https://github.com/codedaptive). Expect rough edges; interfaces may change. It is **macOS only**.

## Prerequisites

- macOS
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [herdr](https://herdr.dev) from Homebrew: `brew install herdr`
- Python 3.12+
- git 2.54+
- Optional: sccache (shared Rust build cache); the CodeGraph MCP server (code search)

## Start here

`docs/QUICKSTART.md`: install, build the example team's agents, `codeteam2 up teams/example.toml`, and how landing
works.

## What is in this repository

| Folder | What |
|---|---|
| `bin/` | `codeteam` (team setup, worktrees, channels, roles), `codeteam-land` (the landing flow), `zone-tool` and the build queue, wrappers for cargo/swift/xcodebuild, checks |
| `v2/` | `codeteam2`, the runtime on herdr: sessions in panes, message delivery, the loop, the dashboard (`codeteam2 deck`) |
| `zone/` | `zone.mk`, the make targets every product gets (`zone-test-one`, `check`, `warm`, ...) |
| `share/` | Claude Code hooks (zone guard, provenance, worktree hooks), launchd templates |
| `roles/` | the role text codeteam appends to each session |
| `catalog/` | the agent catalog: roles, skills, a roster and `generate.py`, which builds a team's agent files; `products/example/` |
| `teams/example.toml` | an example team manifest |
| `docs/` | the branch flow spec, new-team checklist, mission template, quickstart |
| `tests/` | the test suite (`tests/run.sh`, `tests/unit`, `tests/integration`) |
| `scripts/check-public.sh` | a release check: no private names, paths or secrets in the tree |

## Tests

```bash
python3 -m pytest -q tests/unit v2/tests catalog/tests
for f in tests/unit/*.py; do python3 "$f" || echo "FAIL $f"; done
```

## License

MIT; see `LICENSE`.
