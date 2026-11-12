Recover from a compaction. Read your handoff and re-orient before doing
any work.

The SessionStart hook normally injects this automatically after a
compact. Run this command when it did not fire, when you are resuming in
a fresh session rather than a compacted one, or when the injected text
was thin and you want the full picture.

STEP 1 — find the RIGHT handoff

Read `handoffs/$CODETEAM_SESSION.md` in your working folder. More than one
session may share a checkout, so check the four header lines before you
trust it:

- WHICH REPO it names. Discard anything not this one
- WHICH AGENT wrote it. Another session's handoff is not yours
- HOW RECENT it is, and whether its branch still exists

If it checks out, say which file you took and continue.

IF IT DOES NOT CHECK OUT, OR SEVERAL CANDIDATES DO, STOP AND ASK. List
them: agent, timestamp, branch, and the first line of each. Let the
operator pick. Picking the wrong handoff means confidently continuing
somebody else's task.

STEP 2 — walk back only if you need to

`handoffs/$CODETEAM_SESSION.prev.md` is the handoff before this one. Read
it only if the current one leaves you short.

STEP 3 — check the ground truth

The handoff describes the world as it was when it was written. Before
acting on it, confirm what is actually true now:

    git -C <repo> log --oneline -5
    git -C <repo> status --porcelain

A handoff that says a branch was pushed and a repo that says otherwise
means the push failed after the note was written. Trust the repo.

STEP 4 — say where you are

In a few lines: what this session is picking up, what the handoff says is
in progress, anything the repo contradicts, and what you intend to do
first. Then wait.

Do not start work in this turn. Orientation is the whole job here.

IF THERE IS NO HANDOFF

Say so plainly rather than guessing. Read .claude/active-mission.md and
the recent git log, report what you can establish, and name what you
cannot. An honest cold start beats a confident wrong reconstruction.
