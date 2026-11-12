Write the post-compact handoff and save it to a file. Do this now, in this
turn, before anything else.

You are writing for a colleague picking this work up cold. They can read
the handoff file and they can read the code. They cannot read this
conversation, and everything that lives only here is about to be gone.

Give them context, not commands. No "you must", no "always", no "never",
no checklist to obey. They get their own judgment once they are oriented;
your job is to orient them.

Cover, in your own words and your own order:

- What we are building and why
- Where things stand: done, in progress, untouched. Name the in-progress
  thing precisely, by branch, task id, or half-edited file
- Decisions and the thinking behind them, especially the ones that would
  look arbitrary from outside
- What failed and how it failed. The failure mode matters more than the
  fix
- Exact strings that matter: errors, config keys, response shapes, commit
  SHAs, file:line anchors. Quote them verbatim
- What is still open, including what nobody decided
- Where you would pick up if you were the one continuing, and why

Skip anything they would get from just reading the code. Do not summarise
the conversation turn by turn. If the operator overruled you or you
changed your mind, say so and say why: that reasoning is often the most
useful thing in the document.

THE ACTIVE PLAN

If you are holding a plan (an approved multi-step plan, a decomposition
you and the operator agreed, anything the next session would otherwise
have to reconstruct), write it out in full inside the handoff: every step,
which are done, in flight or untouched, the dependency order, and anything
the operator ruled on mid-plan. A handoff that says "see the plan file" is
a dead reference to a reader on another machine or a fresh clone.

IDENTIFY IT SO IT CAN BE FOUND

Open the body with these four lines, before anything else:

    repo:    <repository name>
    agent:   <your session name ($CODETEAM_SESSION)>
    branch:  <the branch this work is on, or none>
    written: <ISO timestamp>

Then the handoff proper.

FILING

Save it to `handoffs/$CODETEAM_SESSION.md` in your working folder
(create the folder if needed), replacing any older handoff of yours. Keep
the previous one as `handoffs/$CODETEAM_SESSION.prev.md` so the chain can
be walked back one step.

If the write fails, print the entire handoff in chat so it can be pasted
somewhere safe. Say plainly that it did not save. A handoff believed saved
and not saved is the worst outcome available.

WHEN YOU ARE DONE

Confirm in one line: saved or not saved, and where. Then say:

    Ready. Run /compact now.

Do not do anything else in this turn.
