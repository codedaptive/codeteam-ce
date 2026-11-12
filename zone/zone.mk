# Zone targets for a monorepo. codeteam's launch script exports
# MAKEFILES=<codeteam>/zone/zone.mk, so make reads this file in every worktree.
# A repo Makefile may also include it: -include $(CODETEAM_HOME)/zone/zone.mk
# The launch script sets CODETEAM_HOME and CODETEAM_ZONE (the zone's path in the repo).
ifndef ZONE_MK_LOADED
ZONE_MK_LOADED := 1
# ZONE_TEST runs the zone's tests: the repo's test-one on $(ZONE), then on $(ZONE)/rust.
# A repo with its own Makefile decides what test-one runs there. In a repo with none,
# zone.mk's test-one below runs, and the $(ZONE)/rust leg usually finds no folder and
# prints "no tests".
ZONE        ?= $(CODETEAM_ZONE)
# Every target runs from the worktree root, so it works from any folder in it.
ZONE_ROOT   := $(shell git rev-parse --show-toplevel 2>/dev/null || pwd)
ZONE_TOOL   ?= $(CODETEAM_HOME)/bin/zone-tool
ZONE_TEST   ?= $(MAKE) --no-print-directory -C $(ZONE_ROOT) test-one DIR=$(ZONE) && $(MAKE) --no-print-directory -C $(ZONE_ROOT) test-one DIR=$(ZONE)/rust
EXCHANGE    ?= $(CODETEAM_EXCHANGE)
WARM_FROM   ?= $(or $(CODETEAM_SWT),$(EXCHANGE))
# Copied in by warm (APFS copy-on-write: near-instant, no extra disk until a file changes).
# A Rust build folder stays valid when copied; a Swift one does not (SwiftPM ties a build
# to its folder), so Swift is warmed by building through Xcode's compile cache instead.
WARM_DIRS   ?= cargo-target
# The code index (CodeGraph) follows each worktree by itself: no warm step (graft retired 2026-10-29).
# zone-test options (zone-tool test --help): empty runs as before. Override one run with
# `make zone-test ZONE_TEST_FLAGS=...`.
ZONE_TEST_FLAGS ?=
# Both targets submit their run to the build queue (zone-tool job submit): the runner starts it when its
# class has a share free and the machine is not busy. CLASS picks the class (full, post, pre, dev); each
# target has its own default, below. ZONE_JOB_WAIT is how long make waits for the result, in seconds; a
# job still waiting then makes the recipe fail with zone-tool's exit 4 (make reports "Error 4") and print the
# `zone-tool job wait <ticket>` that continues the wait. The wait must end before the caller's shell kills
# make, so `auto` (the default) takes the shell limit from BASH_DEFAULT_TIMEOUT_MS (codeteam sessions set it
# to 30 minutes) less a minute, and 100 s when it is unset (Claude Code's own limit is 120 s). A number of
# seconds sets it; 0 waits until the job is done (gates and scripts).
CLASS ?=
ZONE_JOB_WAIT ?= auto

.PHONY: zone-test zone-test-one zone-test-status zone-check warm

# A recipe line that names $(MAKE) runs even under make -n, -t or -q, so without this
# guard `make -n zone-test-one` would run zone-tool, whose inner make only prints and
# exits 0, and file a PASS record that --cached then replays. It reads MAKEFLAGS as GNU make
# 3.81 writes it, stops at "--" or the first VAR=value, and counts n, t or q only in
# the leading undashed flag word or a single-dash word.
zone_skip_no_exec = skip=; first=1; for w in $$MAKEFLAGS; do case "$$w" in --|*=*) break;; --just-print|--dry-run|--recon|--touch|--question) skip=1;; --*) ;; -*[ntq]*) skip=1;; [!-]*[ntq]*|[ntq]*) test -n "$$first" && skip=1;; esac; first=; done; if test -n "$$skip"; then echo "$@: not recorded under make -n, -t or -q"; exit 0; fi;

# In a repo with no Makefile, a zone of `.` runs the lane's CODETEAM_OWNS (test-one below),
# so the same code can need a different answer when only CODETEAM_OWNS changes. The suite
# record keeps its one name (.test-record.json) and its hash stays the code's alone (push-up's
# covered check and test-status compare it in sessions without CODETEAM_OWNS), so OWNS goes
# in as a salt: a record answers --cached or --single only for the same OWNS. A repo with its
# own Makefile gets no salt and its zone-tool arguments are as they were.
ZONE_TEST_SALT = $(if $(ZONE_ROOT_MAKEFILE),,--salt "owns=$(CODETEAM_OWNS)")

