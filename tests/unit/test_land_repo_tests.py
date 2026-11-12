import importlib.machinery
import importlib.util
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, Mock, call, patch

import pytest


ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_repo_tests", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader("cl_repo_tests", loader)
cl = importlib.util.module_from_spec(spec)
with patch("subprocess.run", return_value=SimpleNamespace(stdout="")):
    loader.exec_module(cl)


def make_team(config=None):
    team = Mock()
    team.cfg = config or {}
    team.c.side_effect = lambda key, default: team.cfg.get(key, default)
    team.zones = {"A": ["a"], "B": ["b"]}
    return team


def test_a_missing_folder_returns_no_steps(tmp_path):
    assert cl.repo_test_steps(tmp_path, "missing", "unit", "land", "/zt") == []


def test_a_nothing_runnable_returns_no_steps(tmp_path):
    folder = tmp_path / "suite"
    folder.mkdir()
    (folder / "conftest.py").touch()
    (folder / "__init__.py").touch()
    (folder / "notes.txt").touch()
    (folder / "sub").mkdir()
    (folder / "sub" / "test_nested.py").touch()
    assert cl.repo_test_steps(tmp_path, "suite", "unit", "land", "/zt") == []


def test_a_scripts_only_sorted_with_group_and_class(tmp_path):
    folder = tmp_path / "suite"
    folder.mkdir()
    for name in ("z.sh", "a.py", "conftest.py", "__init__.py"):
        (folder / name).touch()
    assert cl.repo_test_steps(tmp_path, "suite", "unit", "full", "/zt") == [
        ("unit tests (suite)", "/zt job submit --class full --wait 0 --key 'repo suite test-group=unit' -- sh -c 'rc=0; python3 suite/a.py || rc=1; sh suite/z.sh || rc=1; exit $rc'")
    ]


def test_a_pytest_files_only_run_pytest_once(tmp_path):
    folder = tmp_path / "suite"
    folder.mkdir()
    for name in ("test_one.py", "other_test.py", "conftest.py", "__init__.py"):
        (folder / name).touch()
    assert cl.repo_test_steps(tmp_path, "suite", "unit", "land", "/zt") == [
        ("unit tests (suite)", "/zt job submit --class land --wait 0 --key 'repo suite test-group=unit' -- sh -c 'rc=0; python3 -m pytest -q suite || rc=1; exit $rc'")
    ]


def test_a_mixed_worked_example(tmp_path):
    folder = tmp_path / "suite"
    folder.mkdir()
    for name in ("test_one.py", "run.sh", "a.py", "conftest.py"):
        (folder / name).touch()
    (folder / "sub").mkdir()
    (folder / "sub" / "x.py").touch()
    assert cl.repo_test_steps(tmp_path, "suite", "unit", "land", "/zt") == [
        ("unit tests (suite)", "/zt job submit --class land --wait 0 --key 'repo suite test-group=unit' -- sh -c 'rc=0; python3 -m pytest -q suite || rc=1; python3 suite/a.py || rc=1; sh suite/run.sh || rc=1; exit $rc'")
    ]


def test_a_paths_are_shell_quoted(tmp_path):
    folder = tmp_path / "my suite"
    folder.mkdir()
    (folder / "test_one.py").touch()
    (folder / "run me.sh").touch()
    assert cl.repo_test_steps(tmp_path, "my suite", "unit", "full", "/zone tool") == [
        ("unit tests (my suite)", """'/zone tool' job submit --class full --wait 0 --key 'repo my suite test-group=unit' -- sh -c 'rc=0; python3 -m pytest -q '"'"'my suite'"'"' || rc=1; sh '"'"'my suite/run me.sh'"'"' || rc=1; exit $rc'""")
    ]


def test_b_integration_name_and_key(tmp_path):
    folder = tmp_path / "suite"
    folder.mkdir()
    (folder / "run.sh").touch()
    assert cl.repo_integration_steps(tmp_path, "suite", "land", "/zt") == [
        ("integration tests (suite)", "/zt job submit --class land --wait 0 --key 'repo suite test-group=integration' -- sh -c 'rc=0; sh suite/run.sh || rc=1; exit $rc'")
    ]


@pytest.fixture
def stage2():
    team = make_team({"unit_tests": "custom/unit"})
    rec = {"tree": "tree", "files": ["a/file.py"]}
    with ExitStack() as stack:
        stack.enter_context(patch.object(cl, "duplicate_rulings", return_value=[]))
        stack.enter_context(patch.object(cl, "reach", return_value=["A", "B"]))
        stack.enter_context(patch.object(cl, "compile_steps", return_value=[("compile", "check")]))
        stack.enter_context(patch.object(cl, "zone_tests", side_effect=[[('zone A', 'run A')], [('zone B', 'run B')]]))
        repo_unit = stack.enter_context(patch.object(cl, "repo_test_steps", return_value=[("repo unit", "run unit")], create=True))
        repo_integration = stack.enter_context(patch.object(cl, "repo_integration_steps", return_value=[("repo integration", "run integration")]))
        stack.enter_context(patch.object(cl, "team_env", side_effect=lambda t, group: {"group": group}))
        run = stack.enter_context(patch.object(cl, "run_steps", return_value=(True, [])))
        yield team, rec, repo_unit, repo_integration, run


