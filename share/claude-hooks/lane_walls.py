"""The one rule for "what may this lane edit".

zone-guard.py asks it before every edit. `codeteam push-up` asks it too (walls_refusals in
bin/codeteam, cli lane), by path import (`share/claude-hooks/lane_walls.py`), before a push
goes up, so the hook and the push give one answer.
Pure stdlib. Importing it reads no environment and no file: the caller passes the lane's
facts (lane, zone, owns, team.json's lanes, the zone-docs mapping, the manifest's
orchestrator_owns) as arguments, or builds them with load_walls(), which reads the two JSON
files and the manifest TOML it is pointed at, only when called.

Paths are repo-relative, as git records them (`V2/x` is not inside `v2`). Case is never
folded to let a path through; it is folded only to refuse more (see Walls.in_area and
refused_by).
"""
import fnmatch
import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

ORCHESTRATOR = "orchestrator"
LOCKFILES = frozenset({"Cargo.lock", "Package.resolved"})   # change with a zone's own builds, anywhere
# A zone's SPEC, INTERFACE and their public copies live in these folders, named for the zone.
OWNED_DOC_DIRS = ("docs/reference", "docs/_public/reference", "docs/internal/reference")


def _norm(name):
    return re.sub(r"[^A-Z0-9]", "", name.upper())


def _matches(rel, pat):
    """rel is pat, under the folder pat, or matches the glob pat (case-sensitive)."""
    return rel == pat or rel.startswith(pat + "/") or fnmatch.fnmatchcase(rel, pat)


def _area(entry):
    """A lane's own area from its team.json entry: its zone folder (not "" or ".") and its `owns`."""
    path = str(entry.get("path", "")).strip("/")
    return ([path] if path not in ("", ".") else []) + [str(o).strip("/") for o in entry.get("owns", []) or []]


@dataclass(frozen=True)
class Walls:
    """One lane's facts. `lanes` is team.json's "lanes" as is (an entry may lack "owns" or
    "path"; one that is not a dict is skipped); `zone_docs` is zone-docs.json (keys starting
    "_" are comments); `orchestrator_owns` is the manifest's top-level list of paths the
    orchestrator owns on every lane, matched as `owns` is; empty by default.
    Methods: others, walled, in_area, owns_doc, and orchestrator_owned (is a path one the
    orchestrator owns), which refused_by asks first."""
    lane: str
    zone: str
    owns: tuple[str, ...]
    lanes: Mapping[str, Mapping]
    zone_docs: Mapping[str, str]
    orchestrator_owns: tuple[str, ...] = ()

    def others(self):
        """[(lane, path or glob)] that the other lanes own: their zone folder and their `owns`."""
        return [(n, x) for n, r in self.lanes.items()
                if n != self.lane and isinstance(r, dict) for x in _area(r)]

    def orchestrator_owned(self, rel):
        """True when rel matches an entry of orchestrator_owns: the folder and what is under it,
        an exact file or a glob, also with case folded on both sides. It holds for every
        lane, whatever its zone, and reads nothing but this object."""
        return any(_matches(rel, p) or _matches(rel.casefold(), p.casefold()) for p in self.orchestrator_owns)

    def walled(self):
        """A whole-repo lane (zone ".") on a team where other lanes own folders: it edits
        anything but those."""
        return self.zone == "." and bool(self.others())

    def in_area(self, rel):
        """True when rel is in this lane's own area. A walled lane's area is everything but
        the other lanes' areas, and a case-only match of one of those is refused too (folding
        also folds glob classes like [A-Z]; harmless, it only refuses more). A whole-repo lane
        with no other lane's area owns the whole repo. A zoned lane's area is its zone folder
        and its `owns`, compared exactly."""
        if self.walled():
            return not any(_matches(rel.casefold(), pat.casefold()) for _, pat in self.others())
        if self.zone == ".":
            return True
        return (rel == self.zone or rel.startswith(self.zone + "/")
                or any(_matches(rel, pat) for pat in self.owns))

    def _stems(self):
        """{stem: lane}: every lane's zone name normalised, with and without a Kit/Lib ending;
        the first lane wins a stem."""
        stems = {}
        for n, r in self.lanes.items():
            if not isinstance(r, dict):
                continue
            base = _norm(os.path.basename(str(r.get("path", "")).rstrip("/")))
            if base:
                for stem in {base, re.sub(r"(KIT|LIB)$", "", base) or base}:
                    stems.setdefault(stem, n)
        return stems

    def _doc_claim(self, rel):
        """Who a reference doc is named for: ("zone", zone) from zone_docs, ("lane", lane) from
        the longest lane stem, or None (not in a reference folder, or no one's name on it)."""
        d, name = os.path.split(rel)
        if d not in OWNED_DOC_DIRS:
            return None
        key = _norm(name)
        for stem, zone in self.zone_docs.items():
            if not stem.startswith("_") and key.startswith(_norm(stem)):
                return ("zone", zone.strip("/"))
        stems = self._stems()
        best = max((s for s in stems if key.startswith(s)), key=len, default=None)
        return None if best is None else ("lane", stems[best])

    def owns_doc(self, rel):
        """True for <ZONE>_*.md in docs/reference, docs/_public/reference or docs/internal/reference: the file goes to the lane
        whose zone name is the longest match (ACME_APP_* to Acme-App, not acme).
        zone_docs is read first: a stem it lists (for a name that is not a lane's folder name)
        goes to the zone it names, ahead of the lane-name match."""
        claim = self._doc_claim(rel)
        if claim is None:
            return False
        kind, who = claim
        return who == (self.zone if kind == "zone" else self.lane)


