"""unit test for bin/zone-tool scope_dirs: a two-port kit's unused Rust port stays out of a
dependent's scope at the landing's depth too.

zone-tool gives a kit the scope `<kit>!rust` when no Swift source or test of it names rust/, so that a change in its Rust
port reaches only the crate's own root. As a direct dependency at depth 1, the kit came in whole, so a Rust-only
change reached every Swift dependent's roots. A real temp tree stands in for the repo."""
import importlib.machinery
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def zt():
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        loader = importlib.machinery.SourceFileLoader("zone_tool_scope_ports", str(ROOT / "bin" / "zone-tool"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    finally:
        sys.dont_write_bytecode = previous


@pytest.fixture()
def tree(tmp_path, monkeypatch):
    """app depends by path on kit (whose Swift never names rust/) and on bridged (whose Swift does)."""
    monkeypatch.setenv("ZONE_SCOPE_ALWAYS", "scripts")
    files = {
        "app/Package.swift": 'dependencies: [.package(path: "../kit"), .package(path: "../bridged")]\n',
        "app/Sources/App/main.swift": "print(1)\n",
        "kit/Package.swift": "let package = Package(name: \"Kit\")\n",
        "kit/Sources/Kit/kit.swift": "// the rust/ port is a twin, not linked\npublic let k = 1\n",
        "kit/rust/Cargo.toml": "[package]\nname = \"kit\"\n",
        "bridged/Package.swift": "let package = Package(name: \"Bridged\")\n",
        "bridged/Sources/Bridged/b.swift": 'let lib = "rust/target/libbridged.a"\n',
        "bridged/rust/Cargo.toml": "[package]\nname = \"bridged\"\n",
    }
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def test_a_direct_dependency_keeps_its_rust_port_out_at_depth_one(zt, tree):
    assert zt.scope_dirs(tree, "app", depth=1) == ["app", "bridged", "kit!rust", "scripts"]


def test_the_whole_chain_keeps_it_out_as_before(zt, tree):
    # bridged's Swift names rust/, so bridged comes in whole (its rust/ under it); only path targets are entries.
    assert zt.scope_dirs(tree, "app") == ["app", "bridged", "kit!rust", "scripts"]


def test_the_kit_itself_still_excludes_its_own_port(zt, tree):
    assert zt.scope_dirs(tree, "kit", depth=1) == ["kit!rust", "scripts"]
