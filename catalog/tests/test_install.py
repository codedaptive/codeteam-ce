"""Contract tests for install() in generate.py .

Tests install into a scratch team home under tmp_path, using synthetic builds except for the subprocess test, which
runs the real example build into the gitignored build/ folder. One test observes where each entry is built and
renamed by wrapping os.symlink, shutil.copy, shutil.copytree, os.replace and os.rename; the wrappers still perform
the real operations.
"""
import datetime
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GENERATE_PY = Path(__file__).resolve().parents[1] / "generate.py"
PYTHON = sys.executable
PRODUCT = "example"
TODAY = datetime.date.today().isoformat()
FIXED_NS = 1_600_000_000_000_000_000
FOLDERS = ("agents", "skills", "rules")

_spec = importlib.util.spec_from_file_location("generate", GENERATE_PY)
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)

# Build trees: folder -> {path relative to the folder: text}. A skill is a folder, so its files nest under its name.
V1 = {
    "agents": {"alpha.md": "alpha v1\n", "beta.md": "beta v1\n", "gone.md": "gone v1\n"},
    "skills": {
        "coding-rules/SKILL.md": "coding rules v1\n",
        "zone-tests/SKILL.md": "zone tests v1\n",
        "zone-tests/reference/notes.md": "notes\n",
    },
    "rules": {"global.md": "global v1\n", "crew.md": "crew v1\n"},
}
# gone.md dropped, new.md added, coding-rules changed.
V2 = {
    "agents": {"alpha.md": "alpha v1\n", "beta.md": "beta v1\n", "new.md": "new v2\n"},
    "skills": {
        "coding-rules/SKILL.md": "coding rules v2\n",
        "zone-tests/SKILL.md": "zone tests v1\n",
        "zone-tests/reference/notes.md": "notes\n",
    },
    "rules": {"global.md": "global v1\n", "crew.md": "crew v1\n"},
}
# V2 plus a clash and a fresh entry in each folder, for the conflict and adoption tests.
V2X = {
    "agents": {**V2["agents"], "clash.md": "clash build\n", "fresh.md": "fresh build\n"},
    "skills": {
        **V2["skills"],
        "clash-skill/SKILL.md": "clash skill build\n",
        "fresh-skill/SKILL.md": "fresh skill build\n",
    },
    "rules": {**V2["rules"], "clash.md": "clash build\n", "fresh.md": "fresh build\n"},
}

UNLISTED_CASES = [("agents", "personal.md"), ("skills", "personal-skill"), ("rules", "personal.md")]
CONFLICT_CASES = [
    ("agents", "clash.md", "fresh.md"),
    ("skills", "clash-skill", "fresh-skill"),
    ("rules", "clash.md", "fresh.md"),
]
ADOPT_CASES = [("agents", "fresh.md"), ("skills", "fresh-skill"), ("rules", "fresh.md")]


def make_build(root, tree):
    for folder in FOLDERS:
        for rel, text in tree[folder].items():
            path = root / folder / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "hooks" / "effort-ladders.json").write_text('{"alpha": {"sonnet": {"low": {"mode": "m", "text": "t"}}}}\n')
    return root


def expected_files(tree):
    return {
        "agents": sorted(tree["agents"]),
        "skills": sorted({rel.split("/")[0] for rel in tree["skills"]}),
        "rules": sorted(tree["rules"]),
    }


def entry_rel(folder, name):
    return f"{name}/SKILL.md" if folder == "skills" else name


def team_dir(tmp_path):
    return tmp_path / "scratch-team"


def claude_of(team):
    return team / "team" / "claude"


def archive_root(team):
    return team / "team" / "claude-archive"


def archive_today(team):
    return archive_root(team) / f"before-v4-{TODAY}"


def record_of(claude):
    return json.loads((claude / "catalog.json").read_text())


def run_install(out, team):
    return generate.install(PRODUCT, str(out), str(team))


