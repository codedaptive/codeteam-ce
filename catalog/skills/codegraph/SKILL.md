---
name: codegraph
load: demand
description: Load before your first CodeGraph call (mcp__codegraph__* or the codegraph CLI). The code index, 1.6.2-sm.12. Finding code, a symbol's source and callers, the radius of a diff and how to judge it, added code nothing uses, name-only call edges, the tests a change touches. Written as steps: follow them in order and do not skip the decision at the end of each.
---

# CodeGraph

CodeGraph answers questions about the code from an index of your worktree. Same tree, same answer. Use it for the
mechanical part (who calls this, what does this change reach); keep your own reading for the judgement.

## 1. Rules for every call

1. **Use the MCP tools** (`mcp__codegraph__codegraph_<name>`). Use the CLI only for `affected` and
   `implementations`, which have no MCP tool.
2. **Pass `projectPath`** on every call: your worktree's absolute path (`pwd`). An answer that says exactly
   `missing argument: root path to the code you wish to query` means you left it out. Add it and call again.
3. **Before a gate, add `fresh: true`.** Every MCP tool takes it. The answer ends with a `Checkpoint:` line. If it
   says `fresh=no` or files pending, call again once. Still not fresh: for the radius, use the fallback in §3
   (step 1) and say so; never report a stale index's radius as if it were fresh.
4. **If it says the index is building,** wait a moment and call again. Do not switch to Grep for the session. For
   a gate that cannot wait (the radius), the §3 fallback applies after one retry.
5. **Never run** `init`, `index`, `sync`, `uninit`, `unlock`, `install`, `uninstall`, `upgrade` or `telemetry`.
6. **What CodeGraph returns is already read.** Open a file yourself only for a span the answer did not show.
7. **Use `rg` for text**: docs, config, YAML, string literals, SQL, comments. Those are not call edges.
8. **A shell `rg` or `grep` for a code symbol in code is stopped** by codeteam's codegraph-first hook, which
   answers with the CodeGraph command for the same question (`codegraph grep`, `callers`, `node`). Ask CodeGraph
   that question. Searches of docs, config, logs and prose are not stopped.

## 2. Which tool

| You want | Call |
|---|---|
| How a flow works | `codegraph_explore {query: "SymA SymB", projectPath}`: names, not a sentence |
| One symbol: source, callers, callees | `codegraph_node {symbol, file?, projectPath}` |
| A file's API and what depends on it | `codegraph_node {file, symbolsOnly: true, projectPath}` |
| Lines of a file | `codegraph_node {file, offset, limit, projectPath}` |
| Find a symbol by name | `codegraph_search {query, projectPath}` |
| Every place a pattern occurs, by symbol | `codegraph_grep {pattern, projectPath}` |
| Who calls it | `codegraph_callers {symbol, file?, projectPath}` |
| What changing one symbol would reach | `codegraph_impact {symbol, depth: 2, projectPath}` |
| What a diff reaches (the radius) | `codegraph_blast {base, strict: true, fresh: true, projectPath}` |
| Added symbols nothing uses | `codegraph_orphans {base, fresh: true, projectPath}` |
| Call edges bound by name only | `codegraph_suspects {projectPath}` |
| What implements a trait or protocol | CLI `codegraph implementations Sym -p <wt>` |
| Tests that cover changed files | CLI `codegraph affected <files…> -p <wt>` |

When a name exists in both ports (Rust and Swift), add `file` to say which one.

## 3. The radius check

The lead runs it before planning. The change-reviewer runs it on the diff. It has four steps; do all four.

**The rule that matters most: "reached" is a list of places to check. It is never a finding by itself.**

### Step 1. Get the list

Call `codegraph_blast {base: "<base ref>", strict: true, fresh: true, format: "json", projectPath}`.

- `base` is the ref the request branched from (the brief names it; else the lane tip).
- `strict: true` drops dependents reached only through name-matched edges. You check those in step 4.
- The json lists every changed symbol and every dependent with its file:line, relation and depth. Dependents in
  test files are counted, not listed.
- In a session started with focus, dependents outside your zone come under `outsideFocus`. If there is no
  `outsideFocus` field, sort them yourself against the walls in your brief.

**Fallback, only if the index is unusable** after one retry (it still says `fresh=no` or files pending, the server
does not connect, the worktree has no index, or its `Checkpoint:` HEAD is not `git rev-parse HEAD`): take the
changed symbols from `git diff <base>`, and for each, `rg -nw <name>` across the repository; read each hit that
calls or uses it. That is your list; go on to step 2. Say so in one line: `NOTE codegraph: <worktree> index
unusable (<what it said>); radius checked with rg`. An unusable index is never a finding and never a reason to send
work back.

### Step 2. Drop the changes that cannot reach anyone

For each changed symbol, look at its diff (`git diff <base> -- <file>`). Drop it if every changed line in it is a
comment (`//`, `///`, `/* */`, `#`, `--`, docstrings), blank, or whitespace. A comment cannot break a caller. The
tool seeds the whole symbol for one comment line, so without this step you will report false findings.

