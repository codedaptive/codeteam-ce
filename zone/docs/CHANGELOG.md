# CHANGELOG

One line per change to this zone, newest first.

2026-11-16 `tests/integration/land-guard-walls-glob.py` moves to `zone/tests/integration/test_land_guard_walls.py`, gated to the integration group, since its three tests join codeteam-land's `guard_walls` with `lane_walls`, both the zone's (rule 11).
2026-11-16 `lane_walls.Walls.lockfile(rel)` says whether a path is a lock file (`LOCKFILES`) the orchestrator does not own, `refused_by` asks it, and so does the landing tool's wall check, so a zone's work order may land the lock its build regenerates, as the guard already allowed (tests `zone/tests/lane-walls.sh`, `tests/unit/land-wall-lockfiles.py`, `tests/integration/land-guard-walls-glob.py`).
2026-11-14 The zone guard's Stop hook counts a main-thread Write, Edit or MultiEdit of the lane's `ledger/memory/pending-acme.md` after a push as filed (a Bash command naming the file does not count), its block reason says to park the pair there when acme does not answer, and the zone brief names that file while it holds parked pairs (tests `zone/tests/zone-guard-stop-push.sh` and `zone/tests/zone-guard-brief-pending-acme.sh`).
2026-11-11 First public release (codeteam gamma preview, branch flow v5.4).
