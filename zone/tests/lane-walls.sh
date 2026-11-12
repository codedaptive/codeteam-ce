#!/bin/bash
# zone/tests/lane-walls.sh: the ownership rule the zone guard and push-up share, in
# share/claude-hooks/lane_walls.py. Table tests in one inline python run with python3. The module is
# imported by path, so until it exists every case fails, and each case reports the import error.
# Cases: the constants (OWNED_DOC_DIRS now with docs/internal/reference) and a frozen Walls with
# its orchestrator_owns field; a zoned lane (in-zone, a sibling folder, owns globs and folders,
# out-of-zone owners, the orchestrator, mixed case refused, own and another zone's SPEC and
# INTERFACE, the longest stem, lockfiles); a walled lane (another lane's folder refused with its
# owner, mixed case, bin/zone-tool allowed, its own owns not counted, the owner never the lane
# itself, its reference docs: another lane's SPEC or INTERFACE to that lane, a zone-docs zone to
# its lane or the orchestrator, unclaimed docs and docs outside the reference folders still
# allowed); the '.' lane with no other area, its docs too; walled(), others(); load_walls
# (fallbacks, the zone-docs.json override, stripping, a team.json shaped like team/team.json);
# orchestrator_owns from a manifest (missing, unreadable, bad TOML, absent key, non-list: empty;
# stripped entries; folder, file, glob and case-only matches, ahead of the lane's area, owns, own
# doc and lockfile, for zoned, walled and unwalled '.' lanes); docs/internal/reference (own SPEC
# is the lane's, another's goes to its owner); Walls.orchestrator_owned (a folder and what is under it,
# an exact file, a glob, a case-only match, a non-match, no entries); and import reads no
# environment and no file.
# No git, no network. The only files are in a mktemp dir that is removed on exit.
root="$(cd "$(dirname "$0")/../.." && pwd)"
py=python3
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# -I: the environment and this script's folder are not on the path. -B: no bytecode is written into share/.
"$py" -I -B - "$root" "$tmp" <<'PY'
import dataclasses
import json
import os
import pathlib
import subprocess
import sys

root, tmp = sys.argv[1], pathlib.Path(sys.argv[2])
share = os.path.join(root, "share", "claude-hooks")
sys.path.insert(0, share)

ORC = "orchestrator"   # the owner the contract names when no lane owns a refused path
try:
    import lane_walls as _lw
    _why = ""
except Exception as e:   # no share/claude-hooks/lane_walls.py yet: every case below is red
    _lw = None
    _why = f"{type(e).__name__}: {e}"


def mod():
    if _lw is None:
        raise ImportError(f"lane_walls is not importable ({_why})")
    return _lw


def W(**kw):
    return mod().Walls(**kw)


def refused(rel, w):
    return mod().refused_by(rel, w)


def load(**kw):
    return mod().load_walls(**kw)


# A copy of the shape of team/team.json: cli and zone are whole-repo lanes ('.') with owns;
# v2 and the model lanes are zones. A fixture, so the test does not move with the live file.
TEAM = {
    "cli": {"path": ".", "owns": ["bin/codeteam", "roles", "tests", "docs", "README.md", "MANUAL-zones.md"]},
    "zone": {"path": ".", "owns": ["zone", "share", "bin/zone-tool", "bin/cargo"]},
    "v2": {"path": "v2", "owns": []},
    "model-benchmarks": {"path": "model/benchmarks", "owns": []},
    "model-reporting": {"path": "model/reporting", "owns": []},
}
ZONE_OWNS = tuple(TEAM["zone"]["owns"])
CLI_OWNS = tuple(TEAM["cli"]["owns"])
DOCS = {"AKit": {"path": "packages/kits/AKit", "owns": []},
        "BKit": {"path": "packages/kits/BKit", "owns": []}}
KIT = {"kit": {"path": "packages/kit", "owns": ["share/*.py", "bin/zone-tool"]},
       "other": {"path": "packages/other", "owns": []}}
ACME = {"acme": {"path": "apps/acme", "owns": []},
        "Acme-App": {"path": "apps/Acme-App", "owns": []}}
INST = {"acme": {"path": "apps/acme", "owns": []},
        "installer": {"path": "packages/installer", "owns": []}}
