"""The workspace folders a Cargo.lock change reaches.

Reach (bin/codeteam-land) turns a Cargo.lock in no zone's scope into the crates it changes, instead of every zone:
widgets's lock-tool-status-fork-lines ran 55 steps over 7 zones for one added line. A changed workspace package (no
`source`) reaches its own folder; a changed external package (with a `source`) reaches every workspace package in the
new lock that depends on it, directly or through other packages. Packages are keyed on (name, version, source), since
Cargo can lock one name and version from two sources.
"""
import tomllib

Key = tuple[str, str, str | None]


def _valid(p: object) -> bool:
    """Whether `p` is a [[package]] table this module can read: string name and version, a string source if any, and
    a list of strings as dependencies if any."""
    return (isinstance(p, dict) and isinstance(p.get("name"), str) and isinstance(p.get("version"), str)
            and isinstance(p.get("source", ""), str) and isinstance(p.get("dependencies", []), list)
            and all(isinstance(d, str) for d in p.get("dependencies", [])))


def _packages(text: str) -> dict[Key, dict] | None:
    """The lock's packages by key; None when it does not parse or holds a package this module cannot read."""
    try:
        packages = tomllib.loads(text).get("package", [])
    except tomllib.TOMLDecodeError:
        return None
    if not isinstance(packages, list) or not all(_valid(p) for p in packages):
        return None
    return {(p["name"], p["version"], p.get("source")): p for p in packages}


def _matches(entry: str, packages: dict[Key, dict]) -> list[Key]:
    """The keys a dependencies entry ("name", "name version" or "name version (source)") names."""
    name, version, source = (entry.split(" ", 2) + [None, None])[:3]
    source = source and source.strip("()")
    return [k for k in packages if k[0] == name and version in (None, k[1]) and source in (None, k[2])]


def _reaches(start: Key, targets: set[Key], packages: dict[Key, dict]) -> bool:
    """Whether the transitive dependencies of `start` include any of `targets`."""
    seen: set[Key] = set()
    stack = [start]
    while stack:
        for dep in (d for e in packages[stack.pop()].get("dependencies", []) for d in _matches(e, packages)):
            if dep in targets:
                return True
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return False


def lock_changed_folders(old_text: str, new_text: str, package_folders: dict[str, str | None]) -> list[str] | None:
    """Sorted unique folders of the workspace packages the change from `old_text` to `new_text` reaches; [] when the
    locks hold the same packages; None when a lock does not parse or holds a package entry it cannot read (no string
    name or version, a non-string source, dependencies not a list of strings, `package` not a list of tables), or a
    reached package has no usable folder in `package_folders` (missing, None, "." or "")."""
    old, new = _packages(old_text), _packages(new_text)
    if old is None or new is None:
        return None
    changed = [k for k in old.keys() | new.keys() if old.get(k) != new.get(k)]
    names = {k[0] for k in changed if k[2] is None}
    external = {k for k in changed if k[2] is not None}
    if external:
        names |= {k[0] for k in new if k[2] is None and _reaches(k, external, new)}
    folders = {package_folders.get(n) for n in names}
    if folders & {None, ".", ""}:
        return None
    return sorted(folders)
