"""Recipients for the edge cases the acme fixture does not reach (used by tests/run.sh):
a sole decider's READY, a team with no guard, and a managed backporter on the base PUSHED."""
import importlib.machinery
import importlib.util
from pathlib import Path
from types import SimpleNamespace

tool = Path(__file__).resolve().parent.parent / "bin" / "codeteam"
spec = importlib.util.spec_from_loader("codeteam", importlib.machinery.SourceFileLoader("codeteam", str(tool)))
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def team(builder="", guard="", assistants=None):
    a = assistants or {}
    return SimpleNamespace(builder=builder, guard=guard, assistants=a, orc_name=lambda: "Orc-X",
                           managed=lambda n: not a.get(n, {}).get("external", False))


solo = team()
assert ct.ready_recipients(solo, "Orc-X") == "Orc-X"
assert ct.tier_recipient(solo) == "Orc-X"
full = team("Nagatha", "Kong", {"Backporter": {}, "Ext": {"role": "backporter", "external": True},
                                "Designer-X": {"role": "designer"}})
assert ct.ready_recipients(full, "Kong") == "Orc-X,Nagatha"
assert ct.base_recipients(full) == "Kong,Backporter", ct.base_recipients(full)
assert ct.base_recipients(team("Nagatha")) == "Orc-X"
print("ok")