SAME = {"zone": {"path": ".", "owns": ["bin/codeteam"]},
        "cli": {"path": ".", "owns": ["bin/codeteam"]}}
SOLO = {"solo": {"path": ".", "owns": []}, "other": {"path": ".", "owns": []}}
OTH = {"zone": {"path": ".", "owns": ["zone", "share"]},
       "cli": {"path": ".", "owns": ["bin/codeteam", "roles"]},
       "v2": {"path": "v2", "owns": ["tools/v2-cli"]},
       "model-benchmarks": {"path": "model/benchmarks", "owns": []}}
BARE = {"zone": {"path": "zone", "owns": []}}

EMPTY = tmp / "empty-home"
EMPTY.mkdir()
HOME = tmp / "home"
(HOME / "zone").mkdir(parents=True)
(HOME / "zone" / "zone-docs.json").write_text(
    json.dumps({"_doc": "apps/acme", "INSTALLER": "apps/acme"}))
TEAMF = tmp / "team.json"
TEAMF.write_text(json.dumps({"lanes": TEAM}))
INSTF = tmp / "inst-team.json"
INSTF.write_text(json.dumps({"lanes": INST}))
BAD = tmp / "bad.json"
BAD.write_text("{not json")
NOLANES = tmp / "nolanes.json"
NOLANES.write_text(json.dumps({"product": "codeteam"}))
MISSING = tmp / "missing.json"


def ZL():   # team.json's zone lane: whole-repo, walled by cli and v2
    return W(lane="zone", zone=".", owns=ZONE_OWNS, lanes=TEAM, zone_docs={})


def V2():   # a zoned lane
    return W(lane="v2", zone="v2", owns=(), lanes=TEAM, zone_docs={})


def KITW():
    return W(lane="kit", zone="packages/kit", owns=("share/*.py", "bin/zone-tool"), lanes=KIT, zone_docs={})


def AK():
    return W(lane="AKit", zone="packages/kits/AKit", owns=(), lanes=DOCS, zone_docs={})


def MX():
    return W(lane="acme", zone="apps/acme", owns=(), lanes=ACME, zone_docs={})


def MA():
    return W(lane="Acme-App", zone="apps/Acme-App", owns=(), lanes=ACME, zone_docs={})


def teamw():
    return load(lane="zone", zone=".", owns=list(ZONE_OWNS), team_json=TEAMF, codeteam_home=EMPTY)


def fallback(team_json):
    w = load(lane="AKit", zone="packages/kits/AKit", owns=[], team_json=team_json, codeteam_home=EMPTY)
    return (w.others(), w.walled(), w.owns_doc("docs/reference/AKIT_SPEC.md"),
            w.owns_doc("docs/reference/BKIT_SPEC.md"), refused("packages/kits/AKit/x.py", w))


PASS = FAIL = 0


def check(name, want, thunk):
    global PASS, FAIL
    try:
        got = thunk()
    except Exception as e:
        got = f"raised {type(e).__name__}: {e}"
    if got == want:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} (got {str(got)[:160]}, wanted {str(want)[:160]})")


# ---- the module's constants and its data type
check("lane_walls imports by path from share/claude-hooks", True, lambda: mod() is not None)
check("ORCHESTRATOR is 'orchestrator'", ORC, lambda: mod().ORCHESTRATOR)
check("LOCKFILES are Cargo.lock and Package.resolved", {"Cargo.lock", "Package.resolved"},
      lambda: set(mod().LOCKFILES))
check("OWNED_DOC_DIRS are docs/reference, docs/_public/reference and docs/internal/reference",
      ("docs/reference", "docs/_public/reference", "docs/internal/reference"),
      lambda: tuple(mod().OWNED_DOC_DIRS))


def frozen():
    w = W(lane="v2", zone="v2", owns=(), lanes=TEAM, zone_docs={})
    try:
        w.lane = "x"
        immutable = False
    except dataclasses.FrozenInstanceError:
        immutable = True
    return (immutable, tuple(f.name for f in dataclasses.fields(w)))


check("Walls is a frozen dataclass: lane, zone, owns, lanes, zone_docs, orchestrator_owns",
      (True, ("lane", "zone", "owns", "lanes", "zone_docs", "orchestrator_owns")), frozen)
