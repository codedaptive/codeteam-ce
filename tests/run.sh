#!/bin/bash
# codeteam test suite. Runs entirely under scratchpad/tests in the repo this script lives in.
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"
CT="$(cd "$(dirname "$0")/.." && pwd)/bin/codeteam"
T="$(cd "$(dirname "$0")/.." && pwd)/scratchpad/tests"
rm -rf "$T"; mkdir -p "$T"; cd "$T"
# Keep every git command inside the test folder: it lives in the codeteam repo,
# and a vanished worktree would otherwise let git walk up into codeteam itself.
export GIT_CEILING_DIRECTORIES="$T"
# Trust flags go to a test file, never to the real ~/.claude.json.
export CODETEAM_CLAUDE_JSON="$T/claude.json"; echo '{}' > "$CODETEAM_CLAUDE_JSON"
# Window groups come from a test file, never from codeteam's own windows.toml.
export CODETEAM_WINDOWS="$T/no-windows.toml"
# CodeGraph: init pins worktrees and teardown unregisters them. codegraph honours CODEGRAPH_STATE_DIR, so even the real
# CLI reads and writes this folder, never ~/.codegraph. CODETEAM_CODEGRAPH points codeteam at a stub that keeps a plain
# registry file here. A PATH stub would lose: bin/codeteam puts /opt/homebrew/bin first on PATH.
export CODEGRAPH_STATE_DIR="$T/codegraph-state" CODETEAM_CODEGRAPH="$T/codegraph-stub"
cat > "$CODETEAM_CODEGRAPH" <<'EOS'
#!/bin/bash
# codegraph stand-in: one absolute path per line in codegraph-registry, beside this script.
D=$(cd "$(dirname "$0")" && pwd)
REG="$D/codegraph-registry"
echo "$*" >> "$D/codegraph-calls"
case "$1 $2" in
  "project pin") grep -qxF -- "$3" "$REG" 2>/dev/null || echo "$3" >> "$REG" ;;
  "project remove") if [ -f "$REG" ]; then grep -vxF -- "$3" "$REG" > "$REG.tmp"; mv "$REG.tmp" "$REG"; fi ;;
  "project list")
    out=""
    if [ -f "$REG" ]; then while IFS= read -r p; do out="$out${out:+, }{\"root\": \"$p\"}"; done < "$REG"; fi
    echo "[$out]" ;;
esac
exit 0
EOS
chmod +x "$CODETEAM_CODEGRAPH"
reg_has() { grep -qxF -- "$1" "$T/codegraph-registry"; }
PASS=0; FAIL=0
ok()  { PASS=$((PASS+1)); echo "  PASS $1"; }
bad() { FAIL=$((FAIL+1)); echo "  FAIL $1"; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }
G() { git -c user.email=t@t -c user.name=t "$@"; }

# --- product repo: github (origin), a bare anchor cloned from it, and the
#     develop checkout in design/, named like the real one
git init -q --bare -b develop repos/github/acme-ee.git
git clone -q repos/github/acme-ee.git seed 2>/dev/null
( cd seed && git checkout -q -b develop && mkdir -p kits/AKit kits/BKit gauges \
  && echo a > kits/AKit/a && echo b > kits/BKit/b && echo h > gauges/h && echo s > README \
  && mkdir -p .claude && echo p > .claude/PROJECT.md \
  && G add -A && G commit -qm init && git push -q origin develop )
git clone -q --bare repos/github/acme-ee.git repos/acme-ee.git
R="$T/work/acme-team"
git -C repos/acme-ee.git worktree add -q "$R/design/acme-ee-develop" develop
D="$R/design/acme-ee-develop"
mkdir -p "$T/bp"; echo orders > "$T/bp/BACKPORTER.md"
GH0=$(git -C repos/github/acme-ee.git rev-parse develop)
fp() { { git -C repos/acme-ee.git worktree list --porcelain | grep -E '^(worktree|locked)'
         git -C repos/acme-ee.git config --list --local | sort; ls repos/acme-ee.git/hooks; } | shasum | cut -c1-12; }
BEFORE=$(fp)

cat > acme.toml <<EOT
product = "acme"
repo = "$D"
base = "develop"
worktree_root = "$R"
model = "claude-opus-5-5"
lane_permission_mode = "auto"
orc_permission_mode = "bypassPermissions"
builder = "Nagatha"
guard = "Kong"
links = ["lab"]
sleep_clean = "touch CLEANED"
leadership_profile = "Homebrew"
workcrew_profile = "Clear Dark"
[env]
DATA_DIR = "{root}/data"
[session_links]
benchmark-work = "{root}/data"
[[pins]]
name = "prodpin"
repo = "$T/repos/acme-ee.git"
ref = "develop"
[[lanes]]
glob = "kits/*"
[[lanes]]
name = "tooling"
path = "."
owns = ["README", "gauges"]
guide = "TOOLING.md"
[[lanes]]
path = "gauges"
role = "verifier"
job = "Benchmark harness"
[[assistants]]
name = "Designer-Test"
role = "designer"
tier = "design"
[[assistants]]
name = "Nagatha"
tier = "integration"
permission_mode = "bypassPermissions"
[[assistants]]
name = "Kong"
tier = "exchange"
[[assistants]]
name = "Perkins"
tier = "integration"
[[assistants]]
name = "Backporter"
home = "$T/bp"
external = true
links = ["lab"]
EOT

