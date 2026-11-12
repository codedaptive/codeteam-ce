#!/usr/bin/env bash
# check-public.sh: fail when the tree holds a private name, a private path or a secret.
# Checks the repository it lives in, whatever the current folder. Exit 0 = clean, 1 = something found.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 2

# Names of private projects, machines and people, and private paths (case-insensitive, extended regex).
NAMES='moot|tessera|aimodel|ai-model-lab|\bforge\b|fulcrum|alpha-?llm|alphamini|\bmortar\b|cliproxy|minillm|\bparall\b|dev_docs|simple[- ]machines|\bbob\b|/Users/|devlop|ddfactory|com\.bob|team-codegraph|codegraph-team|teams/codegraph|products/codegraph|/opt/homebrew/bin/python3|geniuslocus|ariamcp|queuekit|persistencekit|neuronkit'
# "bench" is checked apart: `cargo bench` is cargo's own subcommand, so a line that names cargo may say it.
BENCH='\bbench\b'
# The public org may appear only in README.md and LICENSE.
ORG='codedaptive'
# Secrets: API keys, tokens, private keys.
SECRETS='sk-ant-[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|AIza[0-9A-Za-z_-]{35}'

list() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git ls-files -co --exclude-standard
  else find . -type f -not -path './.git/*' | sed 's|^\./||'; fi | grep -v '^scripts/check-public\.sh$'
}
scan() { list | tr '\n' '\0' | xargs -0 grep -nIE "$@" 2>/dev/null; }

fail=0
# README.md may name the public sibling projects (MOOTx01 CE) on lines that link to their public repos.
hits=$( { scan -i "$NAMES" | grep -vE '^README\.md:[0-9]+:.*(github\.com/codedaptive/mootx01-ce|MOOTx01 memory system)'; scan -i "$BENCH" | grep -vi 'cargo'; } | sort -u)
if [ -n "$hits" ]; then echo "private names or paths:"; echo "$hits" ; fail=1; fi
org=$(scan -i "$ORG" | grep -vE '^(README\.md|LICENSE):')
if [ -n "$org" ]; then echo "org name outside README.md and LICENSE:"; echo "$org" ; fail=1; fi
sec=$(scan "$SECRETS")
if [ -n "$sec" ]; then echo "possible secrets:"; echo "$sec" ; fail=1; fi
[ $fail -eq 0 ] && echo "check-public: clean ($(list | wc -l | tr -d ' ') files checked)"
exit $fail