check("Walls.orchestrator_owns defaults to () (a Walls built without it, as before)", (),
      lambda: W(lane="v2", zone="v2", owns=(), lanes=TEAM, zone_docs={}).orchestrator_owns)

# ---- a zoned lane (v2 in team.json)
check("zoned: v2/codeteam2.py may be edited", None, lambda: refused("v2/codeteam2.py", V2()))
check("zoned: the zone folder itself is in the lane's area", True, lambda: V2().in_area("v2"))
check("zoned: v2x/y is a sibling folder, not the zone; no owner, so orchestrator",
      (False, ORC), lambda: (V2().in_area("v2x/y"), refused("v2x/y", V2())))
check("zoned: out of zone, model/benchmarks/x.py owned by model-benchmarks",
      "model-benchmarks", lambda: refused("model/benchmarks/x.py", V2()))
check("zoned: out of zone, docs/ROADMAP.md owned by cli", "cli",
      lambda: refused("docs/ROADMAP.md", V2()))
check("zoned: out of zone, nobody/x.txt has no owner, so orchestrator", ORC,
      lambda: refused("nobody/x.txt", V2()))
check("zoned: mixed case V2/x refused, owner v2", "v2", lambda: refused("V2/x", V2()))

# ---- owns globs and folders for a zoned lane
check("owns glob: share/a.py may be edited (owns share/*.py)", None,
      lambda: refused("share/a.py", KITW()))
check("owns glob: share/a.txt is outside the glob; no owner, so orchestrator", ORC,
      lambda: refused("share/a.txt", KITW()))
check("owns folder: bin/zone-tool/sub/x.sh may be edited (owns bin/zone-tool)", None,
      lambda: refused("bin/zone-tool/sub/x.sh", KITW()))
check("owns case: BIN/zone-tool refused for a zoned lane, owner kit", "kit",
      lambda: refused("BIN/zone-tool", KITW()))

# ---- reference docs: own, another zone's, outside the folders, unclaimed
check("own SPEC in docs/reference and own INTERFACE in docs/_public/reference may be edited",
      (True, True, None, None), lambda: (AK().owns_doc("docs/reference/AKIT_SPEC.md"),
                                         AK().owns_doc("docs/_public/reference/AKit_INTERFACE.md"),
                                         refused("docs/reference/AKIT_SPEC.md", AK()),
                                         refused("docs/_public/reference/AKit_INTERFACE.md", AK())))
check("another zone's SPEC (BKIT_SPEC.md) is not AKit's and is refused, owner BKit",
      (False, "BKit"), lambda: (AK().owns_doc("docs/reference/BKIT_SPEC.md"),
                                refused("docs/reference/BKIT_SPEC.md", AK())))
check("another zone's INTERFACE in docs/_public/reference is refused, owner BKit", "BKit",
      lambda: refused("docs/_public/reference/BKit_INTERFACE.md", AK()))
check("a doc outside the two reference folders is no zone doc (owner orchestrator)",
      (False, False, ORC), lambda: (AK().owns_doc("docs/other/AKIT_SPEC.md"),
                                    AK().owns_doc("docs/reference/old/AKIT_SPEC.md"),
                                    refused("docs/other/AKIT_SPEC.md", AK())))
check("a reference doc no zone claims is refused, owner orchestrator", ORC,
      lambda: refused("docs/reference/NOBODY_SPEC.md", AK()))
check("longest stem: ACME_APP_SPEC.md is Acme-App's, not acme's", (False, True),
      lambda: (MX().owns_doc("docs/reference/ACME_APP_SPEC.md"),
               MA().owns_doc("docs/reference/ACME_APP_SPEC.md")))
check("longest stem: acme refused ACME_APP_SPEC.md, owner Acme-App", "Acme-App",
      lambda: refused("docs/reference/ACME_APP_SPEC.md", MX()))

# ---- lockfiles: allowed inside, outside and in another lane's area
check("lockfile: Cargo.lock inside, outside and in another lane's area may be edited",
      (None, None, None), lambda: (refused("v2/sub/Cargo.lock", V2()), refused("Cargo.lock", V2()),
                                   refused("model/benchmarks/Package.resolved", V2())))