ls_() { ls "$1" | tr '\n' ' '; }
echo "== layout"
check "init" "$CT init acme.toml --all-lanes >/dev/null"
check "init pins the team's new standing worktrees in CodeGraph (the two tier checkouts and the lanes)" "reg_has $R/integration/acme-ee-develop-integration && reg_has $R/exchange/acme-ee-integration-exchange && reg_has $R/workcrews/AKit/acme-ee-exchange-AKit && reg_has $R/workcrews/BKit/acme-ee-exchange-BKit && reg_has $R/workcrews/tooling/acme-ee-exchange-tooling && reg_has $R/workcrews/gauges/acme-ee-exchange-gauges"
check "top level: design, integration, exchange, workcrews, team, the pin, the restart file" "[ \"\$(ls_ $R)\" = 'design exchange integration prodpin restart-orchestrator.command team workcrews ' ]"
check "design: the develop checkout (its own .claude kept) and the two sessions' records" "[ \"\$(ls_ $R/design)\" = 'Designer-Test Orc-Acme acme-ee-develop ' ]"
check "integration: its checkout, Nagatha and Perkins" "[ \"\$(ls_ $R/integration)\" = 'Nagatha Perkins acme-ee-develop-integration agent-memory ' ]"
check "exchange: its checkout and Kong" "[ \"\$(ls_ $R/exchange)\" = 'Kong acme-ee-integration-exchange agent-memory ' ]"
check "session records" "[ \"\$(ls_ $R/integration/Nagatha)\" = 'benchmark-work ledger scratchpad ' ]"
check "lane worktree name" "[ -d $R/workcrews/AKit/acme-ee-exchange-AKit ]"
check "lane ledger contents" "[ \"\$(ls_ $R/workcrews/AKit/ledger)\" = 'channel.log issues.md memory reports todo.md ' ]"
check "scratchpad excluded from Time Machine" "tmutil isexcluded $R/workcrews/AKit/scratchpad | grep -q Excluded"
check "team-links beside the team folder" "[ -f $T/work/team-links/acme--lab.log ]"
check "Backporter channel in team/" "[ -f $R/team/Backporter.log ]"
check "agent memory links into the ledger" "[ \"\$(readlink $R/workcrews/AKit/acme-ee-exchange-AKit/kits/AKit/.claude/agent-memory)\" = '$R/workcrews/AKit/ledger/memory' ]"
A() { git -C repos/acme-ee.git merge-base --is-ancestor "$1" "$2"; }
check "branch line: develop -> integration -> exchange -> lane" "A develop integration && A integration exchange && A exchange lane/AKit"
check "every checkout is on its tier's branch" "[ \"\$(git -C $R/integration/acme-ee-develop-integration branch --show-current)\" = integration ] && [ \"\$(git -C $R/exchange/acme-ee-integration-exchange branch --show-current)\" = exchange ]"
check "no detached checkouts anywhere" "! git -C repos/acme-ee.git worktree list --porcelain | grep -q '^detached'"
check "pin on its own branch, current link" "[ \"\$(git -C $R/prodpin/acme-ee-develop-pin branch --show-current)\" = pin/acme ] && [ \"\$(readlink $R/prodpin/current)\" = '$R/prodpin/acme-ee-develop-pin' ]"
check "integration and exchange backed up to origin" "git -C repos/github/acme-ee.git rev-parse -q --verify integration >/dev/null && git -C repos/github/acme-ee.git rev-parse -q --verify exchange >/dev/null"
check "session link in a lane folder" "[ \"\$(readlink $R/workcrews/AKit/benchmark-work)\" = '$R/data' ]"
check "status reports no detached checkouts" "! $CT status acme.toml | grep -q DETACHED"
echo "== launch and roles"
$CT launch acme.toml all --dry-run > launch.out
check "Backporter is not launched" "! grep -q Backporter launch.out"
check "leadership windows use the leadership profile" "grep -q 'Orc-Acme: would launch.*in Homebrew' launch.out && grep -q 'Kong: would launch.*in Homebrew' launch.out"
check "workcrew windows use the workcrew profile" "grep -q 'Coord-AKit: would launch.*in Clear Dark' launch.out"
check "restart file at the team root launches the orchestrator here" "[ -x $R/restart-orchestrator.command ] && grep -q 'launch .*acme.toml. orc --here' $R/restart-orchestrator.command"
check "lane session name" "grep -q 'Coord-AKit: would launch' launch.out"
check "orchestrator starts in the develop checkout" "grep -q \"^cd '$D'\" $R/team/launch/orc.sh"
check "designer starts in the develop checkout" "grep -q \"^cd '$D'\" $R/team/launch/Designer-Test.sh"
check "Kong starts in the exchange checkout" "grep -q \"^cd '$R/exchange/acme-ee-integration-exchange'\" $R/team/launch/Kong.sh"
check "Perkins starts in the integration checkout" "grep -q \"^cd '$R/integration/acme-ee-develop-integration'\" $R/team/launch/Perkins.sh"
check "staff records in their tier" "grep -q \"TMPDIR='$R/design/Orc-Acme/scratchpad/'\" $R/team/launch/orc.sh && grep -q \"TMPDIR='$R/integration/Perkins/scratchpad/'\" $R/team/launch/Perkins.sh"
check "TMPDIR points at the scratchpad" "grep -q \"TMPDIR='$R/workcrews/AKit/scratchpad/'\" $R/team/launch/AKit.sh"
check "session commits under its own name" "grep -q \"GIT_AUTHOR_NAME='Coord-AKit'\" $R/team/launch/AKit.sh && grep -q \"GIT_COMMITTER_NAME='Coord-AKit'\" $R/team/launch/AKit.sh"
check "own auto memory per session" "grep -q 'workcrews/AKit/ledger/memory/auto' $R/team/launch/AKit.sh && grep -q 'design/Designer-Test/ledger/memory/auto' $R/team/launch/Designer-Test.sh"
check "Claude Code temp in the scratchpad" "grep -q \"CLAUDE_CODE_TMPDIR='$R/workcrews/AKit/scratchpad'\" $R/team/launch/AKit.sh"
check "settings.local.json removed only from codeteam's .claude" "grep -q 'gitignore 2>/dev/null)\" = .\\*. ] && rm -f' $R/team/launch/orc.sh"
check "model passed" "grep -q -- \"--model claude-opus-5-5\" $R/team/launch/AKit.sh"
check "role lists feature worktrees" "grep -q 'acme-ee-AKit-<feature>' $R/team/roles/AKit.md && grep -q '## Housekeeping' $R/team/roles/AKit.md"
check "orchestrator role lists every checkout below" "grep -q 'acme-ee-integration-exchange' $R/team/roles/orc.md && grep -q 'Shared with Designer-Test' $R/team/roles/orc.md"
check "a whole-repo lane gets the agent links beside a tracked .claude file" "[ -L $R/workcrews/tooling/acme-ee-exchange-tooling/.claude/agent-memory ] && [ -f $R/workcrews/tooling/acme-ee-exchange-tooling/.claude/PROJECT.md ]"
check "a lane can own several paths" "grep -q 'These paths: .README., .gauges.' $R/team/roles/tooling.md && [ -d $R/workcrews/tooling/acme-ee-exchange-tooling ]"
check "no unrendered placeholders" "! grep -l '{{' $R/team/roles/*.md >/dev/null"
check "no detach anywhere in the roles" "! grep -qi 'detach' $R/team/roles/*.md"
check "Kong's spec authority names the designer" "grep -q 'from Owner, Designer-Test, Orc-Acme' $R/team/roles/Kong.md"
check "READY deciders named" "grep -q 'Orc-Acme, Nagatha, Kong all post READY' $R/team/roles/Kong.md"
check "PATH puts Homebrew first in sessions" "grep -q 'export PATH=\"/opt/homebrew/bin' $R/team/launch/AKit.sh"
check "assistants get the say command and [codeteam] delivery, no watcher" "grep -q 'say .*acme.toml Kong Kong <TYPE> <TO>' $R/team/roles/Kong.md && grep -q 'say .*acme.toml Backporter Backporter <TYPE> <TO>' $R/team/roles/Backporter.md && grep -q 'begin with .\[codeteam\]., delivered when your turn ends' $R/team/roles/Kong.md && grep -q 'begin with .\[codeteam\]., delivered when your turn ends' $R/team/roles/Backporter.md && grep -q 'Run no watcher' $R/team/roles/Kong.md && grep -q 'Run no watcher' $R/team/roles/Backporter.md"
check "Backporter ships develop" "grep -q 'You push .develop. to GitHub' $R/team/roles/Backporter.md"
check "roles re-renders a removed role file" "rm $R/team/roles/Kong.md && $CT roles acme.toml >/dev/null && [ -f $R/team/roles/Kong.md ]"
# --- claude relink: a render re-runs provision_claude for every session dir, quietly. The team's claude home gets its
#     skills after the session dirs were provisioned without them; a second render changes nothing and says nothing about links.
RLT="$R/integration/acme-ee-develop-integration $R/exchange/acme-ee-integration-exchange"
RLL="$R/workcrews/AKit/acme-ee-exchange-AKit/kits/AKit $R/workcrews/BKit/acme-ee-exchange-BKit/kits/BKit $R/workcrews/tooling/acme-ee-exchange-tooling $R/workcrews/gauges/acme-ee-exchange-gauges/gauges"
rl_none() { for d in "$@"; do { [ ! -e "$d/.claude/skills" ] && [ ! -L "$d/.claude/skills" ]; } || return 1; done; }
rl_linked() { for d in "$@"; do [ "$(readlink "$d/.claude/skills")" = "$R/team/claude/skills" ] || return 1; done; }
rl_snap() { for d in "$D" $RLT $RLL; do stat -f '%i %N %Y' "$d"/.claude/* "$d"/.claude/.gitignore 2>/dev/null; done | sort; }
check "relink precondition: no .claude/skills in the tier checkouts or the lane cwds yet" "rl_none $RLT $RLL"
mkdir -p $R/team/claude/skills
$CT roles acme.toml > $T/relink1.out 2>&1
check "relink: the integration and exchange checkouts get .claude/skills after one render" "rl_linked $RLT"
check "relink: every lane's cwd (AKit, BKit, tooling, gauges) gets .claude/skills after one render" "rl_linked $RLL"
check "relink: a render that links says so (claude links:)" "grep -q 'claude links:' $T/relink1.out"
check "relink: the base checkout's own .claude gets no skills and no .gitignore" "[ ! -e $D/.claude/skills ] && [ ! -L $D/.claude/skills ] && [ ! -e $D/.claude/.gitignore ]"
RL_A=$(rl_snap)
$CT roles acme.toml > $T/relink2.out 2>&1
RL_B=$(rl_snap)
check "relink: a second render changes no session's .claude entries" "[ -n \"\$RL_A\" ] && [ \"\$RL_A\" = \"\$RL_B\" ]"
check "relink: a render with nothing to link prints nothing about links, kept or warnings" "! grep -qi 'claude\|link\|kept\|warn' $T/relink2.out"
# own-home assistants: Broken's .claude is a dangling link (a warning, and the render goes on); Homer has an empty folder,
# Porter a real .claude of its own, Ghost no folder at all; Homer2 has a claude home linked by hand, as design/Designer-Codeteam
# is (agents a link to the team's claude agents, no .gitignore). Broken comes first, so Homer's links show the render went on.
mkdir -p $T/homer $T/porter/.claude/agents
mkdir -p $T/broken && ln -s $T/nowhere $T/broken/.claude
mkdir -p $R/team/claude/agents $T/homer2/.claude && ln -s $R/team/claude/agents $T/homer2/.claude/agents
{ cat acme.toml; cat <<EOT
[[assistants]]
name = "Broken"
home = "$T/broken"
[[assistants]]
name = "Homer"
home = "$T/homer"
[[assistants]]
name = "Porter"
home = "$T/porter"
[[assistants]]
name = "Ghost"
home = "$T/ghost"
[[assistants]]
name = "Homer2"
home = "$T/homer2"
EOT
} > relink.toml
check "relink: roles renders with five own-home assistants (exit 0)" "$CT roles relink.toml > $T/relink3.out 2>&1"
check "relink: Homer, an own-home assistant, gets .claude/skills and agent-memory in its ledger" "[ \"\$(readlink $T/homer/.claude/skills)\" = '$R/team/claude/skills' ] && [ \"\$(readlink $T/homer/.claude/agent-memory)\" = '$R/design/Homer/ledger/memory' ]"
check "relink: Porter's own .claude (a real agents folder, no .gitignore) is left alone" "[ -d $T/porter/.claude/agents ] && [ ! -L $T/porter/.claude/agents ] && [ ! -e $T/porter/.claude/skills ] && [ ! -L $T/porter/.claude/skills ] && [ ! -e $T/porter/.claude/.gitignore ]"
check "relink: Ghost's home does not exist, so it is skipped and not created" "[ ! -e $T/ghost ] && [ ! -L $T/ghost ] && [ ! -e $R/design/Ghost ]"
check "relink: Homer2, a hand-linked home, gets .claude/skills" "[ \"\$(readlink $T/homer2/.claude/skills)\" = '$R/team/claude/skills' ]"
check "relink: Homer2's .claude gets a .gitignore of *" "[ \"\$(cat $T/homer2/.claude/.gitignore)\" = '*' ]"
check "relink: Homer2's agents stays the link to the team's claude agents" "[ \"\$(readlink $T/homer2/.claude/agents)\" = '$R/team/claude/agents' ]"
check "relink: a home whose .claude cannot be linked is named in a warning (Broken)" "grep -i 'warn' $T/relink3.out | grep -qi 'broken'"
check "relink: roles writes no own-home assistant into team.json" "! grep -q 'Homer\|Porter\|Ghost\|Broken' $R/team/team.json"
rm -rf $R/design/Homer $R/design/Porter $R/design/Ghost $R/design/Homer2 $R/design/Broken $R/team/roles/Homer.md $R/team/roles/Porter.md $R/team/roles/Ghost.md $R/team/roles/Homer2.md $R/team/roles/Broken.md $T/homer $T/porter $T/homer2 $T/broken
$CT roles acme.toml >/dev/null

# --- model coordinator role, with and without branch flow v5
{ cat acme.toml; cat <<EOT
[[assistants]]
name = "Coord-Judge"
role = "model-coordinator"
tier = "design"
job = "Judge model: distinguish calibrated verdicts"
EOT
} > mc.toml
check "model-coordinator: roles renders the manifest" "$CT roles mc.toml >/dev/null"
check "model-coordinator: plain render has no unreplaced placeholders" "[ -f $R/team/roles/Coord-Judge.md ] && ! grep -qF '{{' $R/team/roles/Coord-Judge.md"
check "model-coordinator: the ledger is the Medium-term records folder" "grep -qF 'Your ledger is the folder labeled \"Medium-term records\" in \"Your folders\"' $R/team/roles/Coord-Judge.md && grep -qF '| Medium-term records: ' $R/team/roles/Coord-Judge.md"
check "model-coordinator: keeps status.md and plan.md in its ledger" "grep -qF 'Keep \`status.md\` (what is decided, what is running, what is next, what waits on the owner) and \`plan.md\` in that folder.' $R/team/roles/Coord-Judge.md"
check "model-coordinator: on start reads its job and ledger, creates what is missing, ends its turn" "grep -qxF 'Read your job and your ledger (\`status.md\`, \`plan.md\`); create either one that is missing, then end your turn.' $R/team/roles/Coord-Judge.md"
check "model-coordinator: names the designer" "grep -qF 'Designer-Test' $R/team/roles/Coord-Judge.md"
check "model-coordinator: names the orchestrator" "grep -qF 'Orc-Acme' $R/team/roles/Coord-Judge.md"
check "model-coordinator: carries the manifest job" "grep -qF 'Judge model: distinguish calibrated verdicts' $R/team/roles/Coord-Judge.md"
check "model-coordinator: never edits code, cuts work orders or starts host jobs" "grep -qF 'You never edit code, cut work orders or start host jobs.' $R/team/roles/Coord-Judge.md"
check "model-coordinator: never messages the owner; questions go through the designer" "grep -qF 'Questions for the owner go through Designer-Test. You never message the owner.' $R/team/roles/Coord-Judge.md"
check "model-coordinator: settles what the documents answer before asking" "grep -qF 'Settle what the documents answer first' $R/team/roles/Coord-Judge.md"
check "model-coordinator: requests to the orchestrator are complete" "grep -qF 'Requests to Orc-Acme are complete: what, inputs, done when' $R/team/roles/Coord-Judge.md"
check "model-coordinator: the designer sets the order when two models want one host" "grep -qF 'When two models want the same host, Designer-Test sets the order.' $R/team/roles/Coord-Judge.md"
rm -f $R/team/roles/Coord-Judge.md
check "model-coordinator: v5 render succeeds" "python3 -c \"import importlib.machinery as m, importlib.util as u; l=m.SourceFileLoader('ct','$CT'); s=u.spec_from_loader('ct',l); ct=u.module_from_spec(s); l.exec_module(ct); t=ct.Team('$T/mc.toml'); t.m['land']={'enabled': True}; ct.render_roles(t, ct.load_team(t))\" >/dev/null"
check "model-coordinator: v5 render has no unreplaced placeholders" "[ -f $R/team/roles/Coord-Judge.md ] && ! grep -qF '{{' $R/team/roles/Coord-Judge.md"
check "model-coordinator: v5 render uses the model-coordinator template" "grep -qxF '# codeteam model coordinator: Coord-Judge' $R/team/roles/Coord-Judge.md"
rm -rf $R/design/Coord-Judge $R/team/roles/Coord-Judge.md $T/mc.toml
$CT roles acme.toml >/dev/null
check "branch-audit lists branches outside the rule and does not delete them" "n=\$(git -C repos/acme-ee.git for-each-ref refs/heads | wc -l); $CT branch-audit acme.toml >/dev/null 2>&1; rc=\$?; [ \$rc -le 1 ] && [ \"\$n\" = \"\$(git -C repos/acme-ee.git for-each-ref refs/heads | wc -l)\" ]"

# --- landed branches go, here and on GitHub; unlanded work and other kinds stay (the branch rule)
B=repos/acme-ee.git
L0=$(git -C $B rev-parse lane/AKit); TR=$(git -C $B rev-parse 'lane/AKit^{tree}')
git -C $B branch worktree-agent-t1 $L0                                              # landed: tip in lane/AKit
git -C $B branch worktree-agent-t2 $(G -C $B commit-tree $TR -p $L0 -m 'lead work, not landed')
git -C $B branch worktree-agent-t3 $(G -C $B commit-tree $TR -p $L0 -m 'lead work, squashed')
git -C $B branch hand/made $L0                                                      # not a codeteam kind
# a unit squashed into its lane (same file contents, different commit) and one that was not
echo f9 > $T/ct-f9; F9=$(git -C $B hash-object -w $T/ct-f9)
T9=$( { printf '100644 blob %s\tf9\n' $F9; git -C $B ls-tree 'lane/AKit^{tree}'; } | git -C $B mktree)
git -C $B branch unit/AKit/f9 $(G -C $B commit-tree $T9 -p $L0 -m 'unit f9 work')
echo f8 > $T/ct-f8; F8=$(git -C $B hash-object -w $T/ct-f8)
T8=$( { printf '100644 blob %s\tf8\n' $F8; git -C $B ls-tree 'lane/AKit^{tree}'; } | git -C $B mktree)
git -C $B branch unit/AKit/f8 $(G -C $B commit-tree $T8 -p $L0 -m 'unit f8 work, never squashed')
git -C $B update-ref refs/heads/lane/AKit $(G -C $B commit-tree $T9 -p $L0 -m "$(printf 'squash of t3 and f9\n\nWorktree: agent-t3')")
git -C $B push -q origin worktree-agent-t1 worktree-agent-t2 hand/made 2>/dev/null
check "sweep-branches --dry-run deletes nothing" "$CT sweep-branches acme.toml --dry-run | grep -q '3 landed branches would be deleted' && git -C $B rev-parse -q --verify worktree-agent-t1 >/dev/null"
$CT sweep-branches acme.toml >/dev/null 2>&1
git -C $B update-ref refs/heads/lane/AKit $L0
check "a landed request branch goes here and on GitHub" "! git -C $B rev-parse -q --verify worktree-agent-t1 >/dev/null && ! git -C repos/github/acme-ee.git rev-parse -q --verify worktree-agent-t1 >/dev/null"
check "a squash-landed request branch goes (Worktree: trailer)" "! git -C $B rev-parse -q --verify worktree-agent-t3 >/dev/null"
check "unlanded work stays, here and on GitHub" "git -C $B rev-parse -q --verify worktree-agent-t2 >/dev/null && git -C repos/github/acme-ee.git rev-parse -q --verify worktree-agent-t2 >/dev/null"
check "a unit squashed into its lane goes (same contents)" "! git -C $B rev-parse -q --verify unit/AKit/f9 >/dev/null"
check "a unit never squashed stays" "git -C $B rev-parse -q --verify unit/AKit/f8 >/dev/null"
check "a branch codeteam did not make stays" "git -C $B rev-parse -q --verify hand/made >/dev/null && git -C repos/github/acme-ee.git rev-parse -q --verify hand/made >/dev/null"
git -C $B branch -D -q worktree-agent-t2 hand/made unit/AKit/f8; git -C $B push -q origin --delete worktree-agent-t2 hand/made 2>/dev/null

# --- accept and remove-worktree: the lane's accept and cleanup as pre-approved codeteam commands (2026-10-24)
AW=$R/workcrews/AKit/acme-ee-exchange-AKit
git -C $AW worktree add -q -b worktree-agent-acc1 $AW/.claude/worktrees/agent-acc1 HEAD 2>/dev/null
echo lead > $AW/.claude/worktrees/agent-acc1/acc1.txt; git -C $AW/.claude/worktrees/agent-acc1 add acc1.txt; G -C $AW/.claude/worktrees/agent-acc1 commit -q -m 'lead work'
check "remove-worktree refuses work not on the lane" "! $CT remove-worktree acme.toml AKit worktree-agent-acc1 >/dev/null 2>&1 && git -C $B rev-parse -q --verify worktree-agent-acc1 >/dev/null"
check "accept squashes and commits with Request and Worktree trailers" "$CT accept acme.toml AKit worktree-agent-acc1 -f acc-one -m 'acc one' | grep -q 'accepted worktree-agent-acc1' && git -C $AW log -1 --format=%B | grep -q '^Request: acc-one' && git -C $AW log -1 --format=%B | grep -q '^Worktree: agent-acc1' && [ -f $AW/acc1.txt ]"
check "accept twice: nothing to accept" "! $CT accept acme.toml AKit worktree-agent-acc1 -f acc-one -m again >/dev/null 2>&1"
check "remove-worktree removes a landed worktree and its branch" "$CT remove-worktree acme.toml AKit worktree-agent-acc1 >/dev/null && [ ! -d $AW/.claude/worktrees/agent-acc1 ] && ! git -C $B rev-parse -q --verify worktree-agent-acc1 >/dev/null"
check "remove-worktree touches only worktree-* branches" "! $CT remove-worktree acme.toml AKit lane/AKit >/dev/null 2>&1"
check "zone roles name accept and remove-worktree, and both are filled in" "grep -q '{{accept}}' $(dirname "$CT")/../roles/zone.md && grep -q '{{remove_worktree}}' $(dirname "$CT")/../roles/zone.md && grep -q '\"accept\": t.cmd(\"accept\")' $CT && grep -q '\"remove_worktree\": t.cmd(\"remove-worktree\")' $CT"
git -C $AW reset -q --hard $L0 2>/dev/null; git -C $B update-ref refs/heads/lane/AKit $L0

# --- a session whose last turn ended on an API error is found (and a later prompt clears it)
cat > $T/apierr.jsonl <<'EOJ'
{"type":"user","message":{"content":"go"},"timestamp":"2026-10-24T13:20:00Z"}
{"type":"assistant","isApiErrorMessage":true,"error":"rate_limit","timestamp":"2026-10-24T13:24:12Z","message":{"model":"<synthetic>"}}
{"type":"system","subtype":"turn_duration","timestamp":"2026-10-24T13:24:13Z"}
EOJ
APIF="import importlib.machinery as m, importlib.util as u; l=m.SourceFileLoader('ct','$CT'); s=u.spec_from_loader('ct',l); ct=u.module_from_spec(s); l.exec_module(ct)"
check "an API-error stall is found" "python3 -c \"$APIF; r=ct.api_error_stall('$T/apierr.jsonl'); assert r and r[0]=='rate_limit'\""
echo '{"type":"user","message":{"content":"resume"},"timestamp":"2026-10-24T13:40:00Z"}' >> $T/apierr.jsonl
check "a later prompt clears the stall" "python3 -c \"$APIF; assert ct.api_error_stall('$T/apierr.jsonl') is None\""
# git's PATH gets /opt/homebrew/bin ahead of /usr/local/bin, and neither directory is added twice. This Mac
# has no /usr/local/bin, so gitpath() stubs Path to say every directory exists and sets PATH to its argument. Each exact
# result also has each directory once, and Homebrew ahead of /usr/local/bin unless the caller put /usr/local/bin first.
gitpath() { python3 -c "$APIF; import os, sys; ct.Path=lambda d: type('P',(),{'is_dir':lambda s:True})(); os.environ['PATH']=sys.argv[1]; print(ct._git_env()['PATH'])" "$1"; }
check "git's PATH, neither directory on it: Homebrew, then /usr/local/bin, go first as one block" "[ \"\$(gitpath /usr/bin:/bin)\" = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin' ]"
check "git's PATH, Homebrew already on it: /usr/local/bin goes right after it and Homebrew stays where it is" "[ \"\$(gitpath /usr/bin:/opt/homebrew/bin:/bin)\" = '/usr/bin:/opt/homebrew/bin:/usr/local/bin:/bin' ]"
check "git's PATH, /usr/local/bin already on it: Homebrew goes ahead of it and /usr/local/bin does not move" "[ \"\$(gitpath /usr/local/bin:/usr/bin)\" = '/opt/homebrew/bin:/usr/local/bin:/usr/bin' ]"
check "git's PATH, both on it in Homebrew-first order: unchanged" "[ \"\$(gitpath /opt/homebrew/bin:/usr/local/bin:/usr/bin)\" = '/opt/homebrew/bin:/usr/local/bin:/usr/bin' ]"
check "git's PATH, both on it in /usr/local/bin-first order: unchanged, a directory already on PATH never moves" "[ \"\$(gitpath /usr/local/bin:/opt/homebrew/bin:/usr/bin)\" = '/usr/local/bin:/opt/homebrew/bin:/usr/bin' ]"
check "git's PATH on the real disk: Homebrew first, and /usr/local/bin after it if it exists" "python3 -c \"$APIF; import os; os.environ['PATH']='/usr/bin:/bin'; want='/opt/homebrew/bin:/usr/local/bin:' if os.path.isdir('/usr/local/bin') else '/opt/homebrew/bin:'; assert ct._git_env()['PATH'].startswith(want)\""

# --- lane cap: at the cap, the done lane quiet longest makes room; first come, first served
cp $R/team/registry.json reg.save 2>/dev/null || echo '{}' > reg.save
sleep 600 & SP=$!
OLD=$(( $(date +%s) - 7200 ))
msg() { mkdir -p $R/workcrews/$1/ledger/inbox; echo "{\"to\": \"$1\", \"from\": \"t\", \"text\": \"go\"}" > $R/workcrews/$1/ledger/inbox/m-$1.json; touch -t $2 $R/workcrews/$1/ledger/inbox/m-$1.json; }
python3 -c "import json,sys; json.dump({'AKit': {'state': 'awake', 'pid': $SP, 'launched_at': $OLD}, 'BKit': {'state': 'asleep'}, 'tooling': {'state': 'asleep'}}, open('$R/team/registry.json','w'))"
msg BKit 202601010000; msg tooling 202501010000
echo 1 > $R/team/max-awake-lanes
CAP=$($CT wake acme.toml --plan)
check "lane cap: a done lane is swapped out for the one waiting longest" "echo \"\$CAP\" | head -1 | grep -q 'swap: sleep AKit .*wake tooling'"
msg AKit 202601010000
CAP2=$($CT wake acme.toml --plan)
check "lane cap: a lane with unread mail is never swapped out" "echo \"\$CAP2\" | grep -q 'wait tooling: cap 1 full' && ! echo \"\$CAP2\" | grep -q swap"
rm -f $R/team/max-awake-lanes $R/workcrews/*/ledger/inbox/m-*.json
kill $SP 2>/dev/null; wait $SP 2>/dev/null
cp reg.save $R/team/registry.json

# --- patrol: a past-queued row whose worktree is "-" takes its age from its work order's mtime.
#     An order under a day old: active (never dead, never parked). An order a day or more old, or no order: parked.
PLW=$R/workcrews/AKit/acme-ee-exchange-AKit
PLD=$R/workcrews/AKit/ledger
cat > $PLW/.ledger.md <<'EOL'
fresh-req · lead · -
old-req · lead · -
noorder-req · lead · -
EOL
mkdir -p $PLD/orders
echo '# fresh-req' > $PLD/orders/fresh-req.md
echo '# old-req' > $PLD/orders/old-req.md
touch -t $(date -v-2d +%Y%m%d%H%M) $PLD/orders/old-req.md
check "patrol: a past-queued row with no worktree and a fresh order is active, not parked" "python3 -c \"$APIF; import time; t=ct.Team('$T/acme.toml'); team=ct.load_team(t); rows,active,dead,parked,queued=ct.lane_work(t,'AKit',team['lanes']['AKit'],time.time()); assert active==['fresh-req'] and dead==[] and parked==2, 'active=%r dead=%r parked=%r queued=%r rows=%r' % (active,dead,parked,queued,rows)\""
PO=$($CT patrol acme.toml --dry-run)
check "patrol: only rows whose order is a day old, or missing, are flagged parked" "echo \"\$PO\" | grep -qF 'AKit: 2 ledger row(s) past queued'"
rm -f $PLW/.ledger.md $PLD/orders/fresh-req.md $PLD/orders/old-req.md
rmdir $PLD/orders

# --- patrol: a non-queued row with an awaited feature as a stage token is not active, dead or parked.
#     Its lead worktree is untouched 2 h (dead on its own); an await on another feature, or none, leaves it dead.
echo 'wait-req · waiting f9 · agent-wtest' > $PLW/.ledger.md
mkdir -p $R/workcrews/AKit/requests/agent-wtest
touch -t $(date -v-2H +%Y%m%d%H%M) $R/workcrews/AKit/requests/agent-wtest/.git
AWF=$PLD/awaits.txt
[ -e $AWF ] && cp $AWF $T/awaits.save
LW="python3 -c \"$APIF; import time; t=ct.Team('$T/acme.toml'); team=ct.load_team(t); rows,active,dead,parked,queued=ct.lane_work(t,'AKit',team['lanes']['AKit'],time.time())"
echo f9 > $AWF
check "patrol: a row waiting on an awaited feature is not active, dead or parked" "$LW; assert active==[] and dead==[] and parked==0 and queued==[], 'active=%r dead=%r parked=%r queued=%r rows=%r' % (active,dead,parked,queued,rows)\""
PW=$($CT patrol acme.toml --dry-run)
check "patrol: a row waiting on an awaited feature is never a DEAD LEAD" "! echo \"\$PW\" | grep -qF 'DEAD LEAD on wait-req'"
echo f8 > $AWF
check "patrol: an await on another feature leaves the row dead" "$LW; assert dead==['wait-req'], 'active=%r dead=%r parked=%r queued=%r' % (active,dead,parked,queued)\""
: > $AWF
check "patrol: an await cleared by push-up leaves the row dead" "$LW; assert dead==['wait-req'], 'active=%r dead=%r parked=%r queued=%r' % (active,dead,parked,queued)\""
rm -f $PLW/.ledger.md $R/workcrews/AKit/requests/agent-wtest/.git $AWF
rmdir $R/workcrews/AKit/requests/agent-wtest
[ -e $T/awaits.save ] && mv $T/awaits.save $AWF

# --- patrol reads the v5 zone-folder ledger and the v1 worktree ledger; feature lookup reads the v5 ledger.
cat > $R/workcrews/AKit/.ledger.md <<'EOL'
v5-req · lead · agent-v5x
EOL
echo 'v1-req · lead · -' > $PLW/.ledger.md
check "patrol ledger: v5 lane_work reads the zone folder" "python3 -c \"$APIF; import time; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': True}; team=ct.load_team(t); rows,*_=ct.lane_work(t,'AKit',team['lanes']['AKit'],time.time()); assert ['v5-req','lead','agent-v5x'] in rows, rows\""
check "patrol ledger: v5 feature lookup reads the zone folder" "python3 -c \"$APIF; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': True}; team=ct.load_team(t); rows=ct._ledger_rows_for(t,team,'v5-req'); assert ('AKit',['agent-v5x']) in rows, rows\""
check "patrol ledger: helper selects v5 zone and v1 worktree" "python3 -c \"$APIF; t=ct.Team('$T/acme.toml'); rec=ct.load_team(t)['lanes']['AKit']; t.m['land']={'enabled': True}; assert ct.lane_ledger_dir(t,'AKit',rec)==t.lane_dir('AKit'); t.m['land']={'enabled': False}; assert ct.lane_ledger_dir(t,'AKit',rec)==ct.lane_wt(t,'AKit',rec)\""
check "patrol ledger: v1 lane_work reads only the worktree" "python3 -c \"$APIF; import time; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': False}; team=ct.load_team(t); rows,*_=ct.lane_work(t,'AKit',team['lanes']['AKit'],time.time()); assert rows==[['v1-req','lead','-']], rows\""
check "patrol ledger: v5 lane with a ref uses its worktree" "python3 -c \"$APIF; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': True}; team=ct.load_team(t); rec=dict(team['lanes']['AKit']); rec['ref']='x'; assert ct.lane_ledger_dir(t,'AKit',rec)==ct.lane_wt(t,'AKit',rec)\""
printf 'v5-closed · agent-v5c · done\njunk\n' > $R/workcrews/AKit/.ledger-closed
printf 'v1-junk\n' > $PLW/.ledger-closed
check "patrol ledger: v5 feature lookup reads closed rows in the zone folder" "python3 -c \"$APIF; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': True}; team=ct.load_team(t); rows=ct._ledger_rows_for(t,team,'v5-closed'); assert ('AKit',['agent-v5c']) in rows, rows\""
check "patrol ledger: v5 closed sweep rewrites the zone ledger and leaves the v1 ledger untouched" "python3 -c \"$APIF; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': True}; team=ct.load_team(t); ct.sweep_closed_requests(t,team,False,'AKit',[(t.exchange,t.exchange),(t.integration,t.integration),(t.base,t.base)]); assert (t.lane_dir('AKit')/'.ledger-closed').read_text()=='v5-closed · agent-v5c · done\\n'; assert (ct.lane_wt(t,'AKit',team['lanes']['AKit'])/'.ledger-closed').read_text()=='v1-junk\\n'\""
echo 'v5-sweep · lead · agent-v5s' >> $R/workcrews/AKit/.ledger.md
git -C $PLW worktree add -q -b worktree-agent-v5s $PLW/.claude/worktrees/agent-v5s HEAD
check "patrol ledger: v5 sweep reports a zone-ledger worktree to its lane" "python3 -c \"$APIF; import contextlib,io,types; t=ct.Team('$T/acme.toml'); t.m['land']={'enabled': True}; out=io.StringIO(); exec('with contextlib.redirect_stdout(out):\\n ct.cmd_sweep(t,types.SimpleNamespace(dry_run=True))'); assert 'AKit: would report agent-v5s' in out.getvalue(), out.getvalue()\""
git -C $PLW worktree remove -f $PLW/.claude/worktrees/agent-v5s
git -C $PLW branch -D worktree-agent-v5s
rm -f $R/workcrews/AKit/.ledger.md $PLW/.ledger.md $R/workcrews/AKit/.ledger-closed $PLW/.ledger-closed

echo "== features"
UA=$($CT unit acme.toml AKit f1 2>/dev/null)
check "unit makes a feature worktree off the lane" "[ \"$UA\" = '$R/workcrews/AKit/acme-ee-AKit-f1' ] && [ \"\$(git -C $UA branch --show-current)\" = unit/AKit/f1 ]"
UB=$($CT unit acme.toml BKit f2 2>/dev/null)
( cd $UA && echo a2 >> kits/AKit/a && G commit -qam "A work" )
( cd $UB && echo b2 >> kits/BKit/b && G commit -qam "B work" )
check "squash worker -> lane names the feature" "$CT squash acme.toml AKit f1 -m 'AKit f1' >/dev/null && git -C repos/acme-ee.git log -1 --format=%B lane/AKit | grep -q 'Feature: f1'"
check "push-up needs a feature" "! $CT push-up acme.toml AKit -m x >/dev/null 2>&1"
check "push-up lane -> exchange" "$CT push-up acme.toml AKit -f f1 -m 'AKit f1' >/dev/null && git -C repos/acme-ee.git log -1 --format=%B exchange | grep -q 'Feature: f1'"
check "Kong's checkout moved with the push" "[ \"\$(git -C $R/exchange/acme-ee-integration-exchange rev-parse HEAD)\" = \"\$(git -C repos/acme-ee.git rev-parse exchange)\" ]"
check "Kong asked to review" "grep -q 'REQUEST Kong' $R/exchange/Kong/ledger/channel.log"
check "push announced on General" "grep -q 'AKit pushed feature f1' $R/team/general.log"
check "lane and exchange backed up" "[ \"\$(git -C repos/github/acme-ee.git rev-parse exchange)\" = \"\$(git -C repos/acme-ee.git rev-parse exchange)\" ] && git -C repos/github/acme-ee.git rev-parse -q --verify lane/AKit >/dev/null"
check "squash onto BKit" "$CT squash acme.toml BKit f2 -m 'BKit f2' >/dev/null"
check "stale push-up refused" "! $CT push-up acme.toml BKit -f f2 -m x >/dev/null 2>&1"
check "waiting lane pulls down then pushes" "$CT pull-down acme.toml BKit >/dev/null && $CT pull-down acme.toml BKit -f f2 >/dev/null && $CT push-up acme.toml BKit -f f2 -m 'BKit f2' >/dev/null"
check "integrate refused without READY" "! $CT integrate acme.toml -m 'f1 f2' f1 f2 >/dev/null 2>&1"
check "READY only from the deciders" "! $CT ready acme.toml Perkins integrate f1 f2 >/dev/null 2>&1"
for w in orc Nagatha; do $CT ready acme.toml $w integrate f1 f2 >/dev/null; done
check "integrate refused with two of three READY" "! $CT integrate acme.toml -m 'f1 f2' f1 f2 >/dev/null 2>&1"
$CT ready acme.toml Kong integrate f2 f1 >/dev/null
check "integrate squashes the set onto integration" "$CT integrate acme.toml -m 'Set one' f1 f2 >/dev/null && [ \"\$(git -C repos/acme-ee.git rev-list --count develop..integration)\" = 1 ] && git -C repos/acme-ee.git log -1 --format=%B integration | grep -q 'Features: f1, f2'"
check "exchange still descends from integration" "A integration exchange"
check "integration backed up" "[ \"\$(git -C repos/github/acme-ee.git rev-parse integration)\" = \"\$(git -C repos/acme-ee.git rev-parse integration)\" ]"
# push-up already retired the landed unit worktree (accepted on exchange); retire itself still needs approval.
check "retire refused before approval" "! $CT retire acme.toml AKit f1 >/dev/null 2>&1"
check "approve marks the feature approved" "$CT approve acme.toml f1 >/dev/null && python3 -c \"import json,sys;sys.exit(0 if json.load(open('$R/team/team.json'))['features']['f1'].get('approved') else 1)\""
check "retire removes the feature worktree and branch" "$CT retire acme.toml AKit f1 >/dev/null && [ ! -d $UA ] && [ -z \"\$(git -C repos/acme-ee.git branch --list unit/AKit/f1)\" ]"
check "promote refused without READY" "! $CT promote acme.toml -m 'Ship' >/dev/null 2>&1"
for w in orc Nagatha Kong; do $CT ready acme.toml $w promote f1 f2 >/dev/null; done
check "promote squashes integration onto develop in its checkout" "$CT promote acme.toml -m 'Ship' >/dev/null && [ \"\$(git -C $D log -1 --format=%s)\" = Ship ] && [ -z \"\$(git -C $D status --porcelain --untracked-files=no)\" ]"
check "the line is intact after promote" "A develop integration && A integration exchange"
check "promote leaves develop for the Backporter to push" "[ \"\$(git -C repos/github/acme-ee.git rev-parse develop)\" = '$GH0' ]"
check "promote tells the external assistant directly" "grep -q 'PUSHED Backporter | develop moved to' $R/team/Backporter.log"
check "promotion announced in general.log to the guard" "grep -q '| Nagatha | PUSHED Kong | develop' $R/team/general.log"
U3=$($CT unit acme.toml AKit f3 2>/dev/null)
$CT pull-down acme.toml AKit >/dev/null; $CT pull-down acme.toml AKit -f f3 >/dev/null
( cd $U3 && echo a3 >> kits/AKit/a && G commit -qam "A3" )
$CT await acme.toml BKit f3 >/dev/null
$CT squash acme.toml AKit f3 -m f3 >/dev/null; $CT push-up acme.toml AKit -f f3 -m f3 >/dev/null
check "push-up tells a lane that awaits the feature" "grep -q 'NOTE Coord-BKit | feature f3 is on exchange' $R/workcrews/BKit/ledger/channel.log && [ -z \"\$(cat $R/workcrews/BKit/ledger/awaits.txt)\" ]"
for w in orc Nagatha Kong; do $CT ready acme.toml $w integrate f3 >/dev/null; done
I0=$(git -C repos/acme-ee.git rev-parse integration)
$CT integrate acme.toml -m f3 f3 >/dev/null
check "discard undoes the last integrate" "$CT discard acme.toml >/dev/null && [ \"\$(git -C repos/acme-ee.git rev-parse integration)\" = \"$I0\" ]"
# codeteam's own posts name the sessions that act on them, never all.
GL=$R/team/general.log
check "a lane's PUSHED goes to the orchestrator" "grep -q '| Coord-AKit | PUSHED Orc-Acme | AKit pushed feature f1' $GL"
check "READY goes to the other deciders" "grep -q '| Orc-Acme | READY Nagatha,Kong | integrate f1,f2' $GL && grep -q '| Nagatha | READY Orc-Acme,Kong | integrate f1,f2' $GL && grep -q '| Kong | READY Orc-Acme,Nagatha | integrate f1,f2' $GL"
check "integration PUSHED goes to the guard" "grep -q '| Nagatha | PUSHED Kong | integration' $GL"
check "the discard NOTE goes to the guard" "grep -q '| Nagatha | NOTE Kong | integration discarded' $GL"
check "nothing codeteam posts names all" "! grep -q '| [A-Z]* all |' $GL"
check "the designer is not told of moves up" "! grep -rlE 'pushed feature|READY|discarded|develop [0-9a-f]{10} features' $R/design/Designer-Test/ledger/inbox >/dev/null 2>&1"
check "sole decider, no guard and a managed backporter" "[ \"\$(python3 $(dirname "$CT")/../tests/r2_recipients.py)\" = ok ]"
X=$R/exchange/acme-ee-integration-exchange
( cd $X && echo d4 >> kits/AKit/a && G commit -qam "docs: direct edit (feature f4)" )
check "register records commits that name their feature" "$CT register acme.toml | grep -q 'registered .* f4' && python3 -c \"import json,sys;f=json.load(open('$R/team/team.json'))['features']['f4'];sys.exit(len(f['exchange'])!=1)\""
check "register is idempotent" "$CT register acme.toml | grep -q 'nothing to register'"
check "register refuses a commit not on exchange" "! $CT register acme.toml -f f5 \$(git -C repos/acme-ee.git rev-parse develop) >/dev/null 2>&1"
check "team.json writers wait for the team lock" "python3 -c \"import fcntl,time;f=open('$R/team/team.lock','a');fcntl.flock(f,fcntl.LOCK_EX);time.sleep(2)\" & sleep 0.5; s=\$(date +%s); $CT register acme.toml >/dev/null; [ \$((\$(date +%s)-s)) -ge 1 ]"
check "snapshot on its own branch inside the lane folder" "[ \"\$($CT snapshot acme.toml gauges develop --name run1 2>/dev/null)\" = '$R/workcrews/gauges/acme-ee-develop-run1' ] && [ \"\$(git -C $R/workcrews/gauges/acme-ee-develop-run1 branch --show-current)\" = snap/gauges/run1 ]"
check "drop" "$CT drop acme.toml gauges run1 >/dev/null && [ ! -d $R/workcrews/gauges/acme-ee-develop-run1 ] && [ -z \"\$(git -C repos/acme-ee.git branch --list snap/gauges/run1)\" ]"
check "env expands {root}" "grep -q \"DATA_DIR='$R/data'\" $R/team/launch/AKit.sh"
check "repin moves the pin branch to the new tip" "$CT repin acme.toml prodpin >/dev/null && [ \"\$(git -C $R/prodpin/acme-ee-develop-pin rev-parse HEAD)\" = \"\$(git -C repos/acme-ee.git rev-parse develop)\" ] && [ \"\$(git -C $R/prodpin/acme-ee-develop-pin branch --show-current)\" = pin/acme ]"
check "repin to another ref swaps folder and link" "$CT repin acme.toml prodpin --ref exchange >/dev/null && [ -d $R/prodpin/acme-ee-exchange-pin ] && [ ! -d $R/prodpin/acme-ee-develop-pin ] && [ \"\$(readlink $R/prodpin/current)\" = '$R/prodpin/acme-ee-exchange-pin' ]"
check "still no detached checkouts" "! git -C repos/acme-ee.git worktree list --porcelain | grep -q '^detached'"

echo "== watch"
# Earlier steps left messages (approvals, review requests); read them first.
for x in AKit Kong orc Backporter; do $CT watch acme.toml $x --now >/dev/null; done
( sleep 4; $CT say acme.toml AKit Orc-Acme REQUEST AKit "please do the thing" >/dev/null ) &
W=$($CT watch acme.toml AKit --timeout 30)
check "watch wakes on a message addressed to the lane" "echo \"$W\" | grep -q 'please do the thing'"
check "a read message is filed under inbox/read" "ls $R/workcrews/AKit/ledger/inbox/read/*.json >/dev/null 2>&1 && [ -z \"\$(ls $R/workcrews/AKit/ledger/inbox/*.json 2>/dev/null)\" ]"
$CT say acme.toml AKit AKit NOTE Orc-Acme "my own line" >/dev/null
W2=$($CT watch acme.toml AKit --timeout 5)
check "the sender gets no copy of its own message" "echo \"$W2\" | grep -q 'nothing for you'"
check "the orchestrator gets the lane's message" "grep -l 'my own line' $R/design/Orc-Acme/ledger/inbox/*.json >/dev/null"
$CT say acme.toml general Orc-Acme NOTE all "news for everyone" >/dev/null
W3=$($CT watch acme.toml AKit --timeout 5)
check "a General message for all does not reach a lane" "echo \"$W3\" | grep -q 'nothing for you' && ! grep -rl 'news for everyone' $R/workcrews/AKit/ledger/inbox >/dev/null"
( sleep 3; $CT say acme.toml general Orc-Acme REQUEST Coord-AKit "your turn" >/dev/null ) &
W4=$($CT watch acme.toml AKit --timeout 20)
check "a General message addressed to the lane wakes it" "echo \"$W4\" | grep -q 'your turn'"
( sleep 3; $CT say acme.toml general Coord-BKit PUSHED all "BKit pushed feature f9 to exchange" >/dev/null ) &
W5=$($CT watch acme.toml AKit --also 'feature f9' --timeout 20)
check "--also wakes a waiting lane on the feature it waits for" "echo \"$W5\" | grep -q 'feature f9'"
WK2=$($CT watch acme.toml Kong --timeout 5)
check "General chatter waits in Kong's inbox without waking it" "echo \"$WK2\" | grep -q 'nothing for you' && grep -l 'lane chatter\|news for everyone' $R/exchange/Kong/ledger/inbox/*.json >/dev/null"
( sleep 3; $CT say acme.toml Kong Orc-Acme REQUEST Kong "look" >/dev/null ) &
WK=$($CT watch acme.toml Kong --timeout 20)
check "Kong wakes for its request and leaves it for --now" "echo \"$WK\" | grep -q look && echo \"$WK\" | grep -q 'left unread'"
WKN=$($CT watch acme.toml Kong --now)
check "--now files Kong's request and never prints the broadcasts" "! echo \"$WKN\" | grep -q 'news for everyone' && grep -l '\"look\"' $R/exchange/Kong/ledger/inbox/read/*.json >/dev/null"
check "Kong's inbox lives in its records in exchange/" "ls $R/exchange/Kong/ledger/inbox/read/*.json >/dev/null 2>&1"
$CT watch acme.toml orc --now >/dev/null
$CT say acme.toml AKit AKit STATUS all "lane chatter" >/dev/null
WO=$($CT watch acme.toml orc --timeout 5)
check "lane chatter waits for the orchestrator without waking it" "echo \"$WO\" | grep -q 'nothing for you'"
WN=$($CT watch acme.toml orc --now)
check "--now files chatter not addressed to the session without printing it" "echo \"$WN\" | grep -q 'nothing for you' && ! echo \"$WN\" | grep -q 'lane chatter'"
$CT say acme.toml link:lab Orc-Acme NOTE Orc-Lab "across teams" >/dev/null 2>&1 || true
( cd $R/workcrews/AKit/acme-ee-exchange-AKit && $CT pull-down $T/acme.toml AKit >/dev/null 2>&1; echo guide > kits/AKit/AGENTS.md && G add -A && G commit -qm "guide" )
check "link-guides adds CLAUDE.md as the lane" "$CT link-guides acme.toml >/dev/null && [ -L $R/workcrews/AKit/acme-ee-exchange-AKit/kits/AKit/CLAUDE.md ] && [ \"\$(git -C $R/workcrews/AKit/acme-ee-exchange-AKit log -1 --format=%an)\" = Coord-AKit ]"
( sleep 3; $CT say acme.toml general Orc-Acme PUSHED Backporter "develop abc123 promoted" >/dev/null ) &
WB=$($CT watch acme.toml Backporter --timeout 20)
check "external assistant wakes on a General message addressed to it; its inbox stays out of its home" "echo \"$WB\" | grep -q 'promoted' && ls $R/team/inboxes/Backporter/read/*.json >/dev/null 2>&1 && [ ! -e $T/bp/ledger ]"
echo "== sleep"
SID=$(python3 -c "import json;print(json.load(open('$R/team/sessions.json'))['AKit']['id'])")
# The stand-in session runs where a launch would start it: sleep checks the pid's cwd.
cd $R/workcrews/AKit/acme-ee-exchange-AKit/kits/AKit; bash -c "exec -a 'claude --session-id $SID' sleep 120" & cd "$T"; sleep 1
# sleep stops only the pid the registry holds (no pattern kill); procreg records it as a launch does.
$CT procreg acme.toml AKit --parent $$ >/dev/null 2>&1
$CT watch acme.toml AKit --now >/dev/null
$CT say acme.toml AKit Orc-Acme REQUEST Coord-AKit "one more thing" >/dev/null
check "sleep refused while a message waits for the session" "! $CT sleep acme.toml AKit >/dev/null 2>&1 && pgrep -f $SID >/dev/null"
$CT watch acme.toml AKit --now >/dev/null
$CT sleep acme.toml AKit >/dev/null
check "sleep runs the clean command" "[ -f $R/workcrews/AKit/acme-ee-exchange-AKit/CLEANED ]"
check "sleep stops the session" "! pgrep -f $SID >/dev/null"
check "external assistant cannot be slept" "$CT sleep acme.toml Backporter 2>&1 | grep -q external"

git clone -q repos/acme-ee.git renamed-folder 2>/dev/null
check "repo name comes from origin, not the folder" "[ \"\$(python3 $(dirname "$CT")/../tests/name_of.py renamed-folder)\" = acme-ee ]"
echo "== lab"
git init -q --bare -b main repos/github/kgf-model-lab.git
git clone -q repos/github/kgf-model-lab.git labseed 2>/dev/null
( cd labseed && git checkout -q -b main && echo t > t && G add -A && G commit -qm i && git push -q origin main )
LR="$T/work/lab-team"
git clone -q repos/github/kgf-model-lab.git "$LR/design/kgf-model-lab-main"
mkdir -p data/p1; echo d > data/p1/x.jsonl
cat > lab.toml <<EOT
product = "lab"
mode = "lab"
repo = "$LR/design/kgf-model-lab-main"
base = "main"
worktree_root = "$LR"
links = ["acme", "Backporter"]
[[lanes]]
name = "training"
path = "."
[[lanes]]
name = "data"
path = "."
workdir = "$T/data/p1"
EOT
check "lab init" "$CT init lab.toml --all-lanes >/dev/null"
check "lab top level" "[ \"\$(ls_ $LR)\" = 'design restart-orchestrator.command team workcrews ' ]"
check "lab orchestrator records beside the clone" "[ -d $LR/design/Orc-Lab/ledger ]"
check "lab worktree name" "[ -d $LR/workcrews/training/kgf-model-lab-main-training ]"
UL=$($CT unit lab.toml training t1 2>/dev/null)
( cd $UL && echo x >> t && G commit -qam w )
check "lab push-up lands on main" "$CT squash lab.toml training t1 -m 'lab t1' >/dev/null && $CT push-up lab.toml training -f t1 -m 'lab push' >/dev/null && [ \"\$(git -C $LR/design/kgf-model-lab-main log -1 --format=%s main)\" = 'lab push' ]"
check "lab main left for its shipper" "[ \"\$(git -C repos/github/kgf-model-lab.git log -1 --format=%s main)\" = i ]"
check "Backporter has a channel to the lab" "[ -f $T/work/team-links/Backporter--lab.log ] && grep -q 'Backporter--lab.log' $R/team/roles/Backporter.md"
$CT say acme.toml link:lab Backporter NOTE Orc-Lab "from backporter" >/dev/null
$CT say lab.toml link:Backporter Orc-Lab ANSWER Backporter "from lab" >/dev/null
check "a link message lands in the other side's inbox" "grep -l 'from backporter' $T/work/lab-team/design/Orc-Lab/ledger/inbox/*.json >/dev/null && grep -l 'from lab' $R/team/inboxes/Backporter/*.json >/dev/null"
mkdir -p $R/workcrews/AKit/ledger/inbox/read; echo '{}' > $R/workcrews/AKit/ledger/inbox/read/old.json; touch -t 202601010000 $R/workcrews/AKit/ledger/inbox/read/old.json
check "rotate tars read messages older than a day" "$CT rotate acme.toml >/dev/null && [ ! -e $R/workcrews/AKit/ledger/inbox/read/old.json ] && tar tzf $R/workcrews/AKit/ledger/inbox/archive/read-*.tgz | grep -q old.json"
check "both sides post to the same Backporter channel" "grep -q 'from backporter' $T/work/team-links/Backporter--lab.log && grep -q 'from lab' $T/work/team-links/Backporter--lab.log"
check "data lane starts in its data folder" "$CT launch lab.toml data --dry-run >/dev/null && grep -q \"^cd '$T/data/p1'\" $LR/team/launch/data.sh"
check "lab orchestrator starts in the clone" "$CT launch lab.toml orc --dry-run >/dev/null && grep -q \"^cd '$LR/design/kgf-model-lab-main'\" $LR/team/launch/orc.sh"

echo "== tmux groups"
cat > $T/windows.toml <<EOT
[[window]]
name = "T-Lead"
profile = "Homebrew"
members = ["acme:orc", "acme:Kong"]
[[window]]
name = "T-Work"
profile = "Novel"
members = ["acme:lanes"]
EOT
printf '#!/bin/bash\nsleep 120\n' > $T/fakeclaude; chmod +x $T/fakeclaude
export CODETEAM_WINDOWS=$T/windows.toml CODETEAM_TMUX_SOCKET=codeteam-test-$$ CODETEAM_NO_TERMINAL=1 CODETEAM_CLAUDE_BIN=$T/fakeclaude
TM() { tmux -L codeteam-test-$$ "$@"; }
$CT launch acme.toml orc Kong BKit --dry-run > tmux.out
check "listed sessions go to their tmux group" "grep -q 'Orc-Acme: would launch.*in tmux T-Lead (Homebrew)' tmux.out && grep -q 'Coord-BKit: would launch.*in tmux T-Work (Novel)' tmux.out"
$CT launch acme.toml orc Kong BKit >/dev/null; sleep 2
check "leadership tabs share one tmux session" "[ \"\$(TM list-windows -t =T-Lead -F '#W' | sort | tr '\n' ' ')\" = 'Kong Orc-Acme ' ]"
check "lane tab in the workers session" "[ \"\$(TM list-windows -t =T-Work -F '#W' | tr '\n' ' ')\" = 'Coord-BKit ' ]"
KSID=$(python3 -c "import json;print(json.load(open('$R/team/sessions.json'))['Kong']['id'])")
check "the session runs inside its tab" "pgrep -f $KSID >/dev/null"
check "mouse selection copies to the clipboard" "TM list-keys -T copy-mode | grep -q 'MouseDragEnd1Pane.*pbcopy'"
$CT say acme.toml Kong Orc-Acme REQUEST Kong "nudge me" >/dev/null
# nudge is retired (typed lines landed in the user's own typing); sessions run no watcher; messages arrive as [codeteam] prompts when a turn ends.
check "nudge types nothing into a session's tab" "[ -z \"\$($CT nudge acme.toml)\" ] && sleep 1 && ! TM capture-pane -p -t =T-Lead:Kong | grep -q 'Messages waiting'"
check "nudge does not repeat for the same messages" "[ -z \"\$($CT nudge acme.toml)\" ]"
check "roles tell sessions to end their turn" "grep -q 'end your turn' $R/team/roles/AKit.md && grep -q 'end your turn' $R/team/roles/Kong.md && ! grep -q 'Start your watch' $R/team/roles/orc.md"
check "a running session is not launched twice" "$CT launch acme.toml Kong | grep -q 'already running'"
TM kill-server 2>/dev/null; export CODETEAM_WINDOWS=$T/no-windows.toml; unset CODETEAM_TMUX_SOCKET CODETEAM_NO_TERMINAL CODETEAM_CLAUDE_BIN

echo "== push needs a test record"
{ echo 'push_needs_record = true'; cat acme.toml; } > rec.toml
ZT="$(cd "$(dirname "$CT")" && pwd)/zone-tool"
$CT pull-down acme.toml AKit >/dev/null 2>&1
LW=$(git -C repos/acme-ee.git worktree list --porcelain | awk '/^worktree /{w=$2} /^branch refs\/heads\/lane\/AKit$/{print w}')
U9=$($CT unit acme.toml AKit f9 2>/dev/null)
( cd $U9 && echo a9 >> kits/AKit/a && G commit -qam "A f9" )
$CT squash acme.toml AKit f9 -m f9 >/dev/null
check "zone-tool covered: no record, not covered" "! (cd $LW && $ZT covered >/dev/null)"
check "push-up refused with no record for the tree" "! $CT push-up rec.toml AKit -f f9 -m f9 >/dev/null 2>&1 && $CT push-up rec.toml AKit -f f9 -m f9 2>&1 | grep -q 'no test record matches this exact code'"
(cd $LW && $ZT test --key 'one kits/AKit' -- false >/dev/null 2>&1)
check "push-up refused when a record on this tree failed" "$CT push-up rec.toml AKit -f f9 -m f9 2>&1 | grep -q 'one kits/AKit (FAIL)'"
(cd $LW && $ZT test --key 'one kits/AKit' -- true >/dev/null 2>&1)
check "push-up goes through on a PASS for exactly this tree" "$CT push-up rec.toml AKit -f f9 -m f9 >/dev/null 2>&1 && git -C repos/acme-ee.git log -1 --format=%B exchange | grep -q 'Feature: f9'"
U10=$($CT unit acme.toml AKit f10 2>/dev/null)
( cd $U10 && echo a10 >> kits/AKit/a && G commit -qam "A f10" )
$CT squash acme.toml AKit f10 -m f10 >/dev/null
check "the PASS for the old tree does not cover the new one" "! $CT push-up rec.toml AKit -f f10 -m f10 >/dev/null 2>&1"
check "--untested pushes and says why in the commit" "$CT push-up rec.toml AKit -f f10 -m f10 --untested 'docs only' >/dev/null 2>&1 && git -C repos/acme-ee.git log -1 --format=%B exchange | grep -q '^Untested: docs only'"
check "teams without push_needs_record are unchanged" "! grep -q push_needs_record acme.toml"
# The records (.json and .log) and sleep's CLEANED are not the lane's to push: the --picks test below commits with add -A,
# and push-up refuses paths outside the walls.
rm -f $LW/.test-record*.json $LW/.test-record*.log $LW/CLEANED

echo "== integrate --picks"
TJ=$R/team/team.json
fx() { python3 -c "import json,sys;r=json.load(open('$TJ'))['features']['$1'];print($2)"; }
for l in AKit BKit; do $CT pull-down acme.toml $l >/dev/null 2>&1; done
U=$($CT unit acme.toml AKit f11 2>/dev/null); ( cd $U && echo p1 > kits/AKit/p1 && G add -A && G commit -qm "A f11 one" )
$CT squash acme.toml AKit f11 -m f11a >/dev/null; $CT push-up acme.toml AKit -f f11 -m f11a >/dev/null
( cd $LW && echo p2 > kits/AKit/p2 && G add -A && G commit -qm "A f11 two" )
$CT push-up acme.toml AKit -f f11 -m f11b >/dev/null
$CT pull-down acme.toml BKit >/dev/null 2>&1
U=$($CT unit acme.toml BKit f12 2>/dev/null); ( cd $U && echo q > kits/BKit/q && G add -A && G commit -qm "B f12" )
$CT squash acme.toml BKit f12 -m f12 >/dev/null; $CT push-up acme.toml BKit -f f12 -m f12 >/dev/null
F11A=$(fx f11 "r['exchange'][0]"); F11B=$(fx f11 "r['exchange'][1]"); F12=$(fx f12 "r['exchange'][0]")
check "f11 has two exchange commits" "[ \"$(fx f11 "len(r['exchange'])")\" = 2 ]"
for w in orc Nagatha Kong; do $CT ready acme.toml $w integrate f11 f12 >/dev/null; done
printf '%s  # f11 one\n\n%s\n' "${F11A:0:10}" "$F12" > picks.txt
echo "$F11A" > stray.txt; echo "$GH0" >> stray.txt
check "a pick outside the named features is refused" "$CT integrate acme.toml -m x --picks stray.txt f11 f12 2>&1 | grep -q 'not commits of f11, f12'"
check "a named feature with no picks is refused" "printf '%s\n' $F12 > only12.txt && $CT integrate acme.toml -m x --picks only12.txt f11 f12 2>&1 | grep -q 'no picks for f11'"
I1=$(git -C repos/acme-ee.git rev-parse integration)
check "integrate --picks takes only the picks" "$CT integrate acme.toml -m 'Set P' --picks picks.txt f11 f12 >/dev/null && git -C repos/acme-ee.git show integration:kits/AKit/p1 >/dev/null 2>&1 && git -C repos/acme-ee.git show integration:kits/BKit/q >/dev/null 2>&1 && ! git -C repos/acme-ee.git show integration:kits/AKit/p2 >/dev/null 2>&1"
check "the commit names what it held back" "git -C repos/acme-ee.git log -1 --format=%B integration | grep -q '^Partly integrated: f11' && git -C repos/acme-ee.git log -1 --format=%B integration | grep -q 'A f11 two\|f11b'"
check "a fully taken feature moves to integration" "[ \"$(fx f12 "r['state']")\" = integration ]"
check "a partly taken feature stays on exchange with its taken commit recorded" "[ \"\$(fx f11 \"r['state']\")\" = lanes ] && [ \"\$(fx f11 \"r['integrated']\")\" = \"['$F11A']\" ]"
check "discard restores a partial integrate" "$CT discard acme.toml >/dev/null && [ \"\$(git -C repos/acme-ee.git rev-parse integration)\" = \"$I1\" ] && [ \"\$(fx f11 \"r.get('integrated')\")\" = None ] && [ \"\$(fx f12 \"r['state']\")\" = lanes ]"
for w in orc Nagatha Kong; do $CT ready acme.toml $w integrate f11 f12 >/dev/null; done
$CT integrate acme.toml -m 'Set P' --picks picks.txt f11 f12 >/dev/null
for w in orc Nagatha Kong; do $CT ready acme.toml $w integrate f11 >/dev/null; done
check "the next set takes only the held commit" "$CT integrate acme.toml -m 'Set Q' f11 >/dev/null && git -C repos/acme-ee.git show integration:kits/AKit/p2 >/dev/null 2>&1 && [ \"\$(git -C repos/acme-ee.git log -1 --format=%B integration | sed -n '/^Squashes:/,\$p' | grep -c .)\" = 2 ] && [ \"\$(fx f11 \"r['state']\")\" = integration ] && [ \"\$(fx f11 \"r.get('integrated')\")\" = None ]"
check "discard after completing keeps the earlier set's commit taken" "$CT discard acme.toml >/dev/null && [ \"\$(fx f11 \"r['state']\")\" = lanes ] && [ \"\$(fx f11 \"r['integrated']\")\" = \"['$F11A']\" ]"
rm -f picks.txt stray.txt only12.txt

echo "== push-up walls"
# wall_refused WORKTREE LANE FEATURE PRE-SHA LINE...: push-up must exit non-zero, print `push-up refused`, `Nothing was
# pushed` and each LINE as `  LINE` (a LINE starting with - must NOT be listed), move neither exchange nor the lane (the
# test's commit stays on the lane), and post nothing. The test's commit is then undone with reset --keep (never --hard).
# WALLX adds push-up arguments (--untested); WALLM is the manifest push-up is given (acme.toml unless a check sets it).
WALLX=""
WALLM=acme.toml
wall_refused() {
  local wt=$1 lane=$2 f=$3 pre=$4 c x0 l good=1
  shift 4
  c=$(git -C "$wt" rev-parse HEAD); x0=$(git -C repos/acme-ee.git rev-parse exchange)
  $CT push-up "$WALLM" "$lane" -f "$f" -m "$f" $WALLX >"$T/wall.out" 2>&1 && good=0
  grep -q 'push-up refused' "$T/wall.out" && grep -q 'Nothing was pushed' "$T/wall.out" || good=0
  [ "$(git -C repos/acme-ee.git rev-parse exchange)" = "$x0" ] && [ "$(git -C "$wt" rev-parse HEAD)" = "$c" ] || good=0
  grep -q "pushed feature $f to" "$R/team/general.log" && good=0
  for l in "$@"; do
    case $l in
      -*) grep -q "^  ${l#-}:" "$T/wall.out" && good=0 ;;
      *) grep -qFx -- "  $l" "$T/wall.out" || good=0 ;;
    esac
  done
  git -C "$wt" reset -q --keep "$pre"
  [ $good = 1 ]
}
# The walls are the lane's: push-up refuses what the guard let through, and passes the zone's own work.
$CT pull-down acme.toml AKit >/dev/null 2>&1
( cd $LW && echo ga > kits/AKit/ga && G add kits/AKit/ga && G commit -qm 'A adds ga' )
check "push-up goes up for an in-zone change (new file under kits/AKit)" "$CT push-up acme.toml AKit -f wa -m 'A ga' >/dev/null 2>&1 && git -C repos/acme-ee.git show exchange:kits/AKit/ga >/dev/null 2>&1"
$CT pull-down acme.toml AKit >/dev/null 2>&1
( cd $LW && mkdir -p docs/reference && echo spec > docs/reference/AKIT_SPEC.md && G add docs/reference/AKIT_SPEC.md && G commit -qm 'A reference doc' )
check "push-up goes up for the zone's own reference doc (docs/reference/AKIT_SPEC.md)" "$CT push-up acme.toml AKit -f wb -m 'A spec' >/dev/null 2>&1 && git -C repos/acme-ee.git show exchange:docs/reference/AKIT_SPEC.md >/dev/null 2>&1"
# 1. an out-of-zone file
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
( cd $LW && echo z > kits/BKit/z && G add kits/BKit/z && G commit -qm 'A adds BKit/z' )
check "push-up refuses an out-of-zone file (kits/BKit/z names BKit)" "wall_refused $LW AKit wr1 $P 'kits/BKit/z: BKit'"
# 2. a mixed-case path: recorded exactly through the index; APFS folds case on disk, so the file lands as kits/AKit/x
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
BLOB=$(echo x | git -C $LW hash-object -w --stdin)
git -C $LW update-index --add --cacheinfo 100644,$BLOB,kits/akit/x
echo x > $LW/kits/akit/x
G -C $LW commit -qm 'A adds kits/akit/x'
check "the commit records the path exactly (kits/akit/x)" "git -C $LW ls-tree -r --name-only HEAD | grep -qFx kits/akit/x"
check "push-up refuses a mixed-case path (kits/akit/x names AKit, its own zone)" "wall_refused $LW AKit wr2 $P 'kits/akit/x: AKit'"
# 3. a rename out of the zone: the new name is BKit's, the old name is AKit's and not listed
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
( cd $LW && G mv kits/AKit/ga kits/BKit/ga && G commit -qm 'A moves ga out of its zone' )
check "push-up refuses a rename out of the zone (kits/BKit/ga names BKit; the old name is not listed)" "wall_refused $LW AKit wr3 $P 'kits/BKit/ga: BKit' '-kits/AKit/ga'"
# 3b. a rename into the zone: the old name is BKit's and is counted
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
( cd $LW && G mv kits/BKit/b kits/AKit/b2 && G commit -qm 'A moves BKit/b into its zone' )
check "push-up refuses a rename into the zone (the old name kits/BKit/b names BKit; the new name is not listed)" "wall_refused $LW AKit wr3b $P 'kits/BKit/b: BKit' '-kits/AKit/b2'"
# 4. a deletion out of the zone
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
( cd $LW && G rm -q kits/BKit/q && G commit -qm 'A deletes BKit/q' )
check "push-up refuses a deletion out of the zone (kits/BKit/q names BKit)" "wall_refused $LW AKit wr4 $P 'kits/BKit/q: BKit'"
# 5. a path no lane owns: the orchestrator
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
( cd $LW && mkdir -p notes && echo x > notes/x && G add notes/x && G commit -qm 'A adds notes/x' )
check "push-up refuses a path no lane owns (notes/x names the orchestrator)" "wall_refused $LW AKit wr5 $P 'notes/x: orchestrator (Orc-Acme)'"
# 6. --untested is not an override
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
( cd $LW && echo z > kits/BKit/z6 && G add kits/BKit/z6 && G commit -qm 'A adds BKit/z6' )
WALLX="--untested why"
check "--untested does not bypass the walls (kits/BKit/z6 names BKit)" "wall_refused $LW AKit wr6 $P 'kits/BKit/z6: BKit'"
WALLX=""
# 7. a walled whole-repo lane (tooling): a case-folded path of another lane's folder
$CT pull-down acme.toml tooling >/dev/null 2>&1
TLW=$R/workcrews/tooling/acme-ee-exchange-tooling; P=$(git -C $TLW rev-parse HEAD)
BLOB=$(echo x | git -C $TLW hash-object -w --stdin)
git -C $TLW update-index --add --cacheinfo 100644,$BLOB,Gauges/x
echo x > $TLW/Gauges/x
G -C $TLW commit -qm 'tooling adds Gauges/x'
check "the tooling commit records Gauges/x exactly" "git -C $TLW ls-tree -r --name-only HEAD | grep -qFx Gauges/x"
check "push-up refuses a walled lane's case-folded path (Gauges/x names gauges)" "wall_refused $TLW tooling wr7 $P 'Gauges/x: gauges'"
check "tooling's worktree tracks docs/ after its pull-down (the guard reads a folder only when git tracks it)" "git -C $TLW ls-files -- docs | grep -q ."
# 8. fail closed: push-up refuses and pushes nothing when lane_walls cannot be imported. The copy of bin/codeteam finds
# its hooks beside itself (TOOL_DIR is $FC, the folder above the copy's bin/), so the copy's share/claude-hooks is the one that is broken.
fc_commit() { ( cd $LW && echo fc > kits/AKit/fc && G add kits/AKit/fc && G commit -qm 'A adds fc' ); }
fc_case() { # NAME: the copy's push-up of the lane's fc commit must refuse, move neither exchange nor the lane, and post nothing
  local x0 h0 rc
  x0=$(git -C repos/acme-ee.git rev-parse exchange); h0=$(git -C $LW rev-parse HEAD)
  $FC/bin/codeteam push-up acme.toml AKit -f wfc -m wfc >$T/fc.out 2>&1; rc=$?
  check "$1: push-up exits non-zero when lane_walls cannot be imported" "[ $rc -ne 0 ]"
  check "$1: push-up says lane_walls unavailable and nothing was pushed" "grep -q 'lane_walls unavailable' $T/fc.out && grep -q 'nothing was pushed' $T/fc.out"
  check "$1: exchange did not move" "[ \"\$(git -C repos/acme-ee.git rev-parse exchange)\" = '$x0' ]"
  check "$1: the lane's commit stays where it was" "[ \"\$(git -C $LW rev-parse HEAD)\" = '$h0' ]"
  check "$1: no push announced on General" "! grep -q 'pushed feature wfc to' $R/team/general.log"
  git -C $LW reset -q --keep $P
}
$CT pull-down acme.toml AKit >/dev/null 2>&1; P=$(git -C $LW rev-parse HEAD)
FC=$T/ctcopy; rm -rf $FC; mkdir -p $FC/bin $FC/share/claude-hooks; cp -p $CT $FC/bin/codeteam
fc_commit; echo 'raise RuntimeError("broken for the test")' > $FC/share/claude-hooks/lane_walls.py
fc_case broken-lane_walls
fc_commit; rm -rf $FC/share/claude-hooks; mkdir -p $FC/share/claude-hooks
fc_case absent-lane_walls
rm -rf $FC
# 9. orchestrator_owns: a path the manifest's top-level key lists is refused for every lane, as the orchestrator's, and
# nothing moves. orc.toml is acme.toml with the key before its first table; acme.toml has no key.
{ echo 'orchestrator_owns = ["teams"]'; cat acme.toml; } > orc.toml
$CT pull-down acme.toml tooling >/dev/null 2>&1; P=$(git -C $TLW rev-parse HEAD)
( cd $TLW && mkdir -p teams && echo a > teams/x.toml && G add teams/x.toml && G commit -qm 'tooling adds teams/x.toml' )
WALLM=orc.toml
check "push-up refuses a path the manifest's orchestrator_owns lists (teams/x.toml names the orchestrator)" "wall_refused $TLW tooling wr8o $P 'teams/x.toml: orchestrator (Orc-Acme)'"
WALLM=acme.toml
# The same path goes up under the manifest without the key. The commit is made again with other content: if a run's
# push of "a" had reached exchange, the same content would leave nothing to commit.
$CT pull-down acme.toml tooling >/dev/null 2>&1; P=$(git -C $TLW rev-parse HEAD)
( cd $TLW && mkdir -p teams && echo b > teams/x.toml && G add teams/x.toml && G commit -qm 'tooling changes teams/x.toml' )
check "push-up via acme.toml (no orchestrator_owns) takes teams/x.toml up to exchange" "$CT push-up acme.toml tooling -f wr8m -m wr8m >/dev/null 2>&1 && [ \"\$(git -C repos/acme-ee.git show exchange:teams/x.toml)\" = b ]"
$CT pull-down acme.toml tooling >/dev/null 2>&1
check "tooling's worktree tracks teams/ after its pull-down (the guard reads a folder only when git tracks it)" "git -C $TLW ls-files -- teams | grep -qx teams/x.toml"
# TABLE: push-up's walls_refusals and zone-guard.py's pretool give one verdict per (lane, path), so the two rules cannot drift.
# A row may name a manifest (its 7th argument): both read that manifest's orchestrator_owns; without one, neither reads it.
# Left out on purpose: .claude/, .ledger.md, cargo-target*, .test-record-*.json, the lane's scratchpad and ledger, and any path
# whose top folder or file is untracked in its worktree (the guard alone calls those the lane's own; untracked_root_file).
# A case variant of a tracked top entry (Gauges/h beside the tracked gauges) is not untracked, so it has a row.
GUARD="$(cd "$(dirname "$CT")/.." && pwd)/share/claude-hooks/zone-guard.py"
WPY="import importlib.machinery as m, importlib.util as u, json, sys; l=m.SourceFileLoader('ct','$CT'); s=u.spec_from_loader('ct',l); ct=u.module_from_spec(s); l.exec_module(ct); tj='$R/team/team.json'; lanes=json.load(open(tj))['lanes']; kw={'manifest': sys.argv[3]} if len(sys.argv) > 3 else {}; print('refused' if ct.walls_refusals(tj, lanes, sys.argv[1], [sys.argv[2]], **kw) else 'allowed')"
push_verdict() { # LANE PATH [MANIFEST]: push-up's walls_refusals verdict; MANIFEST goes as manifest= only when given
  local a=("$1" "$2")
  [ -n "$3" ] && a+=("$3")
  python3 -c "$WPY" "${a[@]}" 2>/dev/null || echo error
}
guard_verdict() { # LANE ZONE OWNS SWT PATH [MANIFEST]: zone-guard.py's pretool verdict for an Edit of SWT/PATH, as its hook sees it
  (
    for v in $(compgen -e); do case "$v" in CODETEAM_*|CT_*) unset "$v";; esac; done
    export CODETEAM_ZONE="$2" CODETEAM_SESSION="$1" CODETEAM_SWT="$4" CODETEAM_HOME="$(cd "$(dirname "$CT")/.." && pwd)"
    if [ -n "$3" ]; then export CODETEAM_OWNS="$3"; fi
    if [ -n "$6" ]; then export CODETEAM_MANIFEST="$6"; fi
    echo "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$4/$5\"},\"cwd\":\"$4\"}" | python3 "$GUARD" pretool >/dev/null 2>&1
    case $? in 0) echo allowed ;; 2) echo refused ;; *) echo error ;; esac
  )
}
ROW() { # WANT LANE ZONE OWNS SWT PATH [MANIFEST]
  local pv gv tag=""
  pv=$(push_verdict "$2" "$6" "$7"); gv=$(guard_verdict "$2" "$3" "$4" "$5" "$6" "$7")
  [ -n "$7" ] && tag=" with manifest ${7##*/}"
  check "walls table: $2 $6 is $1$tag (push-up $pv, guard $gv)" "[ '$pv' = '$1' ] && [ '$gv' = '$1' ]"
}
ROW allowed AKit kits/AKit "" "$LW" kits/AKit/Sources/x.swift
ROW refused AKit kits/AKit "" "$LW" kits/BKit/Sources/x.swift
ROW refused AKit kits/AKit "" "$LW" kits/akit/x
ROW refused AKit kits/AKit "" "$LW" README
ROW refused AKit kits/AKit "" "$LW" gauges/h
ROW allowed AKit kits/AKit "" "$LW" docs/reference/AKIT_SPEC.md
ROW refused AKit kits/AKit "" "$LW" docs/reference/BKIT_SPEC.md
ROW allowed AKit kits/AKit "" "$LW" kits/BKit/Cargo.lock
ROW refused AKit kits/AKit "" "$LW" kits/CKit/q
ROW allowed tooling . "README:gauges" "$TLW" README
ROW refused tooling . "README:gauges" "$TLW" kits/AKit/a
ROW refused tooling . "README:gauges" "$TLW" kits/akit/x
ROW refused tooling . "README:gauges" "$TLW" gauges/h
ROW refused tooling . "README:gauges" "$TLW" Gauges/h
# a reference doc named for another lane is that lane's, even for a walled lane; push-up names that lane
ROW refused tooling . "README:gauges" "$TLW" docs/reference/AKIT_SPEC.md
ROW refused tooling . "README:gauges" "$TLW" docs/reference/BKIT_SPEC.md
WOWN="${WPY%print(*}r=ct.walls_refusals(tj, lanes, sys.argv[1], sys.argv[2:]); print(' '.join(f'{p}:{o}' for p, o in r))"
check "walls table: push-up names AKit and BKit for tooling's docs/reference/AKIT_SPEC.md and BKIT_SPEC.md" "[ \"\$(python3 -c \"\$WOWN\" tooling docs/reference/AKIT_SPEC.md docs/reference/BKIT_SPEC.md 2>&1)\" = 'docs/reference/AKIT_SPEC.md:AKit docs/reference/BKIT_SPEC.md:BKit' ]"
# a walled lane may edit any other path outside the other lanes' areas (folders and owns)
ROW allowed tooling . "README:gauges" "$TLW" kits/BKit/Cargo.lock
ROW allowed tooling . "README:gauges" "$TLW" kits/CKit/q
# The manifest's orchestrator_owns names teams/x.toml: push-up and the guard refuse it for the walled lane, as the
# orchestrator's; the same path under a manifest without the key is allowed (the control).
ROW refused tooling . "README:gauges" "$TLW" teams/x.toml "$T/orc.toml"
ROW allowed tooling . "README:gauges" "$TLW" teams/x.toml "$T/acme.toml"

