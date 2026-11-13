#!/usr/bin/env -S python3 -u
"""v5.4's isolated review, landing and promotion contracts; all git and notices are faked."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_v54", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)


def team_at(root):
    manifest = root / "sample.toml"
    manifest.write_text(f'repo = "{root / "repo"}"\nworktree_root = "{root / "team"}"\n'
                        'guard = "Kong"\n[[assistants]]\nname = "Perkins"\n'
                        '[[lanes]]\nname = "A"\npath = "A"\n[[lanes]]\nname = "B"\npath = "B"\n'
                        '[[lanes]]\nname = "C"\npath = "C"\n[land]\norchestrator = "Skippy"\n')
    team = cl.Team(manifest)
    team.notify = Mock()
    return team


def work(team, wo="w", zone="A", tip="T"):
    tree = team.root / wo
    tree.mkdir(parents=True)
    rec = {"wo": wo, "zone": zone, "tree": str(tree), "branch": f"wo/{zone}/{wo}",
           "base": "B", "tip": tip, "files": [f"{zone}/value"], "queued": "2026-11-10T12:00:00+00:00"}
    team.save_wo(rec)
    return rec


def review(team, wo="w", tip="T"):
    row = {"stage": 3, "wo": wo, "zone": "A", "tip": tip, "reviewers": {"Kong": "pending"},
           "commits": {"Kong": [tip]}, "seen": {"Kong": []},
           "requested": "2026-11-10T12:00:00+00:00", "state": "pending"}
    (team.dir / "reviews" / f"{wo}.json").write_text(json.dumps(row))
    entry = {"wos": [wo], "wo": wo, "tip": tip, "base": "B", "zones": ["A"],
             "queued": "now", "state": "waiting", "review": "pending"}
    p = team.dir / "queue" / f"{wo}.json"
    p.write_text(json.dumps(entry))
    return p


def put_findings(team, rows):
    (team.dir / "findings").mkdir(exist_ok=True)
    (team.dir / "findings" / "w.json").write_text(json.dumps(rows))


def verdict(team):
    with patch.dict(os.environ, CODETEAM_SESSION="Kong"), patch.object(cl, "out", return_value="landing-moved"), \
            patch.object(cl, "git", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
        try:
            cl.cmd_reviewed(team, SimpleNamespace(feature="w"))
        except SystemExit:
            pass


class Refs:
    """Literal ancestry: B -> M -> F -> C; F2 and later are outside C."""
    def __init__(self):
        self.refs = {"HEAD": "B", "main": "B", "integration": "B", "landing": "C"}
        self.calls = []

    def out(self, repo, *args):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return "main"
        if args[0] == "rev-parse":
            return self.refs[args[-1].removeprefix("refs/heads/")]
        if args[0] == "diff":
            return "A/value"
        return ""

    def git(self, repo, *args, **kw):
        self.calls.append((args, kw))
        rc = 0
        if args[:2] == ("merge-base", "--is-ancestor"):
            a, b = (self.refs.get(x.removeprefix("refs/heads/"), x) for x in args[-2:])
            rc = 0 if ancestor(a, b) else 1
        elif args[0] == "merge":
            self.refs["HEAD"] = self.refs["main"] = args[-1]
        elif args[0] == "update-ref":
            self.refs[args[1].removeprefix("refs/heads/")] = args[2]
        return SimpleNamespace(returncode=rc, stdout="", stderr="")


def ancestor(a, b):
    return a == b or (a, b) in {("B", "M"), ("B", "F"), ("B", "C"), ("M", "F"), ("M", "C"), ("F", "C")}


@contextlib.contextmanager
def promoting(team, refs):
    (team.dir / "validation-results.jsonl").write_text(json.dumps({"commit": "C", "result": "pass", "tests": []}) + "\n")
    with patch.object(cl, "git", side_effect=refs.git), patch.object(cl, "out", side_effect=refs.out), \
            patch.object(cl, "stamp_docs", return_value=None), patch.object(cl, "after_promote"), \
            patch.object(cl, "reach", return_value=["A", "B"]):
        yield


def test_review_findings_send_back_and_nothing_lands():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = work(team); p = review(team)
        put_findings(team, [{"id": "w#1", "feature": "w", "wos": ["w"], "state": "open", "by": "Kong", "also": [],
                             "time": "2026-11-10T12:01:00+00:00", "where": "A/value:1", "what": "wrong result"}])
        with patch.object(cl, "move_landing", create=True) as move:
            verdict(team)
        assert not p.exists(), "review findings must remove the whole queue entry"
        assert "queued" not in team.wo("w")
        assert Path(rec["tree"]).is_dir()
        assert not (team.dir / "wo" / "w.landed.json").exists()
        move.assert_not_called()
        assert json.loads((team.dir / "reviews" / "w.json").read_text())["state"] == "findings"
        assert len(team.notify.call_args_list) == 1
        to, kind, text = team.notify.call_args.args
        assert (to, kind) == ("Coord-A", "REQUEST")
        assert all(s in text for s in ("w#1", "A/value:1", "wrong result", "same tree"))
        assert json.loads((team.dir / "landed.log").read_text())["result"] == "review findings"


def review_set(team, w_state="pending"):
    """A --with set of w (zone A, under Kong's review) and g (zone B, whose own commits Kong passed earlier)."""
    work(team, "w", "A", "T")
    work(team, "g", "B", "G")
    asked = "2026-11-10T12:00:00+00:00"
    rows = {"w": {"stage": 3, "wo": "w", "zone": "A", "feature": "w", "tip": "T", "seen": {"Kong": []},
                  "reviewers": {"Kong": w_state}, "commits": {"Kong": ["T"]}, "requested": asked,
                  "state": "pending" if w_state == "pending" else "land",
                  "with": [{"wo": "g", "zone": "B", "tip": "G"}]},
            "g": {"stage": 3, "wo": "g", "zone": "B", "feature": "g", "tip": "G", "seen": {"Kong": ["G0"]},
                  "reviewers": {}, "commits": {}, "requested": asked, "state": "land",
                  "with": [{"wo": "w", "zone": "A", "tip": "T"}]}}
    for wo, row in rows.items():
        (team.dir / "reviews" / f"{wo}.json").write_text(json.dumps(row))
    entry = {"wos": ["w", "g"], "wo": "w", "tip": "T", "tips": [["w", "T"], ["g", "G"]], "base": "B",
             "zones": ["A", "B"], "queued": "now", "state": "waiting",
             "review": "pending" if w_state == "pending" else "land"}
    p = team.dir / "queue" / "w.json"
    p.write_text(json.dumps(entry))
    return p


def file_finding(team, feature, wo, zone, who="Kong"):
    a = SimpleNamespace(feature=feature, wo=[wo], zone=zone, where=f"{zone}/value:1", severity=2,
                        kind="spec", what="refusal missing", belongs="", same_as=None)
    with patch.dict(os.environ, CODETEAM_SESSION=who), contextlib.redirect_stdout(io.StringIO()):
        cl.cmd_finding(team, a)


def test_finding_on_a_passed_set_member_is_held_while_the_set_is_under_review():
    # Kong once read one member's code with its set and found it wrong, but finding refused it because
    # only another member was under review, and his reviewed on that member landed the whole set.
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); review_set(team)
        file_finding(team, "g", "g", "B")
        assert [f["id"] for f in cl.load_findings(team, "g")] == ["g#1"]
        team.notify.assert_not_called()