check("lockfile: Cargo.lock.bak is not a lockfile; no owner, so orchestrator", ORC,
      lambda: refused("Cargo.lock.bak", V2()))

# ---- a walled lane (zone '.' with other lanes' areas)
check("walled: zone lane refuses v2/x, owner v2", "v2", lambda: refused("v2/x", ZL()))
check("walled: zone lane refuses V2/x (case ignored), owner v2", "v2", lambda: refused("V2/x", ZL()))
check("walled: zone lane may edit bin/zone-tool", (True, None),
      lambda: (ZL().in_area("bin/zone-tool"), refused("bin/zone-tool", ZL())))
check("walled: zone lane may edit v2x/y (a folder that only starts with v2)", None,
      lambda: refused("v2x/y", ZL()))
check("walled: zone lane may edit lib/unowned.rs (no lane owns it)", None,
      lambda: refused("lib/unowned.rs", ZL()))
check("walled: zone lane refuses bin/codeteam (cli owns it), owner cli", "cli",
      lambda: refused("bin/codeteam", ZL()))
check("walled: a walled lane's own owns do not matter (cli may edit bin/codeteam it owns)", None,
      lambda: refused("bin/codeteam", W(lane="cli", zone=".", owns=CLI_OWNS, lanes=TEAM, zone_docs={})))
check("walled: the owner is never the lane itself (zone and cli both list bin/codeteam), owner cli",
      "cli", lambda: refused("bin/codeteam", W(lane="zone", zone=".", owns=("bin/codeteam",),
                                               lanes=SAME, zone_docs={})))
check("walled(): true for zone '.' when another lane has an area", True, lambda: ZL().walled())
check("walled(): false for a zoned lane", False, lambda: V2().walled())


def solo():
    return W(lane="solo", zone=".", owns=(), lanes=SOLO, zone_docs={})


check("'.' lane with no other lane's area: not walled, others() empty, may edit every path",
      (False, [], None, None), lambda: (solo().walled(), solo().others(), refused("v2/x", solo()),
                                        refused("bin/codeteam", solo())))
check("others(): other lanes' zone paths and owns, not its own and not '.'",
      sorted([("cli", "bin/codeteam"), ("cli", "roles"), ("model-benchmarks", "model/benchmarks"),
              ("v2", "tools/v2-cli"), ("v2", "v2")]),
      lambda: sorted(tuple(x) for x in W(lane="zone", zone=".", owns=("zone", "share"),
                                         lanes=OTH, zone_docs={}).others()))
check("zoned lane names itself on a case-only match: Zone/x from lane zone (path zone) -> zone",
      "zone", lambda: refused("Zone/x", W(lane="zone", zone="zone", owns=(), lanes=BARE, zone_docs={})))

# ---- a walled lane's reference docs: a doc another lane is named for goes to that lane
WD = {"tool": {"path": ".", "owns": ["share"]},
      "AKit": {"path": "packages/kits/AKit", "owns": []},
      "BKit": {"path": "packages/kits/BKit", "owns": []},
      "acme": {"path": "apps/acme", "owns": []}}


def WT(zone_docs=None):   # the walled lane 'tool': zone '.' beside AKit, BKit and acme's areas
    return W(lane="tool", zone=".", owns=("share",), lanes=WD, zone_docs=dict(zone_docs or {}))


def ZA():   # AKit zoned on the same fixture
    return W(lane="AKit", zone="packages/kits/AKit", owns=(), lanes=WD, zone_docs={})


check("walled: docs/reference/BKIT_SPEC.md is named for BKit, owner BKit", "BKit",
      lambda: refused("docs/reference/BKIT_SPEC.md", WT()))
check("walled: docs/_public/reference/BKit_INTERFACE.md is BKit's, owner BKit", "BKit",
      lambda: refused("docs/_public/reference/BKit_INTERFACE.md", WT()))
check("walled: zone-docs gives INSTALLER to apps/acme, so owner acme", "acme",
      lambda: refused("docs/reference/INSTALLER_SPEC.md", WT({"INSTALLER": "apps/acme"})))
check("walled: zone-docs gives GHOST to apps/ghost (no lane has it), so owner orchestrator", ORC,
      lambda: refused("docs/reference/GHOST_SPEC.md", WT({"GHOST": "apps/ghost"})))
