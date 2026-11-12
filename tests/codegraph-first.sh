#!/bin/bash
# codegraph-first.py: a code-symbol search by rg/grep is stopped once with the CodeGraph command; prose, docs,
# config, logs, pipes and marked commands pass.
H="$(cd "$(dirname "$0")/.." && pwd)/share/claude-hooks/codegraph-first.py"
unset CODETEAM_WORKSPACE   # the hook acts under the default workspace, ~/codeteam-work
W=/srv/codeteam-work/team-acme/workcrews/X/requests/agent-test
PASS=0; FAIL=0
run() { python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":sys.argv[2]}))' "$1" "$W" \
        | CODEGRAPH_FIRST_TEST=1 python3 "$H" >/dev/null 2>&1; echo $?; }
expect() { got=$(run "$2"); if [ "$got" = "$1" ]; then PASS=$((PASS+1)); echo "  PASS $3"; else FAIL=$((FAIL+1)); echo "  FAIL $3 (exit $got, wanted $1): $2"; fi; }
expect 2 'rg -n "EstateCatalog" packages/kits'                    "CamelCase symbol in code is stopped"
expect 2 'rg -nw resolve_argv0_dispatch apps/acme'               "snake_case symbol is stopped"
expect 2 'grep -rn "LocusKit::open" packages'                       "a::path is stopped"
expect 2 'rg "\bopenReader\(" -t rust'                              "word-bounded call is stopped"
expect 2 'cd packages/kits/AKit && rg -n Estate.open .'             "Type.member after cd is stopped"
expect 2 'rg -n "capturedAt|writeInstant|collectNow" packages/kits'   "an alternation of symbols is stopped"
expect 2 'grep -n "fn temp_sqlite_path" rust/src/lib.rs'             "a definition search is stopped"
expect 0 'rg -n "MigrationBenchmark|now and then" packages'           "an alternation with prose passes"
expect 0 'rg -n "EstateCatalog" docs/reference'                     "docs pass"
expect 0 'rg -n "EstateCatalog" CHANGELOG.md README.md'             ".md files pass"
expect 0 'rg -n "timeout" Cargo.toml'                               "config passes"
expect 0 'rg -n "failed to open" packages'                          "a phrase passes"
expect 0 'rg -n todo packages'                                      "a plain lowercase word passes"
expect 0 'git log --oneline | grep EstateCatalog'                   "grep on a pipe passes"
expect 0 'rg --files | rg Estate'                                   "file listing passes"
expect 0 'rg -l "EstateCatalog" packages # codegraph-checked: string in a macro' "the marker passes"
expect 0 'rg -n EstateCatalog -g "*.md"'                            "a .md glob passes"
expect 0 'rg -n EstateCatalog -t md'                           "--type md passes"
expect 0 'rg -n EstateCatalog /tmp/out.log'                         "a log passes"
expect 0 'codegraph grep EstateCatalog -p .'                        "codegraph itself passes"
expect 0 'make zone-test-one DIR=packages/kits/AKit'                "make passes"
out=$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":"rg -n EstateCatalog packages"},"cwd":"/tmp"}))' | python3 "$H" 2>&1; echo "exit=$?")
case "$out" in *exit=0*) PASS=$((PASS+1)); echo "  PASS outside the teams it does nothing";; *) FAIL=$((FAIL+1)); echo "  FAIL outside the teams: $out";; esac
out=$(python3 -c 'import json; print(json.dumps({"tool_name":"Bash","tool_input":{"command":"rg -n EstateCatalog packages"},"cwd":"/srv/codeteam-work/team-acme/workcrews/X","agent_type":"test-runner"}))' | CODEGRAPH_FIRST_TEST=1 python3 "$H" 2>&1; echo "exit=$?")
case "$out" in *exit=0*) PASS=$((PASS+1)); echo "  PASS test-runner (no CodeGraph tools) is never stopped";; *) FAIL=$((FAIL+1)); echo "  FAIL test-runner: $out";; esac
# A scratch git repo stands in for the worktree the command cd's into (removed on exit).
S="$(cd "$(mktemp -d)" && pwd -P)"; trap 'rm -rf "$S"' EXIT
R="$S/codeteam-work/codeteam"; mkdir -p "$R"; git -C "$R" init -q
out=$(python3 -c 'import json,sys; print(json.dumps({"tool_name":"Bash","tool_input":{"command":"cd "+sys.argv[1]+"; grep -rn \"func testEstateKeyService\" bin"},"cwd":"/srv/codeteam-work/team-acme"}))' "$R" | CODEGRAPH_FIRST_TEST=1 python3 "$H" 2>&1)
case "$out" in *"codegraph node testEstateKeyService -p $R "*) PASS=$((PASS+1)); echo "  PASS a definition search suggests the bare name, in the cd'd worktree";; *) FAIL=$((FAIL+1)); echo "  FAIL suggestion: $out";; esac
echo "== codegraph-first: $PASS passed, $FAIL failed"; [ $FAIL = 0 ]
