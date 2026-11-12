#!/bin/sh
# herdr runs this from the plugin's folder. The work is codeteam2's: `codeteam2 plugin <command>`.
# codeteam needs Python 3.11+ (tomllib); macOS's own python3 is older. CODETEAM_PYTHON picks one; else PATH's.
here=$(cd "$(dirname "$0")" && pwd)
for py in ${CODETEAM_PYTHON:-} python3 "$HOME/.local/bin/python3"; do
    command -v "$py" >/dev/null 2>&1 && exec "$py" "$here/../bin/codeteam2" plugin "$@"
done
echo "codeteam plugin: no python3 found" >&2
exit 1