check("walled: a reference doc no lane is named for is in the lane's area, None", None,
      lambda: refused("docs/reference/NOBODY_SPEC.md", WT()))
check("walled: docs/notes.md is outside the reference folders, None", None,
      lambda: refused("docs/notes.md", WT()))
check("walled: packages/kits/AKit/x.swift is AKit's folder, owner AKit", "AKit",
      lambda: refused("packages/kits/AKit/x.swift", WT()))
check("zoned AKit on the same fixture: own AKIT_SPEC.md None, BKIT_SPEC.md owner BKit",
      (None, "BKit"), lambda: (refused("docs/reference/AKIT_SPEC.md", ZA()),
                               refused("docs/reference/BKIT_SPEC.md", ZA())))
# zone-docs names BKit's folder here, so a doc-claim check that ignored walls would not return None.
check("unwalled '.' lane, no other area: BKIT_SPEC.md is None even with a zone-docs claim", None,
      lambda: refused("docs/reference/BKIT_SPEC.md",
                      W(lane="solo", zone=".", owns=(), lanes={"solo": {"path": "."}},
                        zone_docs={"BKIT": "packages/kits/BKit"})))

# ---- load_walls: fallbacks, the zone-docs.json override, stripping, a team.json
FB = ([], False, True, False, None)
check("load_walls, team_json None: own stem works, no others", FB, lambda: fallback(None))
check("load_walls, team_json missing: same fallback", FB, lambda: fallback(MISSING))
check("load_walls, bad JSON: same fallback", FB, lambda: fallback(BAD))
check("load_walls, no 'lanes' key: same fallback", FB, lambda: fallback(NOLANES))


def mx_loaded():
    return load(lane="acme", zone="apps/acme", owns=[], team_json=INSTF, codeteam_home=HOME)


def ins_loaded():
    return load(lane="installer", zone="packages/installer", owns=[], team_json=INSTF, codeteam_home=HOME)


check("zone-docs.json: INSTALLER_SPEC.md is apps/acme's (owns_doc for acme)", True,
      lambda: mx_loaded().owns_doc("docs/reference/INSTALLER_SPEC.md"))
check("zone-docs.json: installer is refused INSTALLER_SPEC.md, owner acme", (False, "acme"),
      lambda: (ins_loaded().owns_doc("docs/reference/INSTALLER_SPEC.md"),
               refused("docs/reference/INSTALLER_SPEC.md", ins_loaded())))
check("zone-docs.json: a key starting with _ is ignored (DOC_SPEC.md is not acme's)", False,
      lambda: mx_loaded().owns_doc("docs/reference/DOC_SPEC.md"))
check("load_walls strips '/' and whitespace from zone and owns", ("v2", ("bin/zone-tool", "share/*.py")),
      lambda: (load(lane="v2", zone="/v2/ ", owns=[" bin/zone-tool/ ", "share/*.py/"],
                    team_json=TEAMF, codeteam_home=EMPTY).zone,
               tuple(load(lane="v2", zone="/v2/ ", owns=[" bin/zone-tool/ ", "share/*.py/"],
                          team_json=TEAMF, codeteam_home=EMPTY).owns)))
check("load_walls keeps team.json's lanes as they are", TEAM, lambda: teamw().lanes)
check("load_walls on a team.json shaped like team/team.json: zone lane walled, bin/codeteam -> cli, "
      "bin/zone-tool may be edited", (True, "cli", None),
      lambda: (teamw().walled(), refused("bin/codeteam", teamw()), refused("bin/zone-tool", teamw())))

# ---- orchestrator_owns: a path the orchestrator owns is refused, ahead of every lane's rule
def ORC_W(lane, zone, owns, lanes, orc):
    return W(lane=lane, zone=zone, owns=tuple(owns), lanes=lanes, zone_docs={},
             orchestrator_owns=tuple(orc))


def ZLO(*orc):   # the walled zone lane (zone '.' beside TEAM's areas) with orchestrator_owns orc
    return ORC_W("zone", ".", ZONE_OWNS, TEAM, orc)


def VO(*orc):    # the zoned v2 lane (TEAM) with orchestrator_owns orc
    return ORC_W("v2", "v2", (), TEAM, orc)


