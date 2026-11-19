"""D466: landing labs describe their one-branch workflow; other teams keep theirs.

Integration (D478, Orc-Codeteam-jj #4328): every case renders the real roles/*.md templates through bin/codeteam's
common_values and render_roles, with no fakes, so a template edit and a code edit can break it together. Moved
from tests/runtime. Skipped unless CODETEAM_TEST_GROUP=integration."""

import importlib.machinery
import importlib.util
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("CODETEAM_TEST_GROUP", "unit") != "integration",
                                reason="integration group only (D478); run with CODETEAM_TEST_GROUP=integration")

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def codeteam():
    dont_write_bytecode = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("codeteam_lab_role_text", str(ROOT / "bin" / "codeteam"))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = dont_write_bytecode


def team(*, lab):
    return SimpleNamespace(
        manifest="example.toml", lab=lab, base="main", integration="integration",
        m={"land": {"enabled": True}}, guard="Kong", orc_name=lambda: "Orc",
        ledger=lambda name: Path("ledgers") / name, cmd=lambda name: f"codeteam {name}",
        root=Path("team"), assistants={}, session_links={}, tier_of=lambda name: None,
        scratchpad=lambda name: Path("scratch") / name,
    )


def render_role(codeteam, t, template):
    return codeteam.render((ROOT / "roles" / template).read_text(), {
        **codeteam.land_role_values(t), "base": t.base, "integration": t.integration,
        "land": "codeteam-land example.toml", "orc": "Orc", "guard": "Kong",
        "guard_ledger": "ledgers/Kong", "lane": "alpha", "coord": "Coord-alpha",
        "product": "Example", "name": "Kong", "job": "", "cwd": "work",
        "walls": "files", "guide": "guide", "ledger": "ledger", "spec_authors": "Orc",
        "channel": "channel", "say": "say", "types": "NOTE", "general": "general",
        "lane_channel": "alpha", "rulings": "rulings", "settled": "settled",
        "harness_rule": "",
    })


@pytest.mark.parametrize(("template", "expected"), [
    ("zone-land.md", ("cut from `main`, the lab's one branch", "Those are already on `main`")),
    ("assistants/kong-land.md", ("not already on `main`", "does not expire when `main` moves")),
    ("assistants/nagatha-land.md", ("A lab has no promotion", "no document stamp runs")),
])
def test_lab_role_renders_one_branch_workflow(codeteam, template, expected):
    text = render_role(codeteam, team(lab=True), template)
    for sentence in expected:
        assert sentence in text
    assert "{{" not in text
    for forbidden in ("`landing`", "`integration`", "Stage 7", "move-over"):
        assert forbidden not in text
    # The contract explicitly requires statements that a lab has no promotion.
    assert "promot" not in text.replace("A lab has no promotion", "").lower()


@pytest.mark.parametrize(("template", "expected"), [
    ("zone-land.md", (
        "merges `integration` (proven code only) into the tree as B",
        "Stage 7 promotes to `main`",
    )),
    ("assistants/kong-land.md", (
        "At a team's move-over, review each zone's whole diff between `main` and `landing` once.",
        "does not expire when `landing` or `integration` moves.",
    )),
    ("assistants/nagatha-land.md", (
        "Promotion is Stage 7 and the tool's",
        "your integration tests stop a landing at Stage 2 and hold promotion through Stage 5's recheck",
    )),
])
def test_non_lab_role_keeps_current_workflow(codeteam, template, expected):
    text = render_role(codeteam, team(lab=False), template)
    for sentence in expected:
        assert sentence in text
    assert "{{" not in text


def test_lab_landing_promotion_describes_five_steps(codeteam):
    text = codeteam.landing_promotion(team(lab=True))
    assert ("Every change reaches `main` only through the landing tool, one work order at a time "
            "(spec v5.4, for a lab). Work order trees are cut from `main`; a lab has no promotion.") in text
    assert re.findall(r"(?m)^(\d+)\. ", text) == ["1", "2", "3", "4", "5"]
    assert "Stage 4 merges reviewed work orders onto `main` one at a time." in text
    assert "`codeteam-land example.toml validate-run` validates the newest `main` commit" in text
    assert "Nobody commits on `main` directly" in text
    for forbidden in ("Stage 7", "`integration`", "`landing`", "migrate-v54"):
        assert forbidden not in text



def test_landing_promotion_names_the_branches_nobody_commits_on(codeteam):
    """The orchestrator's own-edits step names every branch the guard protects: a lab's one branch, or v5.4's three
    (Orc-Codeteam-jj #4291: nothing asserted the v5.4 sentence)."""
    lab = codeteam.landing_promotion(team(lab=True))
    std = codeteam.landing_promotion(team(lab=False))
    assert "5. Your own edits and the designer's (docs, rulings, specs) land like any change" in lab
    assert "Nobody commits on `main` directly; the guard refuses it." in lab
    assert "6. Your own edits and the designer's (docs, rulings, specs) land like any change" in std
    assert "Nobody commits on `main`, `integration` or `landing` directly; the guard refuses it." in std