def test_partner_finding_sends_the_whole_set_back():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); p = review_set(team)
        file_finding(team, "g", "g", "B")
        with patch.object(cl, "move_landing", create=True) as move, contextlib.redirect_stdout(io.StringIO()):
            verdict(team)
        assert not p.exists(), "a finding on any member must take the whole set out of the queue"
        assert "queued" not in team.wo("w") and "queued" not in team.wo("g")
        move.assert_not_called()
        w = json.loads((team.dir / "reviews" / "w.json").read_text())
        g = json.loads((team.dir / "reviews" / "g.json").read_text())
        assert w["reviewers"]["Kong"] == "pass", "w's own commits had no finding"
        assert (g["state"], g["reviewers"]["Kong"]) == ("findings", "findings")
        assert "G" in g["seen"]["Kong"]
        sent = [c.args for c in team.notify.call_args_list]
        assert [(to, kind) for to, kind, _ in sent] == [("Coord-B", "REQUEST")], sent
        assert all(s in sent[0][2] for s in ("g#1", "B/value:1", "refusal missing", "same tree", "w"))


def test_partner_finding_is_refused_once_the_reviewer_owes_no_verdict_in_the_set():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); review_set(team, w_state="pass")
        try:
            file_finding(team, "g", "g", "B")
        except SystemExit:
            pass
        else:
            raise AssertionError("with every verdict in, a late finding waits for landing (a fix work order)")
        assert cl.load_findings(team, "g") == []


