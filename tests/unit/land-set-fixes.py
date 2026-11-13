#!/usr/bin/env -S python3 -u
"""Stage 3: a work order whose reviewer has seen all its commits and filed findings lands when every open finding is
claimed by the landing set (--fixes) and answered by a commit made after it: its own, or a --with partner's that the
finding's reviewer reviews (once: a finding's #1 fixed in the port after the finding,
#2's test carried in data's work order because tests/ is data's wall). Git and findings are faked; nothing touches a
repo."""
import importlib.machinery
import importlib.util
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_set_fixes", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)

PORT = {"wo": "port", "tip": "P" * 40, "fixes": ["f#1", "f#2"]}
DATA = {"wo": "data", "tip": "D" * 40, "fixes": ["f#1", "f#2"]}
PREVIOUS = {"reviewers": {"Kong": "findings"}, "seen": {"Kong": ["P" * 40]}, "tip": "P" * 40}
T1, T2 = "2026-11-12T13:18:50-06:00", "2026-11-12T13:43:34-06:00"


def at(stamp):
    return int(datetime.fromisoformat(stamp).timestamp())


# Each tip's own commits and their committer times: the port's fix of #1 came after #1, its other commit before it;
# data's test commit came after #2.
COMMITS = {"P" * 40: {"p-old": at("2026-11-12T13:00:00-06:00"), "p-fix": at("2026-11-12T13:30:03-06:00")},
           "D" * 40: {"d-test": at("2026-11-12T14:01:51-06:00")}}


def finding(fid, time, by="Kong", wo="port"):
    return {"id": fid, "state": "open", "by": by, "also": [], "wos": [wo], "time": time}


def ranges(findings, rec=PORT, members=None, reviewers=("Kong",), commits=COMMITS):
    """reviewer_ranges for the port with nothing unseen; `reviewers` is who stage3_reviewers names for any files."""
    def review_range(team, tip, seen):
        return [] if seen else list(commits.get(tip, {}))

    def times(team, shas):
        return {s: t for tip in commits.values() for s, t in tip.items() if s in shas}
    with patch.object(cl, "review_range", side_effect=review_range), \
            patch.object(cl, "commit_times", side_effect=times), \
            patch.object(cl, "review_files", return_value=["x"]), \
            patch.object(cl, "stage3_reviewers", return_value=list(reviewers)), \
            patch.object(cl, "all_findings", return_value=list(findings)):
        return cl.reviewer_ranges(SimpleNamespace(), rec, PREVIOUS, ["Kong"], members)


def refused(*a, **kw):
    try:
        ranges(*a, **kw)
    except SystemExit as exc:
        assert exc.code == cl.GATE
        return True
    return False


def test_an_own_fix_committed_after_the_finding_lands_with_nothing_new():
    assert ranges([finding("f#1", T1)]) == {}


def test_a_finding_after_every_own_commit_is_refused_alone():
    assert refused([finding("f#1", T1), finding("f#2", T2)])


def test_a_partner_fix_after_the_finding_answers_it_in_the_set():
    assert ranges([finding("f#1", T1), finding("f#2", T2)], members=[PORT, DATA]) == {}


def test_a_finding_nobody_claims_is_refused_even_with_later_commits():
    port, data = dict(PORT, fixes=["f#2"]), dict(DATA, fixes=["f#2"])
    assert refused([finding("f#1", T1), finding("f#2", T2)], rec=port, members=[port, data])


def test_a_claim_whose_commits_all_came_before_the_finding_is_refused():
    assert refused([finding("f#1", "2026-11-12T15:00:00-06:00")], members=[PORT, DATA])


def test_a_partner_fix_the_findings_reviewer_does_not_review_is_refused():
    # Perkins reviews only security paths: data's test files bring Kong alone, so Perkins never sees the fix.
    assert refused([finding("f#2", T2, by="Perkins")], members=[PORT, DATA], reviewers=("Kong",))


def test_a_partner_fix_in_files_the_findings_reviewer_reviews_answers_it():
    assert ranges([finding("f#2", T2, by="Perkins")], members=[PORT, DATA], reviewers=("Kong", "Perkins")) == {}


def test_a_finding_with_no_time_is_never_answered():
    assert refused([{"id": "f#1", "state": "open", "by": "Kong", "also": [], "wos": ["port"]}], members=[PORT, DATA])


def test_the_landing_set_reaches_each_members_review_record():
    seen = []
    recs = [dict(PORT, zone="Model-NCM"), dict(DATA, zone="data")]

    def record(team, rec, members=None):
        seen.append((rec["wo"], [m["wo"] for m in members or []]))
        return {"stage": 3, "wo": rec["wo"], "zone": "z", "feature": rec["wo"], "tip": rec["tip"], "reviewers": {},
                "commits": {}, "seen": {}, "requested": "t", "state": "land"}
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        team = SimpleNamespace(dir=Path(d), save_wo=lambda rec: None)
        for sub in ("reviews", "queue"):
            (team.dir / sub).mkdir()
        with patch.object(cl, "stage3_record", side_effect=record):
            cl.queue_stage3(team, recs, {"wo": "port"}, "now")
    assert seen == [("port", ["port", "data"]), ("data", ["port", "data"])], seen


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