# --- gate PATH: a real push-up on this throwaway team, under cron's bare PATH, goes through a gate that
#     asserts python3 resolves to Homebrew's at 3.11+. The gate asserts on `command -v`, not sys.executable: Homebrew's
#     python3 is a symlink into the Cellar, so sys.executable never reads /opt/homebrew/bin/ and the check would stay red.
$CT pull-down acme.toml AKit >/dev/null 2>&1
( cd $LW && echo gp > kits/AKit/gate-path && G add kits/AKit/gate-path && G commit -qm 'A adds gate-path' )
{ cat <<'EOG'
gate = "test \"$(dirname \"$(command -v python3)\")\" = /opt/homebrew/bin && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'"
EOG
  cat acme.toml; } > gate.toml
check "push-up under cron's bare PATH goes through a gate that wants Homebrew's python3 at 3.11+" "env PATH=/usr/bin:/bin $CT push-up gate.toml AKit -f gatepath -m gatepath >/dev/null 2>&1 && git -C repos/acme-ee.git show exchange:kits/AKit/gate-path >/dev/null 2>&1"
# The push-up record names the python3 and git versions the gate ran with, as resolved under bin/codeteam's PATH.
check "the push-up record names the python3 and git versions the gate ran with" "python3 -c \"import json,sys;v=json.load(open('$TJ'))['features']['gatepath']['tool_versions'][-1];sys.exit(0 if 'Python 3.' in v['python3'] and '/opt/homebrew/bin/' in v['python3'] and 'git version' in v['git'] else 1)\""

