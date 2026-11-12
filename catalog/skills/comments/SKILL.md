---
name: comments
description: Comment rules - comments travel with the code, say what it does now, and stale ones are findings. Preloaded by coders, change-reviewer and comment-integrity.
---

# Comments

- **Comments travel with the code.** Change the code, change its comment in the same edit.
- **Say what the code does now.** No history: not "previously", "used to", "was replaced by", "old approach",
  removed or deprecated paths, or stale request IDs.
- **Explain the why** for every non-obvious constant, design decision, and "why not the obvious way".
- **No overstatement:** a comment never promises a guarantee the code does not give.
- **No dead citations:** every file, test or symbol a comment names exists.
- A comment-only fix needs no rebuild: `git diff` showing only comment lines changed is the proof.
- **Never edit a document's version, date or changelog section** (the front matter `version:` and `date:`, and its
  `## Changelog` entries). The landing tool's docs pass sets them after the work order lands (branch flow v5.1,
  section 7). Edited by hand in a work order, they conflict with every other landing that touched the same document,
  and the work order cannot land until someone resolves it.
- **Say the level instead.** When the work order changes what a document promises, put one line in
  the commit message that carries the change: `Doc-Level: major` (something removed, or a behaviour users rely on
  changed, even with the same declarations), `Doc-Level: minor` (something added) or `Doc-Level: patch`; for one
  document only, `Doc-Level: <path> major`. The landing tool applies it; without the line it judges from the declared
  API alone, which cannot see a behaviour change. The product's versioning rules decide the level.