zone-test:
	@test -n "$(ZONE)" || { echo "zone-test: set CODETEAM_ZONE"; exit 2; }
	@$(zone_skip_no_exec) cd $(ZONE_ROOT) && $(ZONE_TOOL) job submit --class $(or $(CLASS),full) --wait $(ZONE_JOB_WAIT) $(ZONE_TEST_SALT) $(ZONE_TEST_FLAGS) -- sh -c '$(ZONE_TEST)'

# One package or a filter, through the same record and lock: a repeat on unchanged
# code answers from its record. make zone-test-one DIR=<pkg> [SWIFT_TEST_ARGS=...] [CARGO_TEST_ARGS=...] [PYTEST_ARGS=...] [CLASS=...]
# Class dev by default (the first class to hold back when the machine is busy); CLASS=pre or CLASS=post
# queues the run in that class instead.
# --scope: the record stands until something DIR's tests can touch changes.
# The default ZONE_TEST_ONE_CMD runs the repo's test-one: the repo Makefile's, or zone.mk's own (below)
# in a repo with none; a team may set ZONE_TEST_ONE_CMD instead.
# SWIFT_TEST_ARGS, CARGO_TEST_ARGS and PYTEST_ARGS reach only a repo Makefile's test-one. zone.mk's own uses zone-tool test-one, which passes
# none of them to pytest; they still key the record. Exported PYTEST_ADDOPTS reaches zone.mk's
# pytest; a repo Makefile controls whether it reaches pytest there. Keying it distinguishes
# narrowed runs subject to the collision limits below.
# The repo's own makefile, if it has one: empty means zone.mk supplies test-one (below).
ZONE_ROOT_MAKEFILE := $(wildcard $(ZONE_ROOT)/GNUmakefile $(ZONE_ROOT)/makefile $(ZONE_ROOT)/Makefile)
# In a repo with no makefile, zone.mk's test-one runs the paths in CODETEAM_OWNS when DIR is
# the repo root, so the same DIR on unchanged code runs different tests under a different
# OWNS: the key carries owns=, else a record made under one OWNS (or a refusal under none)
# answers for another. It is added for every DIR, which spares make from recognising the
# spellings of the root (., ./, an absolute path). A repo with its own makefile keeps the
# key without it, byte for byte, so the records it already has still match; the other branch
# is new, so it is stripped to single spaces ("one pkg owns=a:b").
# Test groups (unit, integration, validation): a repo Makefile's test-one reads GROUP (default unit).
# zone.mk's own test-one does not hand GROUP to tests; it passes CODETEAM_TEST_GROUP through zone-tool
# test-one to the tests, which decide what to run. Keep their key terms separate. Non-unit values go in
# the key so a unit record never answers for an integration run; unset or unit keeps the existing key
# so no record is invalidated.
ZONE_TEST_GROUP_KEY = $(if $(filter-out unit,$(GROUP)), group=$(GROUP))$(if $(filter-out unit,$(CODETEAM_TEST_GROUP)), test-group=$(CODETEAM_TEST_GROUP))
# Unset, empty or whitespace-only values add nothing, keeping the key byte for byte. Labels distinguish pytest terms
# from the unlabelled SWIFT/CARGO terms. Accepted limits: a value containing a label word can
# still collide, and zone-tool job submit collapses whitespace in --key, so values differing
# only in inner whitespace share a record.
ZONE_TEST_ARGS_KEY = $(if $(strip $(PYTEST_ARGS)), pytest=$(strip $(PYTEST_ARGS)))$(if $(strip $(PYTEST_ADDOPTS)), pytest-addopts=$(strip $(PYTEST_ADDOPTS)))
ZONE_TEST_ONE_KEY = $(if $(ZONE_ROOT_MAKEFILE),one $(DIR) $(SWIFT_TEST_ARGS) $(CARGO_TEST_ARGS),$(strip one $(DIR) $(SWIFT_TEST_ARGS) $(CARGO_TEST_ARGS) owns=$(CODETEAM_OWNS)))$(ZONE_TEST_ARGS_KEY)$(ZONE_TEST_GROUP_KEY)
ZONE_TEST_ONE_FLAGS ?= --cached --single
# The command that tests one DIR: the repo's own `make test-one` by default. A team whose repo has no test-one (a Makefile without one, or a different way to test) sets
# ZONE_TEST_ONE_CMD in its manifest's [env] (e.g. a Swift package team: codeteam's swift-test-xcode on the package),
# so the zone-test-one target, its record and its cache work the same everywhere.
ZONE_TEST_ONE_CMD ?= $(MAKE) --no-print-directory test-one DIR=$(DIR)
# Single-quote the key, escaping embedded quotes: quotes, backticks and $(...) in values
# must reach zone-tool literally rather than be interpreted by the shell.
zone-test-one:
	@test -n "$(DIR)" || { echo "zone-test-one: set DIR"; exit 2; }
	@$(zone_skip_no_exec) cd $(ZONE_ROOT) && $(ZONE_TOOL) job submit --class $(or $(CLASS),dev) --wait $(ZONE_JOB_WAIT) --key '$(subst ','\'',$(ZONE_TEST_ONE_KEY))' --scope "$(DIR)" $(ZONE_TEST_ONE_FLAGS) -- sh -c '$(ZONE_TEST_ONE_CMD)'

