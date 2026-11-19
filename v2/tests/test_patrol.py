"""Unit tests for patrol findings."""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from codeteam2 import patrol, team as team_module  # noqa: E402


def test_findings_refreshes_cwds_each_round_and_reuses_the_listing():
    class FakePath:
        def __truediv__(self, part):
            return self

        def is_dir(self):
            return False

    team = SimpleNamespace(
        t=SimpleNamespace(root=FakePath()),
        team_json=lambda: {'lanes': {'alpha': {}}},
        held=lambda name: False,
        manifest='fake.toml',
    )
    store = SimpleNamespace(pending=lambda held=True: [])
    v1 = SimpleNamespace(_CWDS=['/stale/tree'], PATROL_IDLE_MIN=20,
                         branch_leftovers=lambda *args: ([], [], []))
    lister = Mock(side_effect=[['/elsewhere'], ['/stale/tree/child']])
    answers = []

    def someone_inside(path):
        if v1._CWDS is None:
            v1._CWDS = lister()
        return any(c == path or c.startswith(path + '/') for c in v1._CWDS)

    def lane_lines(*args, **kwargs):
        answers.append(v1._someone_inside('/stale/tree'))
        answers.append(v1._someone_inside('/stale/tree'))
        return []

    v1._someone_inside = someone_inside
    with patch.object(team_module, 'v1', v1), \
            patch.object(patrol, 'lane_lines', side_effect=lane_lines), \
            patch.object(patrol, 'waiting_reviews', return_value=[]), \
            patch.object(patrol, 'running_lands', return_value=set()):
        patrol.findings(team, {}, {}, store, 2_000_000_000)
        assert answers == [False, False]
        assert lister.call_count == 1

        patrol.findings(team, {}, {}, store, 2_000_000_001)
        assert answers == [False, False, True, True]
        assert lister.call_count == 2
