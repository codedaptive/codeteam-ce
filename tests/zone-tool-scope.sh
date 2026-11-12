#!/bin/bash
# zone-tool test --scope: a record stands until something the tests can touch changes.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd)
ZT="$HERE/bin/zone-tool"
PY=python3
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
export GIT_CEILING_DIRECTORIES="$W"
R="$W/repo"; mkdir -p "$R/pk/A/rust" "$R/pk/B" "$R/pk/C" "$R/pk/D" "$R/docs" "$R/scripts"
cd "$R" && git init -q
cat > pk/A/Package.swift <<'S'
let p = Package(dependencies: [.package(name: "B", path: "../B")], targets: [.target(name: "A", path: "Sources/A")])
S
cat > pk/A/rust/Cargo.toml <<'S'
[lib]
path = "src/lib.rs"
[dependencies]
d = { path = "../../D" }
S
echo a > pk/A/a.swift; echo b > pk/B/b.swift; echo c > pk/C/c.swift; echo d > pk/D/d.rs
echo doc > docs/x.md; echo top > README.md; echo run > scripts/run; echo m > Makefile
git add -A && git -c user.email=t@t -c user.name=t commit -qm init
export MARK="$W/mark"
fail=0
t() {  # label, want (ran|cached), scope-or-empty
  local label=$1 want=$2 sc=$3; : > "$MARK"
  if [ -n "$sc" ]; then "$PY" "$ZT" test --cached --key "k $sc" --scope "$sc" -- sh -c 'echo x >> "$MARK"' >/dev/null 2>&1
  else "$PY" "$ZT" test --cached --key "k whole" -- sh -c 'echo x >> "$MARK"' >/dev/null 2>&1; fi
  local got=cached; [ -s "$MARK" ] && got=ran
  if [ "$got" = "$want" ]; then echo "  PASS $label"; else echo "  FAIL $label: want $want, got $got"; fail=1; fi
}
t "first run runs" ran pk/A
t "same code: answered from the record" cached pk/A
echo c2 > pk/C/c.swift;           t "a package A does not depend on changed: not run again" cached pk/A
echo doc2 > docs/x.md;            t "a doc changed: not run again" cached pk/A
echo top2 > README.md;            t "a top-level .md changed: not run again" cached pk/A
echo new > pk/C/new.swift;        t "an untracked file elsewhere: not run again" cached pk/A
"$PY" "$ZT" covered >/dev/null 2>&1 && echo "  PASS covered reads the restamped record as current" || { echo "  FAIL covered after a restamp"; fail=1; }
echo b2 > pk/B/b.swift;           t "a Swift path dependency changed: runs" ran pk/A
# A Swift package's own rust/ port is the other port: Rust-only changes leave the Swift record.
echo d2 > pk/D/d.rs;              t "a dependency of the package's rust/ crate changed: Swift not run again" cached pk/A
echo r > pk/A/rust/lib.rs;        t "a file in the package's own rust/ port: Swift not run again" cached pk/A
t "the rust/ port's own record: first run" ran pk/A/rust
echo d3 > pk/D/d.rs;              t "the rust/ port's dependency changed: Rust runs" ran pk/A/rust
echo a2 > pk/A/a.swift;           t "the package itself changed: runs" ran pk/A
echo n > pk/A/new.swift;          t "an untracked file in the package: runs" ran pk/A
echo run2 > scripts/run;          t "the test runner (scripts) changed: runs" ran pk/A
echo m2 > Makefile;               t "a top-level build file changed: runs" ran pk/A
t "whole-worktree record: first run" ran ""
echo c3 > pk/C/c.swift;           t "whole-worktree record: any change runs (unchanged behaviour)" ran ""
mkdir -p nomanifest; echo z > nomanifest/z
t "no manifest: whole worktree (first)" ran nomanifest
echo c4 > pk/C/c.swift;           t "no manifest: any change runs" ran nomanifest
"$PY" "$ZT" test-status >/dev/null 2>&1; rc=$?; [ $rc -le 1 ] && echo "  PASS test-status runs ($rc)" || { echo "  FAIL test-status exit $rc"; fail=1; }
exit $fail