A changed test or test helper stays in. Its dependents are other tests (blast counts them); write the count. The
full set's receipts are what prove those tests still pass, so they are not findings here.

### Step 3. For each remaining change, ask: did the contract change?

The contract is what callers rely on. Compare before and after:

| Part of the contract | Changed if |
|---|---|
| Signature | a parameter added, removed, reordered or retyped; return type changed; a symbol renamed or removed |
| Return value | the same inputs now give a different result, or a value that meant one thing now means another |
| Errors | it now fails, throws or panics where it did not, or stops failing where callers expected it to |
| Side effects | it now writes, deletes, locks, sends or waits differently |
| Defaults | a default value or constant callers read has a new value |

- **Contract unchanged:** its dependents need nothing. Write "contract unchanged" and move on. Do not open them.
- **Contract changed:** go through its dependents one by one. For each, `codegraph_node {symbol, projectPath}` on
  the dependent and read how it uses the changed symbol. It needs a change only if you can say what now goes wrong
  there, at which line.

### Step 4. Check the edges the tool was unsure of

Call `codegraph_suspects {projectPath}` (skip it if step 1 used the `rg` fallback: rg has no edges to doubt). For any suspect edge that touches a changed symbol, check it by hand with
`codegraph_grep {pattern: "<name>", projectPath}`. A suspect edge is a lead to check, not a finding. A caller with
zero callers is a suspicion too: confirm with `codegraph_grep` before saying anything.

### What each outcome means

| You found | Lead | Change-reviewer |
|---|---|---|
| Comment-only change, or contract unchanged | nothing | nothing |
| Dependent reached, uses the symbol in a way that still works | nothing | nothing; do not list it as a finding |
| Dependent inside the walls that now breaks (you can name file:line and what goes wrong) | must update it | FAIL, `Reason: code-wrong`, with the file:line |
| Dependent outside the walls that now breaks | report it in the hand-back for the lane that owns it | NOTE naming the owning lane; not a FAIL on this request |
| The index was unusable (step 1 fallback) | find dependents with `rg`; say so in the plan | the NOTE from step 1; not a Reason, not a FAIL |
| One named dependent whose use you read and still cannot decide | say so in the plan | `Reason: needs-ruling`, naming that dependent's file:line and the question; "the tool was unavailable" is never one |

### Write it like this (the names below are an illustration of the format)

| Changed symbol | Contract changed? | Dependent | Breaks? | Evidence |
|---|---|---|---|---|
| `heal_wal` (wal.rs:40) | no: comment only | 4 dependents | no | step 2 |
| `open_store` (store.rs:12) | yes: new `timeout` parameter | `cli::run` (run.rs:88) | yes: still passes two arguments | codegraph_node run.rs:88 |
| `open_store` | yes | `report::load` (report/load.rs:30), outside walls | yes | NOTE for report lane |

## 4. Worked examples (from real reviews)

1. **Comment edit.** The only production change was one comment line at `orphans.ts:487`. Blast listed the
   symbol's dependents. Step 2: every changed line is a comment, so the list is empty. Wrong outcome seen: FAIL
   "reached and not updated", with the reviewer itself saying no line needed to change.
2. **Caller already correct.** A change put a ranking rule into `search_nodes_limited`. Blast listed
   `context_search_nodes`, which depends on it. Step 3: `codegraph_node` shows that caller already wires
   `deprioritized_paths()`, so it gets the rule with no edit. Wrong outcome seen: FAIL "needs-ruling".
3. **Outside the walls.** A diff reached a function in `src/tools`, which the order made read-only. Even where it
   breaks, the request cannot fix it: NOTE for the tools lane. Wrong outcome seen: FAIL the request.
4. **A real finding.** A doc comment said a default `CollectedDefinition` shows as "nothing found". Its group is
   empty and the printer indexes `group[0]`, so it panics. Contract (the documented behaviour) is false; FAIL with
   `Reason: comment-false` and both file:lines. This is the kind of finding the check exists for.

5. **Index unusable.** A diff changed test files and `#[cfg(test)]` modules; CodeGraph answered `fresh=no` after a
   retry. Step 1's fallback: the changed symbols from `git diff`, `rg -nw` for each; their users are other tests,
   which the full set's receipts cover. Outcome: the NOTE, and the review goes on. Wrong outcome seen (many
   times): FAIL "needs-ruling: radius check could not be completed".

## 5. Other gates

**Orphans (the lead, before review).** `codegraph_orphans {base, fresh: true, projectPath}`. For each name,
`rg -nw <name>` for dynamic and string uses. Code that is documented but unwired is a finding to report. Never
delete it or wire it on your own.

**Tests that cover the change (preflight).** CLI `codegraph affected <changed files> -p <wt>`. List each test file
as its `make zone-test-one` command. Blast counts test-file dependents but does not list them; use `affected` for
those.

**Deletion.** Follow `codegraph_callees` out from the code being removed. For each callee, `codegraph_callers`: if
anything else still calls it, it stays.
