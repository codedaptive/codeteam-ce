"""Test the opt-in selection of one test kind and its record isolation."""

import importlib.machinery
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zt():
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("zone_tool_kinds", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


@pytest.fixture
def repo(tmp_path):
    for rel, text in {
        "pkg/tests/plain.sh": "echo ok\n",
        "pkg/tests/gated.sh": '[ "${CODETEAM_TEST_GROUP:-unit}" = validation ] || exit 0\n',
        "pkg/tests/run.sh": "echo manual\n",
        "pkg/tests/test_a.py": "def test_a(): pass\n",
        "tests/unit/land-a.py": "",
        "tests/integration/land-b.py": "",
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


@pytest.mark.parametrize("group,expected", [
    ("unit", ([('py', 'pkg'), ('sh', 'pkg/tests/gated.sh'), ('sh', 'pkg/tests/plain.sh')],
              [('pkg/tests/run.sh', 'run.sh')])),
    ("integration", ([('py', 'pkg'), ('sh', 'pkg/tests/gated.sh')],
                     [('pkg/tests/plain.sh', 'unit'), ('pkg/tests/run.sh', 'run.sh')])),
    ("validation", ([('py', 'pkg'), ('sh', 'pkg/tests/gated.sh')],
                    [('pkg/tests/plain.sh', 'unit'), ('pkg/tests/run.sh', 'run.sh')])),
])
def test_named_kinds_select_discovered_shells_and_keep_pytest(zt, repo, group, expected):
    assert zt._test_one_plan(repo / 'pkg', 'pkg', False, group, kinds=True) == expected


@pytest.mark.parametrize("owned", [False, True])
def test_named_kinds_skip_direct_or_owned_unnamed_shell(zt, repo, owned):
    rel = 'pkg/tests/plain.sh'
    assert zt._test_one_plan(repo / rel, rel, owned, 'integration', kinds=True) == ([], [(rel, 'unit')])


def test_named_kinds_keep_repo_script_folder_gate(zt, repo):
    assert zt._test_one_plan(repo / 'tests', 'tests', True, 'integration', kinds=True) == (
        [('script', 'tests/integration/land-b.py')], [('tests/unit/land-a.py', 'unit')])


@pytest.mark.parametrize("group", ['unit', 'integration', 'validation'])
def test_default_plan_preserves_existing_shell_discovery(zt, repo, group):
    assert zt._test_one_plan(repo / 'pkg', 'pkg', False, group) == (
        [('py', 'pkg'), ('sh', 'pkg/tests/gated.sh'), ('sh', 'pkg/tests/plain.sh')],
        [('pkg/tests/run.sh', 'run.sh')])


@pytest.mark.parametrize("group", ['unit', 'integration', 'validation'])
def test_explicit_kinds_off_preserves_existing_shell_discovery(zt, repo, group):
    assert zt._test_one_plan(repo / 'pkg', 'pkg', False, group, kinds=False) == (
        [('py', 'pkg'), ('sh', 'pkg/tests/gated.sh'), ('sh', 'pkg/tests/plain.sh')],
        [('pkg/tests/run.sh', 'run.sh')])


@pytest.mark.parametrize("group,expected", [
    ('unit', ([('script', 'tests/unit/land-a.py')], [('tests/integration/land-b.py', 'integration')])),
    ('integration', ([('script', 'tests/integration/land-b.py')], [('tests/unit/land-a.py', 'unit')])),
    ('validation', ([], [('tests/unit/land-a.py', 'unit'), ('tests/integration/land-b.py', 'integration')])),
])
def test_default_plan_preserves_repo_folder_gates(zt, repo, group, expected):
    assert zt._test_one_plan(repo / 'tests', 'tests', True, group) == expected


@pytest.mark.parametrize("group,expected", [
    ('unit', ([('script', 'tests/unit/land-a.py')], [('tests/integration/land-b.py', 'integration')])),
    ('integration', ([('script', 'tests/integration/land-b.py')], [('tests/unit/land-a.py', 'unit')])),
    ('validation', ([], [('tests/unit/land-a.py', 'unit'), ('tests/integration/land-b.py', 'integration')])),
])
def test_explicit_kinds_off_preserves_repo_folder_gates(zt, repo, group, expected):
    assert zt._test_one_plan(repo / 'tests', 'tests', True, group, kinds=False) == expected


@pytest.mark.parametrize('group', ['unit', 'integration', 'validation'])
def test_default_direct_shell_runs_in_every_group(zt, repo, group):
    rel = 'pkg/tests/plain.sh'
    assert zt._test_one_plan(repo / rel, rel, False, group) == ([('sh', rel)], [])


@pytest.mark.parametrize('group', ['unit', 'integration', 'validation'])
def test_explicit_kinds_off_direct_shell_runs_in_every_group(zt, repo, group):
    rel = 'pkg/tests/plain.sh'
    assert zt._test_one_plan(repo / rel, rel, False, group, kinds=False) == ([('sh', rel)], [])


@pytest.mark.parametrize('switch,inherited,group', [
    ('1', '/inherited', 'integration'), (' 1 ', None, 'validation'),
    (None, None, 'unit'), ('', '/inherited', 'unit'),
    ('0', '/inherited', 'integration'), ('yes', None, 'validation'),
])
def test_pytest_command_and_pythonpath_follow_switch(zt, repo, monkeypatch, switch, inherited, group):
    for name in ('CODETEAM_KINDS_BY_NAME', 'PYTHONPATH', 'GROUP', 'CODETEAM_OWNS'):
        monkeypatch.delenv(name, raising=False)
    if switch is not None:
        monkeypatch.setenv('CODETEAM_KINDS_BY_NAME', switch)
    if inherited is not None:
        monkeypatch.setenv('PYTHONPATH', inherited)
    monkeypatch.setenv('CODETEAM_TEST_GROUP', group)
    monkeypatch.setenv('ZONE_PYTHON', 'fixed-python')
    monkeypatch.setattr(zt, 'top', lambda: repo)
    monkeypatch.setattr(zt.os, 'getcwd', lambda: str(repo))
    calls = []
    monkeypatch.setattr(zt.subprocess, 'run', lambda cmd, **kw: calls.append((cmd, kw['env'])) or SimpleNamespace(returncode=0))
    assert zt.cmd_test_one(['pkg']) == 0
    cmd, env = next(call for call in calls if call[0][0] == 'fixed-python')
    if switch is not None and switch.strip() == '1':
        assert cmd == ['fixed-python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                       '-p', 'codeteam_kinds_pytest', f'--codeteam-kind={group}', 'pkg']
        assert env['PYTHONPATH'] == str(ROOT / 'share') + (os.pathsep + inherited if inherited is not None else '')
    else:
        assert cmd == ['fixed-python', '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'pkg']
        assert env.get('PYTHONPATH') == inherited


@pytest.mark.parametrize('record_kind,switch,hit', [
    (None, None, True), (None, '1', False), ('by-name', '1', True), ('by-name', None, False),
])
@pytest.mark.parametrize('branch', ['whole', 'restamp'])
def test_record_hit_requires_matching_kind_in_both_branches(zt, tmp_path, monkeypatch, record_kind, switch, hit, branch):
    monkeypatch.delenv('CODETEAM_KINDS_BY_NAME', raising=False)
    if switch is not None:
        monkeypatch.setenv('CODETEAM_KINDS_BY_NAME', switch)
    monkeypatch.setattr(zt, 'snapshot', lambda root: ('tree', []))
    monkeypatch.setattr(zt, 'scope_dirs', lambda root, arg: ['pkg!rust'])
    monkeypatch.setattr(zt, 'code_hash', lambda root, scope, snap: {
        None: 'whole-now', ('pkg!rust',): 'narrow-now', ('pkg',): 'wide-now',
    }[tuple(scope) if scope is not None else None])
    rec = {'result': 'PASS', 'salt': 's', 'command': 'run', 'hash': 'whole-now'}
    if branch == 'restamp':
        rec.update(hash='old-whole', scope=['pkg'], scope_hash='wide-now')
    if record_kind is not None:
        rec['kinds'] = record_kind
    path = zt.record_path(tmp_path, 'key')
    path.write_text(json.dumps(rec))
    actual = zt.record_hit(tmp_path, 'key', 's', 'pkg', 'run')[0]
    assert (actual is not None) is hit
    if not hit:
        assert json.loads(path.read_text()) == rec


@pytest.mark.parametrize('switch,expected', [(None, None), ('1', 'by-name'), ('0', None), ('yes', None)])
def test_cmd_test_records_only_enabled_kind(zt, tmp_path, monkeypatch, switch, expected):
    monkeypatch.delenv('CODETEAM_KINDS_BY_NAME', raising=False)
    if switch is not None:
        monkeypatch.setenv('CODETEAM_KINDS_BY_NAME', switch)
    monkeypatch.setattr(zt, 'top', lambda: tmp_path)
    monkeypatch.setattr(zt, 'record_hit', lambda *args: (None, ('tree', []), 'hash', None, None))
    monkeypatch.setattr(zt, 'commit_state', lambda root: (None, False))
    monkeypatch.setattr(zt, 'append_commit_record', lambda *args: None)
    monkeypatch.setattr(zt, 'hang_wait', lambda *args: (0, None))
    monkeypatch.setattr(zt.subprocess, 'Popen', lambda *args, **kwargs: SimpleNamespace(stdout=[], pid=123))
    assert zt.cmd_test(['--key', 'key', '--', 'fake-test']) == 0
    record = json.loads(zt.record_path(tmp_path, 'key').read_text())
    assert record['result'] == 'PASS'
    if expected is None:
        assert 'kinds' not in record
    else:
        assert record.get('kinds') == expected