def seed_old_home(claude):
    old = {"agents/old.md": "old agent\n", "skills/old-skill/SKILL.md": "old skill\n", "rules/old.md": "old rule\n"}
    for rel, text in old.items():
        path = claude / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def plant(claude, folder, name, text):
    path = claude / folder / entry_rel(folder, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def adopt(out, claude, folder, name):
    if folder == "agents":
        os.symlink(out / "agents" / name, claude / "agents" / name)
    elif folder == "skills":
        shutil.copytree(out / "skills" / name, claude / "skills" / name)
    else:
        shutil.copy(out / "rules" / name, claude / "rules" / name)


def interrupt_record(monkeypatch):
    def boom(c, record):
        raise RuntimeError("interrupted before the record")

    monkeypatch.setattr(generate, "write_record", boom, raising=False)


def install_interrupted(out, team):
    try:
        run_install(out, team)
    except RuntimeError as err:
        return err
    return None


def run_cli(team):
    return subprocess.run(
        [PYTHON, "-I", str(GENERATE_PY), PRODUCT, "--install", str(team)],
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def v1_home(tmp_path):
    team = team_dir(tmp_path)
    seed_old_home(claude_of(team))
    run_install(make_build(tmp_path / "build-v1", V1), team)
    return team


def test_install_returns_claude_home_archive_and_report(tmp_path):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    seed_old_home(claude)
    result = run_install(make_build(tmp_path / "build", V1), team)
    assert len(result) == 3
    c, arch, report = result
    assert Path(c) == claude
    assert Path(arch) == archive_today(team)
    assert set(report) == {"agents", "skills", "rules"}
    for folder in report:
        assert set(report[folder]) == {"replaced", "removed", "created", "left_alone", "conflicts"}


def test_first_install_moves_old_folders_into_the_archive(tmp_path):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    seed_old_home(claude)
    run_install(make_build(tmp_path / "build", V1), team)
    archive = archive_today(team)
    assert (archive / "agents" / "old.md").read_text() == "old agent\n"
    assert (archive / "skills" / "old-skill" / "SKILL.md").read_text() == "old skill\n"
    assert (archive / "rules" / "old.md").read_text() == "old rule\n"
    assert not os.path.lexists(claude / "agents" / "old.md")


def test_first_install_links_agents_and_copies_skills_and_rules(tmp_path):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    seed_old_home(claude)
    out = make_build(tmp_path / "build", V1)
    run_install(out, team)
    names = expected_files(V1)
    assert sorted(os.listdir(claude / "agents")) == names["agents"]
    for name in names["agents"]:
        assert os.readlink(claude / "agents" / name) == str(out / "agents" / name)
    assert sorted(os.listdir(claude / "skills")) == names["skills"]
    assert not (claude / "skills" / "coding-rules" / "SKILL.md").is_symlink()
    assert (claude / "skills" / "zone-tests" / "reference" / "notes.md").read_text() == "notes\n"
    assert sorted(os.listdir(claude / "rules")) == names["rules"]
    assert (claude / "rules" / "crew.md").read_text() == "crew v1\n"


def test_first_install_writes_the_record(tmp_path):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    seed_old_home(claude)
    run_install(make_build(tmp_path / "build", V1), team)
    assert (claude / "catalog.json").exists()
    record = record_of(claude)
    assert record["product"] == PRODUCT
    assert {"catalog_commit", "installed_at"} <= record.keys()
    assert record["files"] == expected_files(V1)


def test_first_install_into_an_empty_home_archives_nothing(tmp_path):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    result = run_install(make_build(tmp_path / "build", V1), team)
    assert result[1] is None
    assert sorted(os.listdir(claude / "agents")) == expected_files(V1)["agents"]


def test_install_prints_one_line_per_folder(tmp_path, capsys):
    team = team_dir(tmp_path)
    seed_old_home(claude_of(team))
    run_install(make_build(tmp_path / "build", V1), team)
    out = capsys.readouterr().out
    line = re.compile(
        r"^  (agents|skills|rules): replaced \d+, removed \d+, created \d+, left alone \d+, conflicts \d+$", re.M
    )
    assert sorted(line.findall(out)) == ["agents", "rules", "skills"]


def test_hooks_effort_ladders_are_copied_from_the_build(tmp_path):
    team = team_dir(tmp_path)
    out = make_build(tmp_path / "build", V1)
    run_install(out, team)
    assert (claude_of(team) / "hooks" / "effort-ladders.json").read_bytes() == (
        out / "hooks" / "effort-ladders.json"
    ).read_bytes()


@pytest.mark.parametrize("folder, name", UNLISTED_CASES)
def test_reinstall_leaves_an_unlisted_entry_alone(tmp_path, v1_home, folder, name):
    claude = claude_of(v1_home)
    planted = plant(claude, folder, name, "mine\n")
    os.utime(planted, ns=(FIXED_NS, FIXED_NS))
    run_install(make_build(tmp_path / "build-v2", V2), v1_home)
    assert planted.is_file() and not planted.is_symlink()
    assert planted.read_text() == "mine\n"
    assert planted.stat().st_mtime_ns == FIXED_NS
    assert name not in record_of(claude)["files"][folder]


def test_reinstall_removes_a_role_the_build_dropped(tmp_path, v1_home):
    run_install(make_build(tmp_path / "build-v2", V2), v1_home)
    assert not os.path.lexists(claude_of(v1_home) / "agents" / "gone.md")


def test_reinstall_creates_a_role_new_in_the_build(tmp_path, v1_home):
    out = make_build(tmp_path / "build-v2", V2)
    run_install(out, v1_home)
    assert os.readlink(claude_of(v1_home) / "agents" / "new.md") == str(out / "agents" / "new.md")


def test_reinstall_replaces_a_changed_skill_with_a_copy(tmp_path, v1_home):
    run_install(make_build(tmp_path / "build-v2", V2), v1_home)
    skill = claude_of(v1_home) / "skills" / "coding-rules" / "SKILL.md"
    assert skill.read_text() == "coding rules v2\n"
    assert not skill.is_symlink()


def test_reinstall_does_not_archive_again(tmp_path, v1_home):
    result = run_install(make_build(tmp_path / "build-v2", V2), v1_home)
    assert result[1] is None
    assert sorted(os.listdir(archive_root(v1_home))) == [f"before-v4-{TODAY}"]
    assert (archive_today(v1_home) / "agents" / "old.md").read_text() == "old agent\n"


def test_reinstall_rewrites_the_record_for_the_new_build(tmp_path, v1_home):
    claude = claude_of(v1_home)
    plant(claude, "agents", "personal.md", "mine\n")
    run_install(make_build(tmp_path / "build-v2", V2), v1_home)
    assert (claude / "catalog.json").exists()
    assert record_of(claude)["files"] == expected_files(V2)


def test_reinstall_reports_counts_per_folder(tmp_path, v1_home):
    plant(claude_of(v1_home), "agents", "personal.md", "mine\n")
    result = run_install(make_build(tmp_path / "build-v2", V2), v1_home)
    assert len(result) == 3
    assert result[2] == {
        "agents": {"replaced": 2, "removed": 1, "created": 1, "left_alone": 1, "conflicts": []},
        "skills": {"replaced": 2, "removed": 0, "created": 0, "left_alone": 0, "conflicts": []},
        "rules": {"replaced": 2, "removed": 0, "created": 0, "left_alone": 0, "conflicts": []},
    }


@pytest.mark.parametrize("folder, clash, fresh", CONFLICT_CASES)
def test_conflict_keeps_the_unlisted_file_and_installs_the_rest(tmp_path, v1_home, folder, clash, fresh):
    claude = claude_of(v1_home)
    plant(claude, folder, clash, "mine\n")
    result = run_install(make_build(tmp_path / "build-v2x", V2X), v1_home)
    kept = claude / folder / entry_rel(folder, clash)
    assert not kept.is_symlink() and kept.read_text() == "mine\n"
    assert len(result) == 3
    report = result[2]
    assert report[folder]["conflicts"] == [clash]
    assert all(report[other]["conflicts"] == [] for other in FOLDERS if other != folder)
    record = record_of(claude)
    assert clash not in record["files"][folder]
    assert fresh in record["files"][folder]
    assert (claude / folder / entry_rel(folder, fresh)).read_text() == V2X[folder][entry_rel(folder, fresh)]


def test_conflict_makes_the_install_command_exit_1(tmp_path):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    first = run_cli(team)
    assert first.returncode == 0, first.stdout + first.stderr
    assert (claude / "catalog.json").exists()
    record = record_of(claude)
    victim = record["files"]["agents"][0]
    link = claude / "agents" / victim
    assert link.is_symlink()
    link.unlink()
    link.write_text("mine\n")
    record["files"]["agents"].remove(victim)
    (claude / "catalog.json").write_text(json.dumps(record, indent=2) + "\n")
    second = run_cli(team)
    assert second.returncode == 1, second.stdout + second.stderr
    assert not link.is_symlink()
    assert link.read_text() == "mine\n"


def test_interrupted_reinstall_keeps_the_old_record_and_the_next_run_converges(tmp_path, v1_home, monkeypatch):
    claude = claude_of(v1_home)
    assert (claude / "catalog.json").exists()
    old_record = (claude / "catalog.json").read_bytes()
    out = make_build(tmp_path / "build-v2", V2)
    interrupt_record(monkeypatch)
    assert install_interrupted(out, v1_home) is not None
    assert (claude / "catalog.json").read_bytes() == old_record
    monkeypatch.undo()
    result = run_install(out, v1_home)
    assert len(result) == 3
    assert all(result[2][folder]["conflicts"] == [] for folder in FOLDERS)
    assert record_of(claude)["files"] == expected_files(V2)
    for folder in FOLDERS:
        assert sorted(os.listdir(claude / folder)) == expected_files(V2)[folder]
    assert os.readlink(claude / "agents" / "new.md") == str(out / "agents" / "new.md")
    assert (claude / "skills" / "coding-rules" / "SKILL.md").read_text() == "coding rules v2\n"
    assert sorted(os.listdir(archive_root(v1_home))) == [f"before-v4-{TODAY}"]


def test_interrupted_first_install_is_archived_again_by_the_next_run(tmp_path, monkeypatch):
    team = team_dir(tmp_path)
    claude = claude_of(team)
    seed_old_home(claude)
    out = make_build(tmp_path / "build-v1", V1)
    interrupt_record(monkeypatch)
    assert install_interrupted(out, team) is not None
    assert not (claude / "catalog.json").exists()
    assert (archive_today(team) / "agents" / "old.md").read_text() == "old agent\n"
    monkeypatch.undo()
    result = run_install(out, team)
    assert len(result) == 3
    assert all(result[2][folder]["conflicts"] == [] for folder in FOLDERS)
    assert record_of(claude)["files"] == expected_files(V1)
    for folder in FOLDERS:
        assert sorted(os.listdir(claude / folder)) == expected_files(V1)[folder]
    archives = sorted(p.name for p in archive_root(team).iterdir())
    assert len(archives) == 2
    assert archives[0] == f"before-v4-{TODAY}"
    assert archives[1].startswith(f"before-v4-{TODAY}-")
    assert (archive_today(team) / "agents" / "old.md").read_text() == "old agent\n"


@pytest.mark.parametrize("folder, fresh", ADOPT_CASES)
def test_reinstall_adopts_an_unlisted_entry_equal_to_the_build(tmp_path, v1_home, folder, fresh):
    claude = claude_of(v1_home)
    out = make_build(tmp_path / "build-v2x", V2X)
    adopt(out, claude, folder, fresh)
    result = run_install(out, v1_home)
    assert (claude / "catalog.json").exists()
    assert fresh in record_of(claude)["files"][folder]
    assert len(result) == 3
    assert result[2][folder]["conflicts"] == []
    assert (claude / folder / entry_rel(folder, fresh)).read_text() == V2X[folder][entry_rel(folder, fresh)]


def install_or_error(out, team):
    # Return filesystem failures so tests can report them in the install assertion.
    try:
        return run_install(out, team), None
    except OSError as err:
        return None, err


def recording(log, real):
    def call(src, dst, *args, **kwargs):
        log.append((str(src), str(dst)))
        return real(src, dst, *args, **kwargs)

    return call


def plant_dir(path):
    path.mkdir(parents=True)
    (path / "inside.md").write_text("inside\n")


@pytest.mark.parametrize("folder, name", [("agents", "alpha.md"), ("rules", "crew.md")])
def test_reinstall_replaces_a_real_directory_at_a_recorded_name(tmp_path, v1_home, folder, name):
    claude = claude_of(v1_home)
    entry = claude / folder / name
    entry.unlink()
    plant_dir(entry)
    out = make_build(tmp_path / "build-v2", V2)
    result, err = install_or_error(out, v1_home)
    assert err is None, f"install raised {err!r}"
    if folder == "agents":
        assert entry.is_symlink()
        assert os.readlink(entry) == str(out / "agents" / name)
    else:
        assert entry.is_file() and not entry.is_symlink()
        assert entry.read_text() == V2["rules"][name]
    assert all(result[2][f]["conflicts"] == [] for f in FOLDERS)
    assert name in record_of(claude)["files"][folder]


def test_install_builds_each_entry_under_its_temp_name_in_the_same_folder(tmp_path, v1_home, monkeypatch):
    claude = claude_of(v1_home)
    (claude / "agents" / ".alpha.md.installing").write_text("leftover\n")
    plant_dir(claude / "rules" / ".crew.md.installing")
    plant_dir(claude / "skills" / ".coding-rules.installing")
    builds, renames = [], []
    for module, name, log in [
        (generate.os, "symlink", builds),
        (generate.shutil, "copy", builds),
        (generate.shutil, "copytree", builds),
        (generate.os, "replace", renames),
        (generate.os, "rename", renames),
    ]:
        monkeypatch.setattr(module, name, recording(log, getattr(module, name)))
    out = make_build(tmp_path / "build-v2", V2)
    result, err = install_or_error(out, v1_home)
    assert err is None, f"install raised {err!r}"
    c = str(claude)
    sources = {str(out / d) for d in FOLDERS}
    built = {(src, dst) for src, dst in builds if os.path.dirname(src) in sources}
    assert built == {
        (f"{out}/{d}/{f}", f"{c}/{d}/.{f}.installing") for d in FOLDERS for f in expected_files(V2)[d]
    }
    homes = {str(claude / d) for d in FOLDERS}
    placed = {(src, dst) for src, dst in renames if os.path.dirname(dst) in homes}
    assert placed == {
        (f"{c}/{d}/.{f}.installing", f"{c}/{d}/{f}") for d in FOLDERS for f in expected_files(V2)[d]
    }
    assert not os.path.lexists(claude / "agents" / ".alpha.md.installing")
    assert not os.path.lexists(claude / "rules" / ".crew.md.installing")
    assert not os.path.lexists(claude / "skills" / ".coding-rules.installing")
    for d in FOLDERS:
        assert [n for n in os.listdir(claude / d) if n.endswith(".installing")] == []
    assert all(result[2][d]["conflicts"] == [] for d in FOLDERS)