def test_partner_finding_needs_the_filer_to_owe_a_verdict_in_the_set():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); review_set(team)
        try:
            file_finding(team, "g", "g", "B", who="Perkins")
        except SystemExit:
            pass
        else:
            raise AssertionError("Perkins owes no verdict in this set, so no verdict of his would send it back")
        assert cl.load_findings(team, "g") == []


def test_verdict_survives_landing_moving():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); work(team); p = review(team)
        verdict(team)
        row = json.loads((team.dir / "reviews" / "w.json").read_text())
        assert row["state"] == "land", "the verdict covers T, not the current landing branch"
        assert row["seen"]["Kong"] == ["T"]
        assert json.loads(p.read_text())["review"] == "land"
        with patch.object(cl, "integration_holders", return_value=[]), patch.object(cl, "out", return_value="NEW"), \
                patch.object(cl, "merge_landing_member", return_value=("MERGED", [])), \
                patch.object(cl, "move_landing") as move, patch.object(cl, "landing_recheck", return_value=False), \
                patch.object(cl, "record_landing_members", return_value=[{"recheck": False}]), \
                patch.object(cl, "landing_bookkeeping"):
            assert cl.land_entry(team, p) == 0
        move.assert_called_once_with(team, "MERGED", "NEW")


def test_stage7_refuses_unfixed_failure_then_promotes_once_fixed_at_or_before_C():
    finding = {"id": "w#1", "test": "A", "Ms": ["M"], "state": "open"}
    assert cl.unfixed_failures("C", [finding], {}, ancestor) == ["w#1"]
    assert cl.unfixed_failures("C", [dict(finding, state="closed", closed_at="F")], {}, ancestor) == []
    assert cl.unfixed_failures("C", [dict(finding, state="closed", closed_at="F2")], {}, ancestor) == ["w#1"]
    # A dropped test failure holds nothing.
    assert cl.unfixed_failures("C", [dict(finding, state="dropped", reason="duplicate of w#0")], {}, ancestor) == []
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); refs = Refs(); put_findings(team, [finding])
        with promoting(team, refs):
            try:
                cl.stage7(team, "C")
            except cl.PromotionRefused as exc:
                assert "w#1" in str(exc)
            else:
                raise AssertionError("unfixed failure at M must refuse C")
            assert refs.refs["main"] == "B"
            put_findings(team, [dict(finding, state="closed", closed_at="F")])
            assert cl.stage7(team, "C") == "C"
            assert refs.refs["main"] == "C"


def test_open_review_finding_does_not_change_stage7():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); refs = Refs()
        put_findings(team, [{"id": "w#1", "state": "open", "by": "Kong", "wos": ["w"]}])
        (team.dir / "landed.log").write_text(json.dumps({"hash": "M", "wos": ["w"]}) + "\n")
        refused = None
        with promoting(team, refs):
            try:
                cl.stage7(team, "C")
            except cl.PromotionRefused as exc:
                refused = str(exc)
        assert refused is None, f"review findings never hold Stage 7: {refused}"
        assert refs.refs["main"] == "C"


def test_promote_integration_equals_base_and_only_reached_lanes_told():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); refs = Refs()
        for name, zone in (("a", "A"), ("b", "B"), ("c", "C")):
            work(team, name, zone)
        with promoting(team, refs):
            cl.stage7(team, "C")
        assert refs.refs["integration"] == refs.refs["main"] == "C"
        writes = [(args, kw) for args, kw in refs.calls if args[:2] == ("update-ref", "refs/heads/integration")]
        assert writes[0][0] == ("update-ref", "refs/heads/integration", "C", "B")
        assert writes[0][1]["env"]["CODETEAM_LAND_TOOL"] == "1"
        lanes = [call.args[0] for call in team.notify.call_args_list if call.args[0].startswith("Coord-")]
        assert lanes == ["Coord-A", "Coord-B"]
        assert all("merge integration at your next stopping point" in call.args[2]
                   for call in team.notify.call_args_list if call.args[0].startswith("Coord-"))