# zone-check: the type-check zone-tool runs before every test run (the product's `make check`, or the manifest's
# ZONE_CHECK_CMD); a test run on code that fails it is refused. Run it after each batch of edits.
zone-check:
	@cd $(ZONE_ROOT) && $(ZONE_TOOL) check $(DIR)

zone-test-status:
	@cd $(ZONE_ROOT) && $(ZONE_TOOL) test-status

# test-one for a repo with no Makefile of its own (a repo zone.mk reaches only through
# MAKEFILES). Any of GNUmakefile, makefile or Makefile at the root counts as having one;
# then this rule is not defined and the repo's own test-one is the only one.
# zone-tool test-one runs pytest and the tests/*.sh of DIR, from the root. DIR=. (or any DIR
# that resolves to the root, such as ./) means the lane's owned paths (CODETEAM_OWNS, colon-separated): in a repo shared by several lanes a
# lane's zone path is `.`, so a zone-test of `.` must run only the paths that lane owns, not
# every lane's tests. With CODETEAM_OWNS empty zone-tool refuses rather than pass on no
# tests or run the whole repo.
ifeq ($(ZONE_ROOT_MAKEFILE),)
.PHONY: test-one
test-one:
	@test -n "$(DIR)" || { echo "test-one: set DIR"; exit 2; }
	@cd $(ZONE_ROOT) && $(ZONE_TOOL) test-one "$(DIR)"
endif

# warm: make a new worktree ready to work in, mechanically: copy the Rust build folder
# from WARM_FROM, then warm-build. WARM_BUILD=0 copies only.
# warm-build: compile the zone's tests without running them, Rust through sccache and Swift
# through Xcode's compile cache (CODETEAM_SWIFT_XCODE=1). Code compiled anywhere on this Mac
# before is not compiled again; the lead then rebuilds only what it changes. codeteam also
# runs it in the exchange worktree after a zone's push lands, so exchange's cargo-target
# and the compile cache hold the newest exchange code.
WARM_BUILD ?= 1
.PHONY: warm-build zone-clean

# zone-clean: remove this worktree's build output (cargo-target, target, .build, node_modules' build caches are
# left). Everything removed is rebuilt on the next build, or cloned again by `make warm`. A product Makefile that
# has its own `clean` keeps it; this one is codeteam's, for every team (some products have none).
CLEAN_DIRS ?= cargo-target target .build
zone-clean:
	@cd $(ZONE_ROOT) && for d in $(CLEAN_DIRS); do if [ -d "$$d" ]; then du -sh "$$d" | sed 's/^/removing /'; rm -rf "$$d"; fi; done; echo "zone-clean: done"
warm:
	@test -n "$(WARM_FROM)" || { echo "warm: set CODETEAM_SWT or CODETEAM_EXCHANGE"; exit 2; }
	@cd $(ZONE_ROOT) && for d in $(WARM_DIRS); do $(ZONE_TOOL) warm --from $(WARM_FROM) --target $$d; done
	@if [ "$(WARM_BUILD)" = 1 ]; then $(MAKE) --no-print-directory -C $(ZONE_ROOT) warm-build; fi

warm-build:
	@if [ -z "$(ZONE)" ] || [ "$(ZONE)" = "." ]; then echo "warm-build: no zone (CODETEAM_ZONE)"; exit 0; fi
	@cd $(ZONE_ROOT); \
	if [ -f "$(ZONE)/rust/Cargo.toml" ]; then echo "warm: compiling $(ZONE)/rust tests"; \
	  $(MAKE) --no-print-directory test-one DIR=$(ZONE)/rust CARGO_TEST_ARGS=--no-run || exit $$?; fi; \
	if [ -f "$(ZONE)/Package.swift" ]; then echo "warm: compiling $(ZONE) Swift tests"; \
	  if [ "$$CODETEAM_SWIFT_XCODE" = 1 ]; then \
	    helper="$(CODETEAM_HOME)/bin/swift-test-xcode"; \
	    [ -f "$$helper" ] || { echo "warm: FAILED: CODETEAM_SWIFT_XCODE=1 but codeteam's swift-test-xcode is not here; not running swift build (it would build into $(ZONE)/.build)" >&2; exit 2; }; \
	    python3 "$$helper" "$(ZONE)" --build-only || exit $$?; \
	  else (cd "$(ZONE)" && swift build --build-tests) || exit $$?; fi; fi

endif