def refused_by(rel: str, walls: Walls) -> str | None:
    """None when walls.lane may edit rel; else the name of what owns it.

    It returns the owner, not a bool, because push-up lists each refused path with the lane,
    or the orchestrator, that owns it; the guard needs only None against not None.

    The orchestrator owns, ahead of every rule below (own area, own `owns`, own reference docs,
    lockfiles), any path that matches an entry of walls.orchestrator_owns the way `owns`
    matches (the folder and what is under it, an exact file, or a glob), or matches one with
    case folded on both sides (Walls.orchestrator_owned). This holds for every lane: zoned,
    walled or whole-repo.

    Otherwise allowed: a lockfile anywhere, a path in the lane's area, the lane's own reference docs. A
    walled lane's area does not include a reference doc named for another lane: that
    goes to the owner, found by rule a below.
    The owner of anything else, first that applies:
      a. a reference doc: the lane whose zone is the one zone_docs names for it (the
         orchestrator when no lane has that zone), else the lane whose zone name it carries;
      b. the first lane, in team.json order, whose area (zone folder and `owns`) matches rel;
      c. the first whose area matches with case folded on both sides (rel is a case-only
         match, refused whatever the lane);
      d. the orchestrator: no lane owns it.
    A walled lane (zone "." with other lanes' areas) is never its own owner: b and c skip it.
    A zoned lane may be named by c (`V2/x` for the lane whose zone is `v2`)."""
    if walls.orchestrator_owned(rel):
        return ORCHESTRATOR
    claim = walls._doc_claim(rel)
    if os.path.basename(rel) in LOCKFILES or walls.owns_doc(rel):
        return None
    # A walled lane's area is "everything but the others'", so in_area alone would let it into a
    # reference doc named for another lane; a claimed doc goes to the claim's owner.
    if walls.in_area(rel) and not (claim is not None and walls.walled()):
        return None
    if claim is not None:
        kind, who = claim
        if kind == "lane":
            return who
        return next((n for n, r in walls.lanes.items()
                     if isinstance(r, dict) and str(r.get("path", "")).strip("/") == who), ORCHESTRATOR)
    skip_self = walls.walled()
    areas = [(n, _area(r)) for n, r in walls.lanes.items()
             if isinstance(r, dict) and not (skip_self and n == walls.lane)]
    for n, pats in areas:
        if any(_matches(rel, p) for p in pats):
            return n
    for n, pats in areas:
        if any(_matches(rel.casefold(), p.casefold()) for p in pats):
            return n
    return ORCHESTRATOR


def load_walls(*, lane, zone, owns, team_json, codeteam_home, manifest=None) -> Walls:
    """Build a Walls from the files: team_json (path of team/team.json, or None) for the lanes,
    and <codeteam_home>/zone/zone-docs.json for the zone-docs mapping. A missing or unreadable
    team.json, or one without a "lanes" object, leaves just this lane at its zone: no other
    lane's area, and its own stem for owns_doc. A missing, unreadable or non-object zone-docs.json is {}.
    manifest (path of the team's TOML, or None) gives the top-level `orchestrator_owns` list,
    read with tomllib; entries are stripped of whitespace and "/", empties dropped, as `owns`. A
    manifest of None, missing, unreadable (a folder too) or bad TOML, an absent key or one that is
    not a list gives (): nothing changes for a team whose manifest does not set it.
    Called explicitly, never at import."""
    zone = str(zone).strip().strip("/")
    owns = tuple(x for x in (str(o).strip().strip("/") for o in owns) if x)
    try:
        lanes = json.loads(Path(team_json).read_text())["lanes"]
        if not isinstance(lanes, dict):
            raise TypeError("lanes is not an object")
    except (OSError, ValueError, KeyError, TypeError):
        lanes = {lane: {"path": zone}}
    try:
        zone_docs = json.loads((Path(codeteam_home) / "zone" / "zone-docs.json").read_text())
        if not isinstance(zone_docs, dict):
            zone_docs = {}
    except (OSError, ValueError):
        zone_docs = {}
    orch = ()
    if manifest is not None:
        try:
            with open(manifest, "rb") as f:
                raw = tomllib.load(f).get("orchestrator_owns")
            if isinstance(raw, list):
                orch = tuple(x for x in (str(o).strip().strip("/") for o in raw) if x)
        except (OSError, ValueError):
            orch = ()
    return Walls(lane=lane, zone=zone, owns=owns, lanes=lanes, zone_docs=zone_docs, orchestrator_owns=orch)
