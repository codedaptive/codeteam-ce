#!/bin/bash
# The zone-test-one record key carries PYTEST_ARGS and PYTEST_ADDOPTS; unset
# preserves the existing key byte for byte, and zone-tool receives it literally.
set -u
unset MAKEFILES MAKEFLAGS MFLAGS MAKELEVEL MAKEOVERRIDES DIR CODETEAM_OWNS GROUP \
  CODETEAM_TEST_GROUP SWIFT_TEST_ARGS CARGO_TEST_ARGS PYTEST_ARGS PYTEST_ADDOPTS CLASS
for name in ${!ZONE_@}; do unset "$name"; done
here="$(cd "$(dirname "$0")/../.." && pwd)"
zone_mk="$here/zone/zone.mk"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/repo" "$tmp/no-make"
git -C "$tmp/no-make" init -q
cat > "$tmp/repo/Makefile" <<MAKE
include $zone_mk
MAKE
cat > "$tmp/zone-tool" <<'STUB'
#!/bin/bash
while [ "$#" -gt 0 ]; do
  if [ "$1" = --key ]; then
    shift
    printf '[%s]\n' "$1" > "$KEY_MARK"
    exit 0
  fi
  shift
done
exit 1
STUB
chmod +x "$tmp/zone-tool"
fail=0
run_key() { # branch, label, expected (bracketed), environment assignment, make arguments
  local branch=$1 label=$2 expected=$3 assignment=$4 out rc got
  shift 4
  local makefile="$tmp/$branch/Makefile"
  if [ "$branch" = no-make ]; then makefile="$zone_mk"; fi
  out="$(env -i PATH="$PATH" HOME="$HOME" TMPDIR="${TMPDIR:-/tmp}" \
    KEY_MARK="$tmp/$label.key" ZONE_CHECK=0 "$assignment" \
    make -C "$tmp/$branch" -f "$makefile" --no-print-directory zone-test-one \
    DIR=pkg ZONE_TOOL="$tmp/zone-tool" ZONE_ROOT="$tmp/$branch" ZONE=z "$@" 2>&1)"; rc=$?
  got="$(cat "$tmp/$label.key" 2>/dev/null)"
  if [ "$rc" -eq 0 ] && [ "$got" = "$expected" ]; then
    echo "ok   $label"
  else
    echo "FAIL $label: exit $rc, got $got, expected $expected; output: $out"
    fail=1
  fi
}
run_key repo a-repo-unset '[one pkg  ]' UNUSED=1
run_key repo b-repo-empty '[one pkg  ]' UNUSED=1 PYTEST_ARGS=
run_key repo c-repo-pytest '[one pkg   pytest=-k foo]' UNUSED=1 'PYTEST_ARGS=-k foo'
run_key repo d-repo-addopts-env '[one pkg   pytest-addopts=-k bar]' 'PYTEST_ADDOPTS=-k bar'
run_key repo e-repo-both-group '[one pkg   pytest=-k foo pytest-addopts=-k bar group=integration]' UNUSED=1 'PYTEST_ARGS=-k foo' 'PYTEST_ADDOPTS=-k bar' GROUP=integration
run_key repo f-repo-cargo '[one pkg  x]' UNUSED=1 CARGO_TEST_ARGS=x
run_key no-make g-no-make-unset '[one pkg owns=]' UNUSED=1
run_key no-make h-no-make-pytest '[one pkg owns= pytest=-k foo]' UNUSED=1 'PYTEST_ARGS=-k foo'
run_key no-make i-no-make-whitespace '[one pkg owns= pytest=-k foo]' UNUSED=1 'PYTEST_ARGS=  -k   foo '
run_key no-make j-no-make-test-group '[one pkg owns= pytest=-k foo test-group=integration]' UNUSED=1 'PYTEST_ARGS=-k foo' CODETEAM_TEST_GROUP=integration
run_key no-make k-no-make-addopts-env '[one pkg owns= pytest-addopts=-k bar]' 'PYTEST_ADDOPTS=-k bar'
run_key no-make b2-no-make-empty '[one pkg owns=]' UNUSED=1 PYTEST_ARGS=
run_key repo p-repo-addopts-empty-env '[one pkg  ]' PYTEST_ADDOPTS=
run_key no-make q-no-make-addopts-empty-env '[one pkg owns=]' PYTEST_ADDOPTS=
run_key repo r-repo-whitespace-only '[one pkg  ]' UNUSED=1 'PYTEST_ARGS=   '
run_key no-make l-double-quotes '[one pkg owns= pytest=-k "a or b"]' UNUSED=1 'PYTEST_ARGS=-k "a or b"'
run_key no-make m-single-quote "[one pkg owns= pytest=-k it's]" UNUSED=1 "PYTEST_ARGS=-k it's"
run_key no-make n-backticks '[one pkg owns= pytest=-k `echo x`]' UNUSED=1 'PYTEST_ARGS=-k `echo x`'
for pair in 'a-repo-unset c-repo-pytest' 'g-no-make-unset h-no-make-pytest'; do
  set -- $pair
  if [ -f "$tmp/$1.key" ] && [ -f "$tmp/$2.key" ] && ! cmp -s "$tmp/$1.key" "$tmp/$2.key"; then
    echo "ok   o-$1-differs-from-$2"
  else
    echo "FAIL o-$1-differs-from-$2: keys missing or identical"
    fail=1
  fi
done
exit "$fail"
