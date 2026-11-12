<div align="center">

# codeteam

### A team of AI coding agents that ships working code.

</div>

One agent writing code is easy. Many agents writing code in the same repository at
once is where things break: work collides, tests rot, and nobody can say what
actually shipped. codeteam turns that crowd into a team.

It runs a git repository as a standing crew of Claude Code sessions: an
orchestrator, a designer (Skippy), a coordinator for each part of the code, a
reviewer (Kong) and an integration builder (Nagatha). Each works in its own folder, inside walls the tools
enforce. Every change reaches the main branch the same way: tested, reviewed,
merged, rechecked and validated, then promoted only when it is proven.

<div align="center">

**The agents write the code. The landing flow decides what ships.**

</div>

[![release](https://img.shields.io/github/v/release/codedaptive/codeteam-ce?include_prereleases&label=release&color=success)](https://github.com/codedaptive/codeteam-ce/releases)
![platforms](https://img.shields.io/badge/platforms-macOS-blue)
![license](https://img.shields.io/badge/license-MIT-success)

> **Gamma preview.** This is branch flow v5.4 ([`docs/SPEC-branch-flow-v5.4.md`](docs/SPEC-branch-flow-v5.4.md)),
> released early to help people now. Expect rough edges; interfaces may change. macOS only.

## Works with

- **[MOOTx01 CE](https://github.com/codedaptive/mootx01-ce)**: compatible with the MOOTx01 memory system, so
  agents keep what they learn across sessions, models and machines.
- **[CodeGraph Hub](https://github.com/codedaptive/codegraph-hub)**: compatible with CodeGraph's pre-indexed code
  knowledge graph, so agents find callers, impact and tests without grepping the repo
  (`mcp.example.json` shows the setup).

Both are optional.

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