mkdir -p $R/keep-me-data; echo precious > $R/keep-me-data/file
echo "== teardown"
# CodeGraph: a request worktree CodeGraph registered itself under the team's workcrews, and a project outside every team.
echo "$R/workcrews/requests/agent-req1" >> "$T/codegraph-registry"
echo "$T/outside-project" >> "$T/codegraph-registry"
cp "$T/codegraph-registry" "$T/registry.before"
check "teardown --dry-run says it would unregister a team root and changes no registration" "$CT teardown acme.toml --dry-run | grep -qF 'would unregister $R/integration/acme-ee-develop-integration' && cmp -s '$T/codegraph-registry' '$T/registry.before'"
check "the lab's lane worktree is registered in CodeGraph before teardown (lab init pinned it)" "reg_has $LR/workcrews/training/kgf-model-lab-main-training"
$CT teardown lab.toml >/dev/null; $CT teardown acme.toml >/dev/null
check "teardown unregisters every CodeGraph root under the acme team (its worktrees and workcrews)" "! grep -qF -- '$R/' '$T/codegraph-registry'"
check "teardown unregisters every CodeGraph root under the lab team" "! grep -qF -- '$LR/' '$T/codegraph-registry'"
check "teardown leaves a project outside every team registered" "reg_has $T/outside-project"
check "codeteam folders removed" "[ ! -e $R/restart-orchestrator.command ] && [ ! -d $R/team ] && [ ! -d $R/workcrews ] && [ ! -d $R/integration ] && [ ! -d $R/exchange ] && [ ! -d $R/prodpin ] && [ ! -d $R/design/Orc-Acme ] && [ ! -d $LR/team ]"
check "the develop checkout survives teardown" "[ \"\$(ls_ $R/design)\" = 'acme-ee-develop ' ] && [ -f $D/README ]"
check "the lab clone survives teardown" "[ -f $LR/design/kgf-model-lab-main/t ]"
check "other folders in the team folder survive teardown" "[ -f $R/keep-me-data/file ]"
check "lab data untouched" "[ -f $T/data/p1/x.jsonl ]"
check "external home untouched" "[ -f $T/bp/BACKPORTER.md ]"
check "product repo fingerprint unchanged" "[ \"$BEFORE\" = \"\$(fp)\" ]"
check "team branches removed" "[ -z \"\$(git -C repos/acme-ee.git branch --list 'lane/*' 'unit/*' 'pin/*' exchange integration)\" ]"

cd /; rm -rf "$T"
ZG="$(cd "$(dirname "$CT")/.." && pwd)/tests/zone-guard.sh"
check "zone guard self-test (tests/zone-guard.sh)" "bash '$ZG' >/dev/null 2>&1"
ZS="$(cd "$(dirname "$CT")/.." && pwd)/tests/zone-tool-scope.sh"
check "zone-tool scoped records (tests/zone-tool-scope.sh)" "bash '$ZS' >/dev/null 2>&1"
WD="$(cd "$(dirname "$CT")/.." && pwd)/tests/wait-defaults.sh"
check "job wait and watch-agent default to the Bash limit (tests/wait-defaults.sh)" "bash '$WD' >/dev/null 2>&1"
CF="$(cd "$(dirname "$CT")/.." && pwd)/tests/codegraph-first.sh"
check "a code-symbol rg/grep asks CodeGraph first (tests/codegraph-first.sh)" "bash '$CF' >/dev/null 2>&1"
echo "== $PASS passed, $FAIL failed"
[ $FAIL = 0 ]
