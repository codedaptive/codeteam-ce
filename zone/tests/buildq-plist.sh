#!/bin/bash
# zone/tests/buildq-plist.sh: share/codeteam-buildq.plist, the launchd job template that keeps codeteam-buildq running,
# as share/install-buildq-plist.sh --print fills it in. Read only: the filled-in plist is written to a scratch folder
# and parsed with plutil; nothing is installed or loaded. HOME is a scratch path and the prefix and Python are pinned.
#  1. plutil -lint passes.
#  2. KeepAlive is true.
#  3. ProgramArguments: the interpreter and the runner are absolute paths, and the last argument is --standby.
#  4. WorkingDirectory is absent (launchd defaults to /).
#  5. No string value in the plist contains ~ (launchd does not expand it), and no __PLACEHOLDER__ is left.
#  6. Label is com.codeteam.codeteam-buildq (the default CODETEAM_LAUNCHD_PREFIX).
#  7. EnvironmentVariables.PATH is <HOME>/.cargo/bin:/opt/homebrew/bin:<HOME>/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin.
#  8. EnvironmentVariables.HOME is <HOME>.
#  9. ProcessType is Interactive.
set -u
here="$(cd "$(dirname "$0")/../.." && pwd)"
py=python3
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
fail=0
fakehome="$tmp/home"
plist="$tmp/codeteam-buildq.plist"
HOME="$fakehome" CODETEAM_LAUNCHD_PREFIX= CODETEAM_PYTHON=/usr/bin/python3 bash "$here/share/install-buildq-plist.sh" --print > "$plist"

cat > "$tmp/check.py" <<'PY'
import json
import sys

home = sys.argv[1]
try:
    d = json.load(sys.stdin)
except ValueError:
    d = {}


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


args = d.get("ProgramArguments") if isinstance(d.get("ProgramArguments"), list) else []
args = [a for a in args if isinstance(a, str)]
checks = [
    (2, "KeepAlive is true", d.get("KeepAlive") is True),
    (3, "ProgramArguments: absolute interpreter and runner, last argument --standby",
     len(args) >= 3 and args[0].startswith("/") and args[1].startswith("/") and args[-1] == "--standby"),
    (4, "WorkingDirectory is absent", "WorkingDirectory" not in d),
    (5, "no string value contains ~ or a placeholder",
     bool(d) and not any("~" in s or any(k in s for k in ("__PREFIX__", "__PYTHON__", "__CODETEAM_HOME__", "__HOME__"))
                       for s in strings(d))),
    (6, "Label is com.codeteam.codeteam-buildq", d.get("Label") == "com.codeteam.codeteam-buildq"),
    (7, "EnvironmentVariables.PATH matches", d.get("EnvironmentVariables", {}).get("PATH") ==
     f"{home}/.cargo/bin:/opt/homebrew/bin:{home}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"),
    (8, "EnvironmentVariables.HOME is the given HOME", d.get("EnvironmentVariables", {}).get("HOME") == home),
    (9, "ProcessType is Interactive", d.get("ProcessType") == "Interactive"),
]
bad = 0
for num, label, good in checks:
    print(("ok   %d %s" if good else "FAIL %d %s") % (num, label))
    bad += 0 if good else 1
sys.exit(1 if bad else 0)
PY

if plutil -lint "$plist" > "$tmp/lint" 2>&1; then
  echo "ok   1 plutil -lint passes"
else
  echo "FAIL 1 plutil -lint passes: $(cat "$tmp/lint")"
  fail=1
fi
plutil -convert json -o - "$plist" > "$tmp/plist.json" 2>/dev/null
"$py" -I "$tmp/check.py" "$fakehome" < "$tmp/plist.json" || fail=1
exit $fail