def loaded(manifest):   # the walled zone lane built from the files, with manifest as its manifest
    return load(lane="zone", zone=".", owns=list(ZONE_OWNS), team_json=TEAMF, codeteam_home=EMPTY,
                manifest=manifest)


def probe(w):   # the manifest's list, and four answers that must stay as they were without it
    return (w.orchestrator_owns, refused("bin/codeteam", w), refused("share/x.py", w), refused("v2/x", w))


UNCHANGED = ((), "cli", None, "v2")   # probe() of the walled zone lane with no orchestrator_owns

ORC_TOML = tmp / "orc.toml"   # the key at top level, before the [[lanes]] table
ORC_TOML.write_text('product = "codeteam"\n'
                    'orchestrator_owns = ["share/claude-hooks", "docs/reference/ZONE_SPEC.md"]\n'
                    '\n[[lanes]]\nname = "zone"\npath = "."\n')
STRIP_TOML = tmp / "strip.toml"
STRIP_TOML.write_text('orchestrator_owns = [" /share/x/ ", "", "   ", "docs/reference/ZONE_SPEC.md"]\n')
NOKEY_TOML = tmp / "nokey.toml"
NOKEY_TOML.write_text('product = "codeteam"\n\n[[lanes]]\nname = "zone"\npath = "."\n')
NONLIST_TOML = tmp / "nonlist.toml"
NONLIST_TOML.write_text('orchestrator_owns = "share/claude-hooks"\n')
BADT = tmp / "bad-manifest.toml"
BADT.write_text('orchestrator_owns = [\n')
NOFILE_TOML = tmp / "no-such-manifest.toml"
DIRM = tmp / "manifest-is-a-folder"
DIRM.mkdir()

check("load_walls with no manifest argument: orchestrator_owns is (), refused_by as before",
      UNCHANGED, lambda: probe(teamw()))
check("load_walls, manifest None: orchestrator_owns is (), refused_by as before",
      UNCHANGED, lambda: probe(loaded(None)))
check("load_walls, manifest path missing: orchestrator_owns is (), refused_by as before",
      UNCHANGED, lambda: probe(loaded(NOFILE_TOML)))
check("load_walls, manifest unreadable (a folder): orchestrator_owns is (), refused_by as before",
      UNCHANGED, lambda: probe(loaded(DIRM)))
check("load_walls, manifest bad TOML: orchestrator_owns is (), refused_by as before",
      UNCHANGED, lambda: probe(loaded(BADT)))
check("load_walls, manifest with no orchestrator_owns key: orchestrator_owns is (), refused_by as before",
      UNCHANGED, lambda: probe(loaded(NOKEY_TOML)))
check("load_walls, manifest with a non-list orchestrator_owns (a string): orchestrator_owns is (), "
      "refused_by as before", UNCHANGED, lambda: probe(loaded(NONLIST_TOML)))
check("load_walls reads the top-level orchestrator_owns list from the manifest, order kept",
      ("share/claude-hooks", "docs/reference/ZONE_SPEC.md"), lambda: loaded(ORC_TOML).orchestrator_owns)
check("load_walls strips whitespace and '/' from orchestrator_owns entries and drops empties",
      ("share/x", "docs/reference/ZONE_SPEC.md"), lambda: loaded(STRIP_TOML).orchestrator_owns)
check("manifest entry share/claude-hooks: share/claude-hooks/lane_walls.py is ORCHESTRATOR, from the file",
      ORC, lambda: refused("share/claude-hooks/lane_walls.py", loaded(ORC_TOML)))

# A folder entry (the folder and what is under it), an exact file and a glob, each ahead of the owner.
check("orchestrator_owns folder: model/benchmarks/x.py is ORCHESTRATOR for zoned v2 (without it: model-benchmarks)",
      (ORC, "model-benchmarks"),
      lambda: (refused("model/benchmarks/x.py", VO("model/benchmarks")), refused("model/benchmarks/x.py", VO())))
check("orchestrator_owns file: v2/DECISIONS.md is ORCHESTRATOR for zoned v2; its sibling .md.bak and the file without it stay v2's",
      (ORC, None, None),
      lambda: (refused("v2/DECISIONS.md", VO("v2/DECISIONS.md")),
               refused("v2/DECISIONS.md.bak", VO("v2/DECISIONS.md")),
               refused("v2/DECISIONS.md", VO())))
