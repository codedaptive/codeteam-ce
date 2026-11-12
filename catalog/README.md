# Agent catalog v4

Small role files, small skills (one per tool or craft), and a product layer, generated into one team's agents.

| Layer | Where | Loaded |
|---|---|---|
| Role | `roles/<role>.md`: kind (session, subagent, leaf, both), tools, base skills, body (duty, short procedure, hard rules) | always, for that role |
| Global rules | `rules/global.md` | always, every agent |
| Product rules | `products/<p>/rules/` (product.md = the repo's AGENTS.md, team-layout.md) | always, every agent |
| Shared skills | `skills/`: codeteam-shared, zone-tests, git-worktree, codegraph, comments, coding-rules, review-verdicts, gate-procedures, handoff, rust-cargo, swift, python; on demand: swiftui, localization | preloaded per role |
| Product skills and choices | `products/<p>/skills/`, `products/<p>/product.toml` (roles, models, extra skills and tools per role, on-demand skills) | per role |
| Models | `rosters/<name>.csv` (default `claude`): the model and effort per role | at build |
| Effort ladders | `effort/ladders.csv`: what the effort-mode hook tells the designer and orchestrator at each effort level | at install |

`products/example/` is the product layer for the example team in `teams/example.toml`; copy it for a new product.

Build and install:
```
python3 -I generate.py <product>                     # build/<product>/{agents,skills,rules}
python3 -I generate.py <product> --install $CODETEAM_WORKSPACE/team-<product>
python3 -I generate.py all --install                 # every product, each into $CODETEAM_WORKSPACE/team-<product>
```
Install links `agents/` to the build, copies skills and rules, and records what it placed in `team/claude/catalog.json`.
A first install (no record yet) archives the team's `team/claude/{agents,skills,rules}` into `team/claude-archive/`.
A reinstall replaces or removes only what the record lists, creates what is new in the build, and never touches
anything else. A build name already on disk but not on the record is a conflict: kept, reported, and the run exits 1
(unless it already equals the build; then it joins the record). Install also adds codeteam's hooks to the team's
`settings.json` (run with `$CODETEAM_PYTHON`, default `python3`, from `$CODETEAM_HOME/share/claude-hooks/`).
Re-run the plain build after any change; installed agents follow the build through their links (skills and rules
are copies: re-run with `--install` when those change).

Rules the generator applies:
- Sessions (kind session or both) get their skills written into the agent file: Claude Code doesn't preload
  `skills:` for a session started with `--agent` (tested 2026-10-30). Subagents get `skills:`.
- Every agent that can start agents gets `experimental.cacheTtl: 1h`; leaves start without CLAUDE.md.
- An `Agent(...)` list keeps only roles the product has.
- Every role gets `ToolSearch`; a role that uses an MCP server's tools names them in `product.toml` `[tools]`.

Sessions also get codeteam's role text (`roles/*.md` at the top of this repository, appended at launch); it carries
channels and team commands, so role files here carry craft, not mechanics.

Tests: `python3 -m pytest -q tests` (install contract tests; one builds the example product).
