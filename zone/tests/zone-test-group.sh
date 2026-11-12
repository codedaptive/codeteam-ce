#!/bin/bash
# Test group passthrough and record isolation without a queue or runner.
# 1. test-one passes CODETEAM_TEST_GROUP to a child, but drops CODETEAM_MANIFEST and HERDR_SESSION.
# 2. In a no-Makefile repo, unset and unit use "one pkg owns="; integration adds
#    " test-group=integration", separately from GROUP's " group=integration".
# 3. A unit PASS record cannot answer an integration key.
# 4. Key parsing excludes test-group words while preserving real filters.
# 5. Key group extraction returns sorted group words, or an empty tuple.
# 6. A retry guard accepts a later narrower PASS only when its groups match the FAIL.
set -u
unset MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES DIR MAKEFILES CODETEAM_ZONE CODETEAM_OWNS \
      ZONE ZONE_ROOT ZONE_TOOL ZONE_TEST ZONE_TEST_FLAGS CODETEAM_BUILDQ_TICKET CODETEAM_SLOT_HELD \
      CODETEAM_LANDING CODETEAM_TEST_GROUP GROUP ZONE_CHECK_CMD CLASS ZONE_MK_LOADED \
      SWIFT_TEST_ARGS CARGO_TEST_ARGS ZONE_TEST_ONE_CMD ZONE_TEST_ONE_FLAGS
here="$(cd "$(dirname "$0")/../.." && pwd)"
ZONE_MK="${ZONE_MK:-$here/zone/zone.mk}"
export CODETEAM_HOME="$here" PYTHONDONTWRITEBYTECODE=1
py=python3
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/stub"
printf '#!/bin/sh\nexit 0\n' > "$tmp/stub/tmutil"
chmod +x "$tmp/stub/tmutil"
export PATH="$tmp/stub:$PATH" GIT_CEILING_DIRECTORIES="$tmp" ZONE_CHECK=0
fail=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1: $2"; fail=1; }

A="$tmp/a"
mkdir -p "$A/envpkg/tests"
git -C "$A" init -q
printf '__pycache__/\n.pytest_cache/\n' > "$A/.gitignore"
cat > "$A/envpkg/tests/env.sh" <<'SH'
#!/bin/bash
printf 'group=%s\nmanifest=%s\nsession=%s\n' "${CODETEAM_TEST_GROUP-unset}" "${CODETEAM_MANIFEST-unset}" "${HERDR_SESSION-unset}"
SH
git -C "$A" add -A
git -C "$A" -c user.email=t@t -c user.name=t commit -qm init

out="$(cd "$A" && env CODETEAM_TEST_GROUP=integration CODETEAM_MANIFEST=secret HERDR_SESSION=secret "$here/bin/zone-tool" test-one envpkg 2>&1)"; rc=$?
if [ "$rc" -eq 0 ] && grep -qx 'group=integration' <<<"$out" && \
   grep -qx 'manifest=unset' <<<"$out" && grep -qx 'session=unset' <<<"$out"; then
  ok '1 child receives group and no manifest or session'
else
  bad '1 child receives group and no manifest or session' "exit $rc; output: $(tr '\n' '|' <<<"$out")"
fi

cat > "$tmp/stub/zone-tool" <<'SH'
#!/bin/bash
printf '%s\n' "$*" >> "$MARK"
while [ "$#" -gt 0 ]; do
  if [ "$1" = --key ]; then shift; printf '%s\n' "$1" >> "$KEY_MARK"; break; fi
  shift
