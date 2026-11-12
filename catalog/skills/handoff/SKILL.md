---
name: handoff
description: What to keep across a compaction or a restart. Preloaded by sessions and request leads.
---

# Handoff

When codeteam asks for a handoff, or before a compaction, write `<ledger>/reports/handoff.md`:
- your role, your lane and walls, who you report to;
- each open request: its work order path, worktree, branch, lead agent id, stage;
- the current test record per module (from `make zone-test-status`);
- open findings and questions, each with its owner.
After a compaction, re-read the handoff and the work order from disk. Never rebuild details from memory.
