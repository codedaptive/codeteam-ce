#!/usr/bin/env -S python3 -u
"""Two-port kits expose a separate Rust test root."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_nested_crate import nested_crate_root

W = Path(tempfile.mkdtemp(prefix="nested-crate-"))


def put(path):
    file = W / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text("\n")


def test_two_port_kit():
    put("kit/Package.swift")
    put("kit/rust/Cargo.toml")
    assert nested_crate_root(W, "kit") == "kit/rust"


def test_missing_swift():
    put("rust-only/rust/Cargo.toml")
    assert nested_crate_root(W, "rust-only") is None


def test_missing_cargo():
    put("swift-only/Package.swift")
    assert nested_crate_root(W, "swift-only") is None


def test_nested_swift_package_disqualifies():
    put("both/Package.swift")
    put("both/rust/Cargo.toml")
    put("both/rust/Package.swift")
    assert nested_crate_root(W, "both") is None


failed = 0
for name, test in list(globals().items()):
    if name.startswith("test_") and callable(test):
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
if failed:
    print(f"{failed} failed ({W} kept)")
else:
    shutil.rmtree(W)
    print("all passed")
sys.exit(bool(failed))