check("orchestrator_owns glob: share/*.py is ORCHESTRATOR for the walled zone lane, share/a.txt stays the lane's",
      (ORC, None), lambda: (refused("share/a.py", ZLO("share/*.py")), refused("share/a.txt", ZLO("share/*.py"))))

# A case-only match (casefold on both sides) is ORCHESTRATOR too, for a walled and a zoned lane.
check("orchestrator_owns case-only: SHARE/x is ORCHESTRATOR for entry share (walled zone lane), without it None",
      (ORC, None), lambda: (refused("SHARE/x", ZLO("share")), refused("SHARE/x", ZLO())))
check("orchestrator_owns case-only, zoned: v2/decisions.md is ORCHESTRATOR for entry V2/DECISIONS.md, without it None",
      (ORC, None), lambda: (refused("v2/decisions.md", VO("V2/DECISIONS.md")), refused("v2/decisions.md", VO())))

# Ahead of every other rule: the lane's own area, its owns, its own reference doc, the lockfile.
check("ahead of own area: zone lane owns share, entry share/claude-hooks -> ORCHESTRATOR, without it None",
      (ORC, None), lambda: (refused("share/claude-hooks/lane_walls.py", ZLO("share/claude-hooks")),
                            refused("share/claude-hooks/lane_walls.py", ZLO())))
check("ahead of own zone folder: zoned v2 with entry v2/codeteam2.py -> ORCHESTRATOR",
      ORC, lambda: refused("v2/codeteam2.py", VO("v2/codeteam2.py")))
check("ahead of own owns: zoned kit with entry bin/zone-tool -> ORCHESTRATOR for bin/zone-tool/sub/x.sh, without it None",
      (ORC, None), lambda: (refused("bin/zone-tool/sub/x.sh", ORC_W("kit", "packages/kit", ("share/*.py", "bin/zone-tool"),
                                                                  KIT, ("bin/zone-tool",))),
                            refused("bin/zone-tool/sub/x.sh", KITW())))
check("ahead of own reference doc: zone lane (zone 'zone') with entry docs/reference/ZONE_SPEC.md -> ORCHESTRATOR, without it None",
      (ORC, None), lambda: (refused("docs/reference/ZONE_SPEC.md", ORC_W("zone", "zone", (), BARE, ("docs/reference/ZONE_SPEC.md",))),
                            refused("docs/reference/ZONE_SPEC.md", ORC_W("zone", "zone", (), BARE, ()))))
check("ahead of the lockfile rule: entry Cargo.lock -> ORCHESTRATOR for zoned v2; v2/sub/Cargo.lock and the lockfile without it stay allowed",
      (ORC, None, None), lambda: (refused("Cargo.lock", VO("Cargo.lock")), refused("v2/sub/Cargo.lock", VO("Cargo.lock")),
                                  refused("Cargo.lock", VO())))

# The walled lane and the unwalled '.' lane with no other area.
check("walled: entry model/benchmarks -> ORCHESTRATOR for model/benchmarks/x.py (without it: model-benchmarks)",
      (ORC, "model-benchmarks"), lambda: (refused("model/benchmarks/x.py", ZLO("model/benchmarks")),
                                          refused("model/benchmarks/x.py", ZLO())))
check("unwalled '.' lane with no other lane's area: entry v2/x -> ORCHESTRATOR, without it None",
      (ORC, None), lambda: (refused("v2/x", W(lane="solo", zone=".", owns=(), lanes=SOLO, zone_docs={},
                                             orchestrator_owns=("v2/x",))),
                            refused("v2/x", solo())))

# docs/internal/reference: an own SPEC is the lane's, another zone's goes to its owner.
check("docs/internal/reference: AKit's own SPEC is AKit's (None), BKIT_SPEC.md is refused, owner BKit",
      (True, None, False, "BKit"),
      lambda: (AK().owns_doc("docs/internal/reference/AKIT_SPEC.md"),
               refused("docs/internal/reference/AKIT_SPEC.md", AK()),
               AK().owns_doc("docs/internal/reference/BKIT_SPEC.md"),
               refused("docs/internal/reference/BKIT_SPEC.md", AK())))