done
SH
chmod +x "$tmp/stub/zone-tool"
run_key() {  # label, expected key, followed by env assignments
  local label=$1 expected=$2 out rc got; shift 2
  export MARK="$tmp/$label.args" KEY_MARK="$tmp/$label.key"
  out="$(env "$@" make -f "$ZONE_MK" --no-print-directory zone-test-one DIR=pkg \
    ZONE_TOOL="$tmp/stub/zone-tool" ZONE_ROOT="$A" ZONE=z 2>&1)"; rc=$?
  got="$(cat "$KEY_MARK" 2>/dev/null)"
  if [ "$rc" -eq 0 ] && [ "$got" = "$expected" ]; then ok "2 $label key"
  else bad "2 $label key" "exit $rc, got [$got], expected [$expected]; output: $out"; fi
}
run_key unset 'one pkg owns=' -u CODETEAM_TEST_GROUP -u GROUP
run_key unit 'one pkg owns=' -u GROUP CODETEAM_TEST_GROUP=unit
run_key integration 'one pkg owns= test-group=integration' -u GROUP CODETEAM_TEST_GROUP=integration
run_key both 'one pkg owns= group=integration test-group=integration' GROUP=integration CODETEAM_TEST_GROUP=integration

B="$tmp/guard"
mkdir -p "$B/pkg"
git -C "$B" init -q
printf 'scratch\n' > "$B/pkg/README"
git -C "$B" add -A
git -C "$B" -c user.email=t@t -c user.name=t commit -qm init
if "$py" -I - "$here/bin/zone-tool" "$B" <<'PY'
import importlib.machinery
import importlib.util
import json
import os
import pathlib
import sys

loader = importlib.machinery.SourceFileLoader('zone_tool', sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
tool = importlib.util.module_from_spec(spec)
loader.exec_module(tool)
root = pathlib.Path(sys.argv[2])
failed = False

def check(label, condition):
    global failed
    if condition:
        print('ok   ' + label)
    else:
        print('FAIL ' + label + ': assertion failed')
        failed = True

unit_key = 'one pkg owns='
integration_key = 'one pkg owns= test-group=integration'
check('3 unit and integration record paths differ', tool.record_path(root, unit_key) != tool.record_path(root, integration_key))
_, _, before, _, _ = tool.record_hit(root, unit_key, '', None)
tool.record_path(root, unit_key).write_text(json.dumps({'result': 'PASS', 'hash': before, 'salt': '', 'time': '2026-01-01T00:00:00', 'key': unit_key}))
check('3 unit PASS answers its own key', tool.record_hit(root, unit_key, '', None)[0] is not None)
check('3 unit PASS does not answer integration key', tool.record_hit(root, integration_key, '', None)[0] is None)

check('4 group metadata is not a filter', tool._key_parts('one pkg owns= test-group=integration') == ('one', 'pkg', []))
check('4 real filters survive group metadata', tool._key_parts('one pkg --filter x test-group=integration')[2] == ['--filter', 'x'])
groups = getattr(tool, '_key_groups', None)
check('5 sorted group words', groups is not None and groups('one pkg owns= group=integration test-group=integration') == ('group=integration', 'test-group=integration'))
check('5 no group words', groups is not None and groups('one pkg owns=') == ())
os.environ['ZONE_CHECK'] = '0'
os.environ.pop('CODETEAM_BUILDQ_TICKET', None)
os.environ.pop('CODETEAM_LANDING', None)
whole = 'one pkg owns='
other = 'one pkg/test_x.py owns= test-group=integration'
same = 'one pkg/test_x.py owns='
tool.record_path(root, whole).write_text(json.dumps({'key': whole, 'result': 'FAIL', 'time': '2026-01-01T00:00:00', 'tail': ['pkg/test_x.py']}))
tool.record_path(root, other).write_text(json.dumps({'key': other, 'result': 'PASS', 'time': '2026-01-02T00:00:00', 'tail': []}))
refusal = tool.guard_run(root, whole, 'test-hash', False)
check('6 different group PASS does not unlock retry', isinstance(refusal, str) and 'REFUSED' in refusal)
tool.record_path(root, other).unlink()
tool.record_path(root, same).write_text(json.dumps({'key': same, 'result': 'PASS', 'time': '2026-01-02T00:00:00', 'tail': []}))
check('6 same group PASS unlocks retry', tool.guard_run(root, whole, 'test-hash', False) is None)
sys.exit(1 if failed else 0)
PY
then :; else fail=1; fi
exit "$fail"
