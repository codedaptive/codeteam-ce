<div align="center">

# CodeTeam - Gamma Release

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

> **Gamma preview.** This is parked branch v5.4 ([`docs/SPEC-branch-flow-v5.4.md`](docs/SPEC-branch-flow-v5.4.md)),
- Why is it a Gamma release? Because this is completely working version that can people can
use and build from.... but it requires a lot of disk space for big projects. A single machine can
handle 40-60 parallel worktrees from a mono repo but will be contrained by disk more than compute.
- The next release will be CodeTeam-JJ which will fold in Jujutsu for massive disk savings.
- This release will stand as it is for pure GIT for multi machine and network storage users.
- CodeTeam-JJ will also be release the same way but seperate. 
- CTJJ will allow about 30 software factories to run on a single high end Mac Laptop without a problem; your agents will be able 
to migration from CT to CTJJ.  
- Forge will then replace CTJJ and wrap GIT, GITHUB, JJ, Tessera, Mortar, and T3 Code into a full maintained software factory agent migration from version to version.
- This version will receive bug fixes but no enhancements are planned it is feature complete.

## Works with

- **[MOOTx01 CE](https://github.com/codedaptive/mootx01-ce)**: compatible with the MOOTx01 memory system, so
  agents keep what they learn across sessions, models and machines.
- **[CodeGraph Hub](https://github.com/codedaptive/codegraph-hub)**: compatible with CodeGraph's pre-indexed code
  knowledge graph, so agents find callers, impact and tests without grepping the repo. The fork listed here is our
  custom fork that tracks codegraph but adds a centralized server needed for a software factory work at scale.
  (`mcp.example.json` shows the setup).
-  If not using Enterprise API pair with **[Official CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI)**: or our **[Codedaptive CLIProxy fork](https://github.com/codedaptive/CLIProxyAPI)** and our **[Quota forecasting and spend analysis management center fork](https://github.com/codedaptive/CLIProxyAPI-MgmtCenterWithForecasting)**)
- **Haiku 5.5, Sonnet 5.5, Opus 5.5, Fable 5.2**
- **Astra 6, Sol 6.1, Terra 6.1**
> All agent files and skills where optimize using hundreds of hours of real python, typescript, swift, rust, agentic transcripts replayed through the models listed and tuned to the published prompting guides for each. If the expectations of future models change automous behavior will degrade; using with other models will require tuning to achieve automous factory production.

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