check("docs/internal/reference, walled lane: BKIT_SPEC.md is named for BKit, owner BKit", "BKit",
      lambda: refused("docs/internal/reference/BKIT_SPEC.md", WT()))
check("docs/internal alone is no reference folder: the reference SPEC is AKit's, docs/internal/AKIT_SPEC.md "
      "and docs/internal/other/AKIT_SPEC.md are no zone doc, owner orchestrator",
      (True, False, False, ORC),
      lambda: (AK().owns_doc("docs/internal/reference/AKIT_SPEC.md"), AK().owns_doc("docs/internal/AKIT_SPEC.md"),
               AK().owns_doc("docs/internal/other/AKIT_SPEC.md"), refused("docs/internal/AKIT_SPEC.md", AK())))

# ---- Walls.orchestrator_owned: the answer the unwalled '.' lane's guard
# uses. True when rel matches an entry of orchestrator_owns the way owns matches (the folder and what is
# under it, an exact file, a glob), or matches with case folded on both sides. VO(*orc) is the zoned v2
# lane (TEAM) with orchestrator_owns orc; the lane does not matter to this method.
check("orchestrator_owned: folder entry teams covers teams/x.toml", True,
      lambda: VO("teams").orchestrator_owned("teams/x.toml"))
check("orchestrator_owned: folder entry teams covers the folder itself", True,
      lambda: VO("teams").orchestrator_owned("teams"))
check("orchestrator_owned: exact file entry v2/DECISIONS.md covers that file, not its .bak sibling",
      (True, False), lambda: (VO("v2/DECISIONS.md").orchestrator_owned("v2/DECISIONS.md"),
                              VO("v2/DECISIONS.md").orchestrator_owned("v2/DECISIONS.md.bak")))
check("orchestrator_owned: glob share/*.py covers share/a.py, not share/a.txt",
      (True, False), lambda: (VO("share/*.py").orchestrator_owned("share/a.py"),
                              VO("share/*.py").orchestrator_owned("share/a.txt")))
check("orchestrator_owned: non-match bin/foo is False for entry teams", False,
      lambda: VO("teams").orchestrator_owned("bin/foo"))
check("orchestrator_owned: teamsx/y is False for entry teams (a sibling folder that only starts with it)",
      False, lambda: VO("teams").orchestrator_owned("teamsx/y"))
check("orchestrator_owned: case-only match Teams/x.toml is True for entry teams", True,
      lambda: VO("teams").orchestrator_owned("Teams/x.toml"))
check("orchestrator_owned: no orchestrator_owns entries is False for every path", (False, False),
      lambda: (VO().orchestrator_owned("teams/x.toml"), VO().orchestrator_owned("teams")))

# ---- import: no environment read and no file read at import
TRAP = r'''
import builtins, dataclasses, fnmatch, importlib.util, io, json, os, pathlib, re, sys, typing

class Trap:
    def __getattr__(self, name):
        raise RuntimeError("reads the environment: " + name)
    def __getitem__(self, key):
        raise RuntimeError("reads the environment: " + str(key))
    def __contains__(self, key):
        raise RuntimeError("reads the environment")
    def __iter__(self):
        raise RuntimeError("reads the environment")
    def __len__(self):
        raise RuntimeError("reads the environment")

def no_file(*a, **k):
    raise RuntimeError("reads a file at import")

os.environ = Trap()
builtins.open = no_file
io.open = no_file
pathlib.Path.open = no_file
pathlib.Path.read_text = no_file
spec = importlib.util.spec_from_file_location("lane_walls", sys.argv[1])
loaded = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loaded)
print("IMPORT-OK")
'''


def trapped():
    r = subprocess.run([sys.executable, "-I", "-B", "-c", TRAP, os.path.join(share, "lane_walls.py")],
                       capture_output=True, text=True, timeout=60)
    if r.returncode == 0 and r.stdout.strip().endswith("IMPORT-OK"):
        return "IMPORT-OK"
    err = (r.stderr.strip().splitlines() or ["no output"])[-1]
    return f"exit {r.returncode}: {err}"


check("import reads no environment and no file", "IMPORT-OK", trapped)

print(f"== lane-walls: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
PY
