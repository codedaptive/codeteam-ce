---
status: active
created: 2026-10-30
updated: 2026-11-04
tags: [rules, always-applies]
---

# Rules every agent follows

**What outranks what.** A hook's refusal; then these rules; then your role file (codeteam's text: paths, commands,
channels); then your agent file (the procedure); then skills. A file never claims to outrank another. The crew and
what each member does: `crew.md` beside this file.

1. **Never lose work.** No `git reset --hard`, `git clean`, `rm -rf`, force push or deleting a file you did not
   create in this request. One exception: a lane may delete a run folder outside its tree that
   its own earlier request made and its records name, once the work it served has landed and no later run still
   reads it. Unsure whether something is yours, or still read: leave it and say so.
2. **Look before you claim or write.** Read the code (CodeGraph first; a skill your file lists under "Skills you load" is loaded with the Skill tool before the step that needs it) before saying how it works; list a folder
   before creating a file in it; read a file before editing it. Memory is not a source.
3. **Stay in your walls.** Edit only what your lane owns and your brief names. A guard's refusal is not a blocker:
   it is another lane's work. One NOTE to the orchestrator naming the files, then carry on with yours.
4. **Never claim what you did not run.** Quote the test record.
5. **Edit structured files (TOML, JSON, YAML) with a parser or exact-line edits,** never regex or sed.
6. **One plain command per shell call.** If a command times out, retry once, then report.
7. **Messages cost a turn.** Send one only when it changes what the receiver does: a REQUEST that needs an answer
   or an action; a RULING; DONE or PUSHED when work lands (codeteam posts PUSHED itself); a NOTE another lane must
   act on; BLOCKED with what is needed. Never acknowledgments, thanks, "noted", restatements, progress, STATUS for
   its own sake, or an answer to a message that asks nothing. One message per event, to the one session that must
   act, one or two sentences; anything longer is a file under your ledger's `reports/`, named in the message. Only
   the orchestrator addresses `all`, and only for a ruling every session must hear. Subagents send no messages:
   they hand back once. A mechanical step whose record is green (a READY, a re-clear at a new tip, a copy of a
   ruling into its register, a loop restart) is done and reported, never asked.
8. **Settle a question from the documents before you ask:** spec, interface, rulings, the settled ledger, house
   rules, your own channel, the code. Ask with the citations and your recommendation.
9. **The harness is not your work.** codeteam, the catalog, role and agent files, `.claude` settings, rules, hooks,
   herdr, other teams: don't change them, propose changes or ask about them. One line in your status if something
   seems wrong; one line to the orchestrator only if it blocks the product.
10. **Never run `codegraph upgrade`,** not even with `--check`, when CodeGraph is installed. One CodeGraph install serves
   every team on the machine; `upgrade` would change it for all of them at once. Upgrading it is the owner's call.
   The other index commands stay off-limits too, as the codegraph skill says: `init`, `index`, `sync`, `uninit`,
   `unlock`, `install`, `uninstall`, `telemetry`.
11. **Three kinds of test.** A unit test checks one small piece of code, such as a function or a
   class, in isolation from everything outside it, and gives the same answer every time it runs.
   - Small scope: it exercises one behaviour of one unit, so a failure points at one place.
   - Isolated: it makes no network calls, uses no real database or live service, and doesn't depend on other tests
     or on the order they run in. Collaborators are replaced with fakes, or are simple enough to use directly.
   - Deterministic: it doesn't depend on timing, sleeps or machine load.
   - Fast: it runs in milliseconds, so the whole set can run on every change.

   Anything that crosses those lines is a different kind of test. An integration test checks that several units or
   a real dependency work together. A validation test measures performance or accuracy. A test proves the code
   produces an outcome; it never measures how fast. A busy machine is never a reason for anything: a test that
   cannot pass on a busy machine is in the wrong group. Every test package has three groups, `unit`,
   `integration` and `validation`; coders write unit tests, Nagatha integration tests, the repo orchestrator
   validation tests. A test in the wrong group is moved when it is seen, as a small patch riding with the work
   that found it: not a failure, and it blocks nothing.
