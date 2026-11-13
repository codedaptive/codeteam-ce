#!/usr/bin/env -S python3 -u
"""The slow-compile survey names as new only what is new to the code: a site in a file changed since the last survey
that was not over the line then, or one over the line in two surveys running, reported once
(2026-11-12: sites in untouched files crossed 100 ms on alternate runs and came back as 'new' each time)."""
import importlib.machinery
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_slow_new", str(ROOT / "bin" / "codeteam-land"))
cl = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", returncode=0)):
    loader.exec_module(cl)

HPKE = ["pkg/WidgetCoreKit/Tests/WidgetCryptoTests.swift", 42,
        "instance method 'hpkeMalformedAndCrossRoleInputsReject()'", 869]
EXPR = ["pkg/A/Sources/A/x.swift", 7, "expression", 150]


def test_a_site_that_flickers_in_an_untouched_file_is_not_new():
    assert cl.slow_new([HPKE], [], set(), changed=set()) == []
    assert cl.slow_new([HPKE], [], set(), changed=None) == []


def test_a_site_in_a_changed_file_that_was_not_over_before_is_new():
    assert cl.slow_new([HPKE], [], set(), changed={HPKE[0]}) == [HPKE]


def test_a_site_already_over_in_a_changed_file_is_not_new_even_when_its_line_moved():
    moved = [HPKE[0], 44, HPKE[2], 900]
    assert cl.slow_new([moved], [HPKE], {cl.slow_site(*HPKE[:3])}, changed={HPKE[0]}) == []


def test_a_site_seen_before_a_run_that_did_not_rebuild_it_is_not_new_when_its_file_changes():
    # A run type-checks only what it rebuilds, so the last survey can miss a site seen earlier.
    seen = {cl.slow_site(*HPKE[:3])}
    assert cl.slow_new([HPKE], [], set(), changed={HPKE[0]}, seen=seen) == []


def test_seen_sites_carry_from_survey_to_survey():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        survey(team, [HPKE], changed=[])                   # seen, file unchanged: not new
        survey(team, [], changed=[])                       # not rebuilt this run
        survey(team, [HPKE], changed=[HPKE[0]])            # its file changed: seen before, so not new
        assert team.sent == [], team.sent


def test_two_surveys_running_report_once():
    assert cl.slow_new([EXPR], [EXPR], set(), changed=set()) == [EXPR]
    assert cl.slow_new([EXPR], [EXPR], {cl.slow_site(*EXPR[:3])}, changed=set()) == []


class FakeTeam:
    def __init__(self, d):
        self.dir = Path(d)
        self.repo = Path(d)
        self.zones = {"WidgetCoreKit": ["pkg/WidgetCoreKit"]}
        self.sent = []

    def c(self, key, default):
        return default

    def notify(self, to, kind, text):
        self.sent.append(text)


def survey(team, lines, changed):
    log = "\n".join(f"/home/x/landing/acme-ee/{p}:{ln}:5: warning: {w} took {ms}ms to type-check"
                    for p, ln, w, ms in lines)
    diff = SimpleNamespace(stdout="\n".join(changed), returncode=0)
    with patch.object(cl, "ssh", return_value=SimpleNamespace(stdout=log)), \
            patch.object(cl, "git", return_value=diff):
        cl.slow_report(team, {"path": "~/landing/acme-ee", "slow_ms": 100}, "c" * 40)


def test_the_first_survey_after_the_old_format_names_nothing_already_listed():
    with tempfile.TemporaryDirectory() as d:
        team = FakeTeam(d)
        (team.dir / "slow-compile.json").write_text(json.dumps([HPKE]))
        (team.dir / "validation-results.jsonl").write_text(json.dumps({"commit": "b" * 40, "result": "pass"}) + "\n")
        survey(team, [HPKE, EXPR], changed=[])
        assert team.sent == [], team.sent
        saved = json.loads((team.dir / "slow-compile.json").read_text())
        assert saved["commit"] == "c" * 40 and len(saved["rows"]) == 2
        survey(team, [HPKE, EXPR], changed=[])            # EXPR over twice running, never reported: new once
        assert len(team.sent) == 1 and "x.swift:7 expression 150ms" in team.sent[0], team.sent
        assert "## New to the code (1)" in (team.dir / "slow-compile.md").read_text()
        survey(team, [HPKE, EXPR], changed=[])
        assert len(team.sent) == 1, team.sent


if __name__ == "__main__":
    test_a_site_that_flickers_in_an_untouched_file_is_not_new()
    test_a_site_in_a_changed_file_that_was_not_over_before_is_new()
    test_a_site_already_over_in_a_changed_file_is_not_new_even_when_its_line_moved()
    test_a_site_seen_before_a_run_that_did_not_rebuild_it_is_not_new_when_its_file_changes()
    test_seen_sites_carry_from_survey_to_survey()
    test_two_surveys_running_report_once()
    test_the_first_survey_after_the_old_format_names_nothing_already_listed()
    print("all passed")