def test_c_d_stage2_uses_configured_unit_folder_and_batches_in_order(stage2):
    team, rec, repo_unit, repo_integration, run = stage2
    assert cl.check_integration(team, rec, False) == ["A", "B"]
    repo_unit.assert_called_once_with("tree", "custom/unit", "unit", "land", str(ROOT / "bin" / "zone-tool"))
    repo_integration.assert_called_once_with("tree", "tests/integration", "land", str(ROOT / "bin" / "zone-tool"))
    assert run.call_args_list == [
        call("tree", [("compile", "check")], {"group": "integration"}, concurrent=False, on_result=ANY),
        call("tree", [("repo unit", "run unit")], {"group": "unit"}, concurrent=True, on_result=ANY),
        call("tree", [("zone A", "run A"), ("zone B", "run B"), ("repo integration", "run integration")], {"group": "integration"}, concurrent=True, on_result=ANY),
    ]


def test_c_stage2_defaults_to_tests_unit(stage2):
    team, rec, repo_unit, _, _ = stage2
    team.cfg.clear()
    cl.check_integration(team, rec, False)
    repo_unit.assert_called_once_with("tree", "tests/unit", "unit", "land", str(ROOT / "bin" / "zone-tool"))


def test_d_unit_failure_exits_gate_before_integration(stage2):
    team, rec, _, repo_integration, run = stage2
    run.side_effect = [(True, []), (False, ["FAIL unit"]), (True, [])]
    with pytest.raises(SystemExit) as exc:
        cl.check_integration(team, rec, False)
    assert exc.value.code == 3
    assert run.call_args_list == [
        call("tree", [("compile", "check")], {"group": "integration"}, concurrent=False, on_result=ANY),
        call("tree", [("repo unit", "run unit")], {"group": "unit"}, concurrent=True, on_result=ANY),
    ]
    repo_integration.assert_not_called()


def test_d_empty_unit_steps_skip_unit_batch(stage2):
    team, rec, repo_unit, _, run = stage2
    repo_unit.return_value = []
    assert cl.check_integration(team, rec, False) == ["A", "B"]
    repo_unit.assert_called_once_with("tree", "custom/unit", "unit", "land", str(ROOT / "bin" / "zone-tool"))
    assert run.call_args_list == [
        call("tree", [("compile", "check")], {"group": "integration"}, concurrent=False, on_result=ANY),
        call("tree", [("zone A", "run A"), ("zone B", "run B"), ("repo integration", "run integration")], {"group": "integration"}, concurrent=True, on_result=ANY),
    ]


def test_d_docs_only_runs_no_batches(stage2):
    team, rec, repo_unit, repo_integration, run = stage2
    assert cl.check_integration(team, rec, True) == []
    repo_unit.assert_not_called()
    repo_integration.assert_not_called()
    run.assert_not_called()


def test_e_validate_suite_batches_zone_and_repo_validation():
    team = make_team({"validation_tests": "custom/validation"})
    tree = Path("/fake-tree")
    with patch.object(cl.Path, "cwd", return_value=tree), \
            patch.object(cl, "compile_steps") as compile_steps, \
            patch.object(cl, "zone_tests", side_effect=[[('zone A', 'run A')], [('zone B', 'run B')]]) as zones, \
            patch.object(cl, "repo_test_steps", return_value=[("repo validation", "run validation")]) as repo, \
            patch.object(cl, "team_env", side_effect=lambda t, group: {"group": group}), \
            patch.object(cl, "run_steps", return_value=(True, [])) as run:
        with pytest.raises(SystemExit) as exc:
            cl.cmd_validate_suite(team, None)
    assert exc.value.code == 0
    compile_steps.assert_not_called()
    assert zones.call_args_list == [call(team, tree, "A", "full", group="validation"),
                                    call(team, tree, "B", "full", group="validation")]
    repo.assert_called_once_with(tree, "custom/validation", "validation", "full", str(ROOT / "bin" / "zone-tool"))
    run.assert_called_once()
    assert run.call_args.args == (tree, [("zone A", "run A"), ("zone B", "run B"),
                                         ("repo validation", "run validation")], {"group": "validation"})
    assert callable(run.call_args.kwargs.get("on_result"))     # each step's line is printed as it finishes (F1)


def test_f_recheck_never_requests_repo_unit_group():
    team = make_team()
    tree = Path("/fake-tree")
    with patch.object(cl, "compile_steps", return_value=[("compile", "check"), ("repo gates", "gate")]), \
            patch.object(cl, "zone_tests", return_value=[("zone integration", "run zone")]), \
            patch.object(cl, "repo_test_steps", return_value=[("repo integration", "run repo")], create=True) as repo:
        result = cl.recheck_steps(team, tree, ["A"])
    assert result == ([("compile", "check")], [("zone integration", "run zone"), ("repo integration", "run repo")])
    repo.assert_called_once_with(tree, "tests/integration", "integration", "land", str(ROOT / "bin" / "zone-tool"))
