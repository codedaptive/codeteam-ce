"""shell_test_kind: the kind of a shell test script, for zone-tool's selection of one kind by name (V55-25 item 1).

A script under a unit, integration or validation folder is that kind. An unnamed script that expands the group
variable ($CODETEAM_TEST_GROUP or $GROUP) decides its own group at run time, so it has no fixed kind (None). Any other unnamed script is a ZUT ("unit"). Naming the variable without
expanding it (export -n GROUP, env CODETEAM_TEST_GROUP=x) does not read it.
"""
import re
from pathlib import Path

from codeteam_folder_kind import folder_kind

# $NAME or ${NAME...}; \b keeps $GROUPS, $GROUP_ID and $CODETEAM_TEST_GROUPS out.
GROUP_EXPANSION = re.compile(r"\$\{?(?:CODETEAM_TEST_GROUP|GROUP)\b")


def shell_test_kind(path: Path, rel: str) -> str | None:
    """The folder kind of rel; else None when the script expands the group variable; else "unit"."""
    kind = folder_kind(rel)
    if kind:
        return kind
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return "unit"
    return None if GROUP_EXPANSION.search(text) else "unit"
