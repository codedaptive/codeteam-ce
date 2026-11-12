---
status: active
created: 2026-10-24
tags: [rules, always-applies, smoke]
---

# smoke-project (codeteam v2 test bed)

- This repo exists to test codeteam v2. Keep changes small and exactly what the message asks.
- Zone lanes edit only their zone (`zones/<name>`) and their zone's spec in `docs/reference`.
  A guard refuses the rest; a change another zone needs goes to Orc-Smoke as a NOTE.
- Tests: `make zone-test` for your zone (or `make test-one DIR=<your zone>`). Run the tests that
  cover your change before you start and once at the end. A test over 5 seconds needs a reason.
- Settle a question from the documents first (`docs/reference/*_SPEC.md`, the code); send
  Orc-Smoke your answer with file:line citations and your recommendation.
- Report with the say command your role file names: DONE with what changed and the test result,
  or a NOTE when you are blocked. Never claim a test passed without running it.
