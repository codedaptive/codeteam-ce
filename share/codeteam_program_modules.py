"""The share/ modules a codeteam program loads (D558): a promote restarts a runner when any file it runs changed, and
the list of those files is read from the program's own import lines, not kept by hand (the hand-kept lists missed
codeteam_tm, D552's codeteam_finding_holds and D555's six build-queue modules)."""
import re
from pathlib import Path

IMPORT = re.compile(r"^[ \t]*(?:import|from)[ \t]+(codeteam_\w+)", re.M)


def program_modules(root: Path, program: str) -> set[str]:
    """program (a path under root, such as "bin/codeteam-land") and every share/codeteam_*.py it imports, directly or
    through another such module, as paths relative to root; a module it names that is not in share/ is left out. A
    program root does not have gives the empty set."""
    if not (root / program).is_file():
        return set()
    found, todo = {program}, [program]
    while todo:
        for name in IMPORT.findall((root / todo.pop()).read_text()):
            path = f"share/{name}.py"
            if path not in found and (root / path).is_file():
                found.add(path)
                todo.append(path)
    return found
