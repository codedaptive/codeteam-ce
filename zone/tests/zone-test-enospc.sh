#!/bin/bash
# zone-tool test out-of-space records in a scratch git repo.
# 1. Each case-varied ENOSPC signature with exit 1 is BROKEN, with its line in
#    the reason, a non-zero exit and the out-of-space summary.
# 2. BROKEN is not cached: a second run increments the external counter.
# 3. An ordinary FAIL is cached: the second run leaves the counter unchanged.
# 4. A signature before 200 filler lines is still detected.
# 5. HUNG takes precedence over an ENOSPC signature; its stderr marker is captured and checked.
#    Integration only (real clock).
# 6. Exit 0 takes precedence over an ENOSPC signature.
# 7. A signature after a 300-character prefix survives the reason's 200-character cap.
# 8. A signature after 300 'İ' (which lowercase to two code points each) and before
#    300 more characters stays in the reason.
# Failure messages mask the out-of-space phrases, so a failing check reads as FAIL,
# not as an out-of-space run, to the zone-tool run that runs this test.
set -u
# Stage 2 (v5.2) sets GROUP and CODETEAM_TEST_GROUP: children must not inherit them or their record keys change.
# export -n keeps the outer values available to this script without exporting them.
export -n GROUP CODETEAM_TEST_GROUP
here="$(cd "$(dirname "$0")/../.." && pwd)"
py=python3
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
repo="$tmp/repo"
mkdir -p "$repo"
git -C "$repo" init -q
printf 'scratch\n' > "$repo/file"
git -C "$repo" add file
git -C "$repo" -c user.name=test -c user.email=test@example.invalid commit -qm init
fail=0
ok()  { echo "ok   $1"; }
bad() { echo "FAIL $1: $(printf '%s' "$2" | sed 's/[Ss][Pp][Aa][Cc][Ee]/sp@ce/g; s/[Ff][Uu][Ll][Ll]/f@ll/g')"; fail=1; }

# Find a keyed record and check result and, when supplied, the matched line.
record_check() {
  "$py" -I -c '
import json, pathlib, sys
root, key, want, *line = sys.argv[1:]
for path in pathlib.Path(root).glob(".test-record-*.json"):
    rec = json.loads(path.read_text())
    if rec.get("key") == key:
        errors = []
        result = rec.get("result")
        if result != want:
            errors.append(f"record result {result!r}, want {want!r}")
        if line:
            reason = rec.get("reason", "")
            if not isinstance(reason, str) or not reason.startswith("out of space: ") or line[0] not in reason:
                errors.append(f"reason {reason!r}, want prefix out of space: and line {line[0]!r}")
        print("; ".join(errors))
        sys.exit(bool(errors))
print(f"record for {key!r} missing")
sys.exit(1)' "$repo" "$@"
}

# 1. Distinct keys isolate the three signatures from each other.
for item in 'device|NO SPACE LEFT ON DEVICE' 'database|Database Or Disk Is Full' 'space|Out Of Space'; do
  key="${item%%|*}"
  text="${item#*|}"
  out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
    "$here/bin/zone-tool" test --cached --key "$key" -- sh -c 'printf "%s\n" "$1"; exit 1' sh "$text")"
  rc=$?
  errors="$(record_check "$key" BROKEN "$text")"
  [ "$rc" -eq 1 ] || errors="$errors; exit $rc, want 1"
  case "$out" in *'zone-test: BROKEN (out of space)'*) ;; *) errors="$errors; stdout lacks zone-test: BROKEN (out of space)" ;; esac
  if [ -z "$errors" ]; then ok "1 $key signature"; else bad "1 $key signature" "$errors"; fi
done

# 2. The counter is outside the repo, so it cannot change the code hash.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key broken-rerun -- sh -c 'echo x >> "$1"; echo No space left on device; exit 1' sh "$tmp/broken-count")"
rc1=$?
count1="$(wc -l < "$tmp/broken-count" | tr -d ' ')"
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key broken-rerun -- sh -c 'echo x >> "$1"; echo No space left on device; exit 1' sh "$tmp/broken-count")"
rc2=$?
count2="$(wc -l < "$tmp/broken-count" | tr -d ' ')"
if [ "$rc1" -eq 1 ] && [ "$rc2" -eq 1 ] && [ "$count1" = 1 ] && [ "$count2" = 2 ] && [[ "$out" != *'already recorded'* ]]; then
  ok "2 BROKEN reruns"
else bad "2 BROKEN reruns" "exits $rc1/$rc2, counter $count1 -> $count2 (want 1 -> 2), stdout [$out]"; fi