def test_stage7_completes_when_document_stamp_fails():
    for error in (SystemExit("stamp exited"), ValueError("stamp invalid")):
        with tempfile.TemporaryDirectory() as tmp:
            team = team_at(Path(tmp)); refs = Refs()
            with promoting(team, refs), patch.object(cl, "stamp_docs", side_effect=error), \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                assert cl.stage7(team, "C") == "C"
            assert refs.refs["main"] == refs.refs["integration"] == "C"
            assert not (team.dir / "promote.json").exists()
            notes = [call.args for call in team.notify.call_args_list if call.args[1] == "NOTE"]
            assert len(notes) == 1 and notes[0][:2] == ("Skippy", "NOTE")
            assert "C" in notes[0][2] and str(error) in notes[0][2]
            assert "C" in stderr.getvalue() and str(error) in stderr.getvalue()


def test_a1_overlap_by_ancestry_not_time():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); work(team); p = review(team)
        e = json.loads(p.read_text()); e["review"] = "land"; p.write_text(json.dumps(e))
        (team.dir / "landed.log").write_text(json.dumps({"time": "earlier", "hash": "X", "wos": ["old"], "range": "B..X"}) + "\n")
        def git(repo, *args, **kw):
            return SimpleNamespace(returncode=0 if args[-1] == "L" else 1, stdout="", stderr="")
        def out(repo, *args):
            if args[0] == "rev-parse":
                return "L" if args[-1].removeprefix("refs/heads/") == "landing" else "B"
            return "A/value"
        with patch.object(cl, "integration_holders", return_value=[]), patch.object(cl, "git", side_effect=git), \
                patch.object(cl, "out", side_effect=out), patch.object(cl, "merge_landing_member", return_value=("N", [])), \
                patch.object(cl, "move_landing", create=True), \
                patch.object(cl, "record_landing_members", return_value=[{"recheck": True}]), patch.object(cl, "landing_bookkeeping"):
            assert cl.land_entry(team, p) == 0
        rows = cl.read_recheck(team)
        assert len(rows) == 1, "X landed before the Stage 2 merge, but is absent from B"
        assert rows[0]["overlapping"] == ["old"]


def test_a2_conflict_names_landed_work_orders_and_keeps_tree():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); rec = work(team); p = review(team)
        e = json.loads(p.read_text()); e["review"] = "land"; p.write_text(json.dumps(e))
        (team.dir / "landed.log").write_text(json.dumps({"hash": "X", "wos": ["older"], "range": "B..X"}) + "\n")
        with patch.object(cl, "integration_holders", return_value=[]), patch.object(cl, "out", side_effect=lambda repo, *a: "L" if a[0] == "rev-parse" else "A/value"), \
                patch.object(cl, "git", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")), \
                patch.object(cl, "intervening_landings", return_value=[("older", ["A/value"])]), \
                patch.object(cl, "merge_landing_member", return_value=(None, ["A/value"])):
            assert cl.land_entry(team, p) == 2
        text = team.notify.call_args.args[2]
        assert all(s in text for s in ("A/value", "older", "promoted", "merge integration", "not merge landing"))
        assert Path(rec["tree"]).is_dir()
        assert (team.dir / "wo" / "w.bounce.txt").read_text() == "A/value\n"


def test_a3_at_or_before_C_by_ancestry_never_clock():
    findings = [{"id": "future", "test": "A", "Ms": ["later"], "state": "open", "time": "invalid"},
                {"id": "late-fix", "test": "B", "commits": ["M"], "state": "closed", "closed_at": "F2", "closed": "invalid"},
                {"id": "fixed", "test": "C", "Ms": ["M"], "state": "closed", "fixed_by": "fix"}]
    with patch.object(cl, "now", side_effect=AssertionError("clock read")):
        assert cl.unfixed_failures("C", findings, {"fix": "F"}, ancestor) == ["late-fix"]


def test_a5_perkins_only_with_security_paths():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp))
        assert cl.stage3_reviewers(team, ["A/auth.py"]) == ["Kong"]
        team.cfg["security_paths"] = ["A/auth*", "secrets/**"]
        assert cl.stage3_reviewers(team, ["A/auth.py"]) == ["Kong", "Perkins"]
        assert cl.stage3_reviewers(team, ["B/value"]) == ["Kong"]
        team.m["assistants"] = []
        assert cl.stage3_reviewers(team, ["A/auth.py"]) == ["Kong"]