def test_lab_orchestrator_bullets_describe_landing_and_pull(codeteam):
    text = codeteam.LAB_LAND_ORC_BULLETS.format(land="codeteam-land example.toml", base="main")
    assert "merged onto `main` (Stage 4)" in text
    assert "`codeteam-land example.toml wo-pull <wo>`" in text
    assert "the landing tool sends no notice" in text
    assert "Stage 7" not in text


def test_lab_team_gets_lab_orchestrator_bullets(codeteam):
    text = codeteam.land_orc_bullets(team(lab=True))
    assert "merged onto `main` (Stage 4)" in text
    assert "`codeteam-land example.toml wo-pull <wo>`" in text
    assert "the landing tool sends no notice" in text
    assert "Stage 7" not in text
    assert "landing branch" not in text


def test_non_lab_team_gets_standard_orchestrator_bullets(codeteam):
    text = codeteam.land_orc_bullets(team(lab=False))
    assert "merged onto the landing branch (Stage 4)" in text
    assert "When Stage 7 promotes it, the waiting zone is told and pulls it." in text


def test_non_lab_landing_promotion_keeps_seven_steps(codeteam):
    text = codeteam.landing_promotion(team(lab=False))
    assert re.findall(r"(?m)^(\d+)\. ", text) == ["1", "2", "3", "4", "5", "6", "7"]
    assert "7. Move-over" in text
    assert "Stage 7 fast-forwards `main`" in text


def test_lab_lane_folders_describe_landed_work(codeteam):
    text = codeteam.folders_section(team(lab=True), {"lanes": {"alpha": {}}}, "alpha")
    assert "cut from `main` by codeteam" in text
    assert "Move reports for landed work into" in text


def test_non_lab_lane_folders_keep_promoted_work(codeteam):
    text = codeteam.folders_section(team(lab=False), {"lanes": {"alpha": {}}}, "alpha")
    assert "cut from `integration` by codeteam" in text
    assert "Move reports for promoted work into" in text


def test_kong_writes_no_changelog_entry_in_a_lab_and_keeps_the_step_elsewhere(codeteam):
    """D468: nothing places a lab's changelog entry (no promotion, no document stamp)."""
    lab = render_role(codeteam, team(lab=True), "assistants/kong-land.md")
    std = render_role(codeteam, team(lab=False), "assistants/kong-land.md")
    assert "2. A lab has no promotion, so no document stamp places a changelog entry: write none" in lab
    assert "changelog/<wo>.md" not in lab
    assert "2. When done with a work order, write its changelog entry to `ledgers/Kong/changelog/<wo>.md`" in std


def common_team(*, lab):
    """team(lab=) with what common_values reads besides the landing text."""
    t = team(lab=lab)
    vars(t).update(product="Example", title="Example", exchange="exchange", general="general", repo=Path("repo"),
                   int_wt=lambda: Path("int"), ex_wt=lambda: Path("ex"), builder="Nagatha",
                   spec_authors=lambda: ["Orc"], designers=lambda: [], assistant_channel=lambda name: f"ch-{name}",
                   rulings=Path("rulings"), home=Path("home"), target="main", guard_per="land", backup=False)
    return t


# The values render_roles adds per role; none of them is landing text.
ROLE_KEYS = {"lane": "alpha", "coord": "Coord-alpha", "name": "Kong", "job": "", "cwd": "work", "walls": "files",
             "guide": "guide", "ledger": "ledger", "channel": "channel", "lane_channel": "alpha"}


@pytest.mark.parametrize(("lab", "expected"), [
    (True, {"zone-land.md": ("cut from `main`, the lab's one branch", "Those are already on `main`"),
            "assistants/kong-land.md": ("not already on `main`", "does not expire when `main` moves"),
            "assistants/nagatha-land.md": ("A lab has no promotion", "no document stamp runs")}),
    (False, {"zone-land.md": ("merges `integration` (proven code only) into the tree as B", "Stage 7 promotes to `main`"),
             "assistants/kong-land.md": ("does not expire when `landing` or `integration` moves.",),
             "assistants/nagatha-land.md": ("Promotion is Stage 7 and the tool's",)}),
])
def test_common_values_carries_the_landing_branch_text(codeteam, lab, expected):
    """render_roles renders every role from common_values, so the lane, Kong and Nagatha branch text must reach a
    role through it: without `**land_role_values(t)` there the placeholders stay (Orc-Codeteam-jj #4304, their Kong
    at merge 19: nothing covered that line)."""
    values = codeteam.common_values(common_team(lab=lab))
    for template, sentences in expected.items():
        text = codeteam.render((ROOT / "roles" / template).read_text(), {**values, **ROLE_KEYS})
        assert "{{" not in text, template
        for sentence in sentences:
            assert sentence in text, (template, sentence)
