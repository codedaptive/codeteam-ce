---
name: git-worktree
load: demand
description: Load before any git commit, branch or worktree step you do by hand. Commits, branches and worktrees for leads and coordinators - commit cadence, one commit per unit, squash trailers, continuing an earlier lead's branch.
---

# Commits and worktrees

- **The test gates the commit.** Commit when you have just tested green: normally once per unit, plus once after
  review fixes. Never commit to "save progress"; agents edit forward and the branch survives a crash anyway.
- **Coders do not commit.** They edit their file set and report. The lead commits each unit in its own commit.
- **Commit messages:** one line saying what changed and why, then `Request: <request>`.
- **One request, one lead, one worktree** until it is accepted. Rework goes back to the same lead, resumed.
- A new lead that replaces one that cannot be resumed first merges the old branch: `git merge worktree-agent-<id>`.
  Never work in another lead's worktree.
- Coordinators move finished work up with the commands in their role text from codeteam (`accept` and `push-up`, or,
  under branch flow v5, `codeteam-land land`). Never push or merge by hand.
- Never rewrite history that another worktree has: no `reset --hard`, `rebase` or force push on shared branches.