def test_a6_docs_stamp_queued_on_landing_without_waiting():
    with tempfile.TemporaryDirectory() as tmp:
        team = team_at(Path(tmp)); team.cfg.update(docs={"enabled": True}, seed_index=False)
        (team.dir / "docs-pending.jsonl").write_text(json.dumps({"wo": "w", "hash": "M", "time": "now", "docs": {"A.md": "minor"}, "entry": "change"}) + "\n")
        refs = {"integration": "1111111111111111111111111111111111111111",
                "landing": "2222222222222222222222222222222222222222",
                "B": "0000000000000000000000000000000000000001"}
        heads = {}; cut_bases = []; messages = []
        def git(repo, *args, **kw):
            if args[:2] == ("worktree", "add"):
                tree = Path(args[-2]); tree.mkdir(parents=True)
                heads[tree] = refs[args[-1].removeprefix("refs/heads/")]
                cut_bases.append(heads[tree])
                (tree / "A.md").write_text("---\nversion: 1.0.0\n---\n# A\n")
            if args[0] == "commit":
                messages.append(args[args.index("-m") + 1])
                heads[Path(repo)] = "3333333333333333333333333333333333333333"
            return SimpleNamespace(returncode=0, stdout="---\nversion: 1.0.0\n---\n# A\n" if args[0] == "show" else "", stderr="")
        def out(repo, *args):
            if args[0] == "status": return "dirty"
            if args == ("rev-parse", "HEAD"): return heads[Path(repo)]
            return refs[args[-1].removeprefix("refs/heads/")]
        with patch.object(cl, "git", side_effect=git), patch.object(cl, "out", side_effect=out), \
                patch.object(cl, "spawn") as spawn, patch.object(cl, "cmd_land") as land, patch.object(cl, "land_entry") as immediate:
            assert cl.stamp_docs(team, "C", "B") == "docs-stamp-C"
        assert cut_bases == ["1111111111111111111111111111111111111111"]
        assert team.wo("docs-stamp-C")["base"] == "1111111111111111111111111111111111111111"
        assert team.wo("docs-stamp-C")["made_by"] == "codeteam-land"
        assert messages[0].endswith("\n\nMade-By: codeteam-land")
        assert "land docs-stamp-C" in spawn.call_args.args[0]
        land.assert_not_called(); immediate.assert_not_called()


def test_a7_review_skip_by_record_and_trailer_not_name():
    for wo, made, trailer, expected in (("docs-x", False, False, "pending"), ("revert-x", False, False, "pending"),
                                         ("stamp", True, True, "land"), ("record", True, False, "pending"),
                                         ("trailer", False, True, "pending")):
        with tempfile.TemporaryDirectory() as tmp:
            team = team_at(Path(tmp)); rec = work(team, wo)
            if made:
                rec["made_by"] = "codeteam-land"; team.save_wo(rec)
            def out(repo, *args):
                if args[0] == "rev-list": return "T"
                if args[0] == "show": return "change\n\nMade-By: codeteam-land" if trailer else "change"
                return "B"
            with patch.object(cl, "checked_members", return_value=[(rec, True)]), patch.object(cl, "merge_checked_base"), \
                    patch.object(cl, "changed_files", return_value=["A/value"]), patch.object(cl, "check_combined_members", return_value=(["A"], ["A"])), \
                    patch.object(cl, "queue_notices"), patch.object(cl, "out", side_effect=out):
                cl.check_and_queue(team, SimpleNamespace(wo=wo), [wo])
            entry = json.loads(next((team.dir / "queue").glob("*.json")).read_text())
            assert entry.get("review") == expected, f"{wo}: names alone must never skip review"


failed = 0
for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
    try:
        test()
        print(f"  PASS {test.__name__}")
    except (Exception, SystemExit) as exc:
        failed += 1
        print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
print(f"{failed} failed" if failed else "all passed")
sys.exit(1 if failed else 0)