# 3. Ordinary failure still answers from its record.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key plain-fail -- sh -c 'echo x >> "$1"; echo boom; exit 1' sh "$tmp/fail-count")"
rc1=$?
count1="$(wc -l < "$tmp/fail-count" | tr -d ' ')"
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key plain-fail -- sh -c 'echo x >> "$1"; echo boom; exit 1' sh "$tmp/fail-count")"
rc2=$?
count2="$(wc -l < "$tmp/fail-count" | tr -d ' ')"
errors="$(record_check plain-fail FAIL)"
if [ "$rc1" -eq 1 ] && [ "$rc2" -eq 1 ] && [ "$count1" = 1 ] && [ "$count2" = 1 ] && [[ "$out" == *'already recorded'* ]] && [ -z "$errors" ]; then
  ok "3 plain FAIL caches"
else bad "3 plain FAIL caches" "exits $rc1/$rc2, counter $count1 -> $count2, stdout [$out], $errors"; fi

# 4. Detection scans past what the record's tail retains.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key early-line -- sh -c 'echo No space left on device; i=0; while [ "$i" -lt 200 ]; do echo filler; i=$((i + 1)); done; exit 1')"
rc=$?
errors="$(record_check early-line BROKEN 'No space left on device')"
if [ "$rc" -eq 1 ] && [ -z "$errors" ]; then ok "4 early signature"; else bad "4 early signature" "exit $rc; $errors"; fi

# The hang window waits on a real clock: integration group.
# Run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/zone-test-enospc.sh.
if [ "${CODETEAM_TEST_GROUP:-unit}" = integration ]; then
# 5. A silent sleeping child exercises HUNG precedence over the already-printed signature.
# Capture stderr: codeteam-land would interpret the nested HUNG marker as this step hanging.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" CODETEAM_HANG_WINDOW=1 \
  "$here/bin/zone-tool" test --cached --key hung -- sh -c 'echo No space left on device; sleep 30' 2>&1)"
rc=$?
errors="$(record_check hung HUNG)"
printf '%s\n' "$out" | grep -q '^zone-test: HUNG: ' || errors="$errors; captured output lacks HUNG marker"
if [ "$rc" -ne 0 ] && [ -z "$errors" ]; then ok "5 HUNG wins over an out-of-space signature"; else bad "5 HUNG wins over an out-of-space signature" "exit $rc; $errors"; fi
else
  echo "skip 5 HUNG wins over an out-of-space signature: integration group only; run with CODETEAM_TEST_GROUP=integration make zone-test-one DIR=zone/tests/zone-test-enospc.sh"
fi

# 6. Success is not an out-of-space failure.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key success -- sh -c 'echo out of space; exit 0')"
rc=$?
errors="$(record_check success PASS)"
if [ "$rc" -eq 0 ] && [ -z "$errors" ]; then ok "6 exit 0 wins"; else bad "6 exit 0 wins" "exit $rc; $errors"; fi

# 7. Keep the matched text when the line's prefix alone exceeds the cap.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key long-line -- sh -c 'printf "%0300d" 0; printf "No space left on device\n"; exit 1')"
rc=$?
if errors="$("$py" -I -c '
import json, pathlib, sys
rec = next(rec for path in pathlib.Path(sys.argv[1]).glob(".test-record-*.json")
           if (rec := json.loads(path.read_text())).get("key") == "long-line")
assert rec["result"] == "BROKEN", rec
reason = rec["reason"]
assert reason.startswith("out of space: "), reason
assert "No space left on device" in reason, reason
assert len(reason) <= 200 + len("out of space: "), reason
' "$repo" 2>&1)" && [ "$rc" -eq 1 ]; then
  ok "7 long-line signature"
else bad "7 long-line signature" "exit $rc; $errors"; fi

# 8. Offsets come from the original line, not its lowercased form, which is longer here.
out="$(cd "$repo" && env -i PATH=/opt/homebrew/bin:/usr/bin:/bin HOME="$tmp" \
  "$here/bin/zone-tool" test --cached --key dotted-i -- "$py" -I -c '
import sys
sys.stdout.buffer.write(b"\xc4\xb0" * 300 + b"No space left on device" + b"x" * 300 + b"\n")
sys.exit(1)')"
rc=$?
errors="$(record_check dotted-i BROKEN 'No space left on device')"
if [ "$rc" -eq 1 ] && [ -z "$errors" ]; then ok "8 dotted-i signature"; else bad "8 dotted-i signature" "exit $rc; $errors"; fi

exit "$fail"
