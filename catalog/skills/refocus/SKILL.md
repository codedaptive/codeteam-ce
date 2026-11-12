---
name: refocus
description: Shrink the working context to what matters before a compaction. Writes a four-part report (learned true, learned false, completed, pending) as the whole message; in a codeteam session /prepare-for-compact follows it at once and codeteam compacts, keeping both. Use before every compaction (codeteam prompts at 70% of the compaction window), or when the operator says refocus.
---

# Refocus

A long session holds its beginning and its end well. The middle is what
compaction summarizes away. This skill puts the state of the work at the
end, so the compacted session reasons from a short, clean report.

The purpose is focus. A smaller active context supports sounder judgment.

## Write the report

Make the report your whole message. One fact per bullet. Anchor each fact
to its evidence where one exists: a commit SHA, a file:line, a command
result. Include only what the next decision depends on.

### Learned — true

Facts established this session that the work depends on. Where a fact
replaced an earlier belief, state the fact as it stands now.

### Learned — false

Beliefs held earlier this session that proved wrong. For each, state the
wrong belief and the fact that replaced it. This list keeps a later turn
from re-deriving the same mistake.

### Completed

Work finished and verified, with where it landed.

### Pending

Work still owed. For each, the next step and anything it waits on.

### Then the handoff (codeteam sessions)

In a codeteam session nobody reviews the report before the compaction: there is no operator at the prompt. Write
the report as your whole message, then run `/prepare-for-compact` straight after it (read and follow
`.claude/commands/prepare-for-compact.md`). When the handoff ends with "Ready. Run /compact now.", codeteam runs
`/compact` with the instruction to keep the Refocus report and the handoff verbatim, and then tells you to resume.

In a session the owner drives directly, close the report by asking them to check it; when they correct something, write the
whole report again with the correction in place; when they confirm it, give them this line to run:

```
/compact Keep the Refocus report above verbatim as the working state. Summarize everything before it in a few lines.
```

## After the compact

Start from the report. Treat the two Learned lists as settled, Completed as
done, and Pending as the work queue.

Before acting on a fact that names a file, a commit, or a running process,
check it again. Those change while the session runs.
