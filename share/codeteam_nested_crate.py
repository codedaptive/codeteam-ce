"""A two-port kit's Rust crate as a test root of its own (D491, D484).

zone.mk's whole-zone run tests <kit> and then <kit>/rust, but `zone-test-one DIR=<kit>` runs the Swift package only.
When no Swift source or test names rust/, zone-tool's scope for <kit> is "<kit>!rust" (rust_ports), so a change in the
Rust port reaches no root but the crate's own: the kit's rust/ crate is offered as a root beside the kit. When Swift
code names rust/, the kit's own scope holds the crate too, and both roots are reached.
"""
from pathlib import Path


def nested_crate_root(tree, root: str) -> str | None:
    """`<root>/rust` when root (relative to tree) holds a Package.swift and root/rust a Cargo.toml and no
    Package.swift; else None."""
    kit = Path(tree) / root
    rust = kit / "rust"
    if (kit / "Package.swift").is_file() and (rust / "Cargo.toml").is_file() and not (rust / "Package.swift").exists():
        return f"{root.strip('/')}/rust"
    return None
