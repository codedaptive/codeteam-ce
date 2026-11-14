"""The files the server may hand out."""
from pathlib import Path

SUFFIXES = {".html", ".css", ".js"}


def web_files(web_dir: Path) -> dict[str, Path]:
    """Every regular file (not a symlink) under web_dir with a .html, .css or .js suffix, keyed by its posix path
    relative to web_dir ("deck.css", "js/main.js"). The server serves only these names."""
    return {path.relative_to(web_dir).as_posix(): path for path in sorted(web_dir.rglob("*"))
            if path.suffix in SUFFIXES and path.is_file() and not path.is_symlink()}
