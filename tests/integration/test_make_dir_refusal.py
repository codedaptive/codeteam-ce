import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "make_dir_refusal", ROOT / "share" / "claude-hooks" / "make_dir_refusal.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
make_dir_refusal = module.make_dir_refusal


def test_real_folder_inside_zone_is_allowed(tmp_path):
    (tmp_path / "zone" / "folder").mkdir(parents=True)
    calls = []

    def in_zone(path):
        calls.append(path)
        return path.startswith("zone/")

    assert make_dir_refusal("zone/folder", str(tmp_path), str(tmp_path.resolve()), in_zone) is None
    assert calls == ["zone/folder"]


def test_real_folder_outside_zone_is_refused(tmp_path):
    (tmp_path / "outside" / "folder").mkdir(parents=True)

    assert make_dir_refusal(
        "outside/folder", str(tmp_path), str(tmp_path.resolve()),
        lambda path: path.startswith("zone/"),
    ) == "outside/folder"


def test_dotted_module_inside_zone_is_allowed(tmp_path):
    base = tmp_path / "zone"
    (base / "tests").mkdir(parents=True)
    (base / "tests" / "test_x.py").touch()

    assert make_dir_refusal(
        "tests.test_x", str(base), str(tmp_path.resolve()),
        lambda path: path.startswith("zone/"),
    ) is None


def test_dotted_module_outside_zone_is_refused(tmp_path):
    base = tmp_path / "outside"
    (base / "tests").mkdir(parents=True)
    (base / "tests" / "test_x.py").touch()

    assert make_dir_refusal(
        "tests.test_x", str(base), str(tmp_path.resolve()),
        lambda path: path.startswith("zone/"),
    ) == "tests.test_x"


def test_dotted_test_method_is_judged_by_its_module(tmp_path):
    base = tmp_path / "zone"
    (base / "tests").mkdir(parents=True)
    (base / "tests" / "test_x.py").touch()
    calls = []

    def in_zone(path):
        calls.append(path)
        return path.startswith("zone/")

    assert make_dir_refusal(
        "tests.test_x.Case.test_y", str(base), str(tmp_path.resolve()), in_zone,
    ) is None
    assert calls == ["zone/tests/test_x.py"]


def test_comma_list_refuses_only_the_outside_item(tmp_path):
    base = tmp_path / "zone"
    (base / "tests").mkdir(parents=True)
    (base / "other").mkdir()
    (base / "tests" / "test_x.py").touch()
    (base / "other" / "test_y.py").touch()

    assert make_dir_refusal(
        "tests.test_x,other.test_y", str(base), str(tmp_path.resolve()),
        lambda path: path.startswith("zone/tests/"),
    ) == "other.test_y"


def test_dotted_item_with_no_module_file_is_refused(tmp_path):
    base = tmp_path / "zone"
    base.mkdir()

    assert make_dir_refusal(
        "tests.test_x", str(base), str(tmp_path.resolve()),
        lambda path: path.startswith("zone/"),
    ) == "tests.test_x"
