#!/usr/bin/env -S python3 -u
"""Pure stopped_by contracts: how a step's outcome and output read as a full disk, a compile cache error or a test
failure. The changelog notice, Stage 2 step record, checked_members, team_env and feature-save locking tests are in
tests/integration/land-v52-tidy-io.py, because they build a real team on disk (rule 11)."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# Point the build queue at a scratch folder, so nothing these tests run reaches the checkout or the live queue.
os.environ["CODETEAM_QUEUE_DIR"] = str(Path(tempfile.mkdtemp(prefix="land-queue-")) / "queue")

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.machinery.SourceFileLoader("cl_tidy", str(ROOT / "bin" / "codeteam-land"))
spec = importlib.util.spec_from_loader(loader.name, loader)
cl = importlib.util.module_from_spec(spec)
with patch.object(subprocess, "run", return_value=SimpleNamespace(stdout="", stderr="", returncode=0)):
    loader.exec_module(cl)


def test_stopped_by_reads_each_tools_full_disk_error_on_a_step_that_did_not_pass():
    # Python, Rust (cargo, rustc), git and the shell each say ENOSPC their own way.
    for said in ("OSError: [Errno 28] No space left on device: '/team-acme/land/tmp/x'",
                 "error: failed to write `target/debug/deps/x.rmeta`: No space left on device (os error 28)",
                 "fatal: write error: No space left on device",
                 "sh: line 1: echo: write error: ENOSPC"):
        assert cl.stopped_by("FAIL", said) == "disk", said
        assert cl.stopped_by("HUNG", said) == "disk", said
    assert cl.stopped_by("PASS", "test_enospc_is_reported ... No space left on device ... ok") is None
    assert cl.stopped_by("FAIL", "assertion failed: left == right (3 != 4)") is None


def test_stopped_by_reads_the_swift_compile_cache_error_on_a_step_that_did_not_pass():
    # Xcode's shared compile cache once failed a package's check with this line;
    # the cache, not the work order. A full disk named in the same output is the cause, so it reads as "disk".
    said = ("<unknown>:0: error: cannot create CAS filesystem: not a IncludeFileList node kind "
            "[#CompilationCaching]")
    assert cl.stopped_by("FAIL", said) == "cache"
    assert cl.stopped_by("HUNG", said) == "cache"
    assert cl.stopped_by("PASS", said) is None
    assert cl.stopped_by("FAIL", said + "\nerror: No space left on device") == "disk"
    assert cl.stopped_by("FAIL", "note: see [#CompilationCaching] for how the cache works") is None
    # A stored result that cannot be read back, then cannot be replaced; neither line is tagged.
    for said in ("error: CAS error: unsupported compile result schema found",
                 "error: failed to update cache: cache poisoned for 'e37ee2e9c191648a' (new='llvmcas://05026ffa' vs. "
                 "existing 'llvmcas://85fa99d3')"):
        assert cl.stopped_by("FAIL", said) == "cache", said
        assert cl.stopped_by("PASS", said) is None, said
    assert cl.stopped_by("FAIL", "XCTAssertEqual failed: the cache poisoned flag was not set") is None


def test_a_finished_test_run_is_a_test_failure_even_beside_a_cache_error():
    # 2026-11-14: xcodebuild logged "failed to update cache: cache poisoned" twice while building a package,
    # then ran 1409 tests and two failed; the step read as CACHE, "nothing to fix", twice.
    poisoned = ("error: failed to update cache: cache poisoned for '4a19' (new='llvmcas://747a' vs. "
                "existing 'llvmcas://553a')\n")
    for ran in ("\U00100884 Test run with 1409 tests in 179 suites failed after 24.575 seconds with 2 issues.",
                "\t Executed 12 tests, with 1 failure (0 unexpected) in 0.512 (0.600) seconds",
                "test result: FAILED. 3 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out",
                "==== 1 failed, 30 passed in 1.23s ===="):
        assert cl.stopped_by("FAIL", poisoned + ran + "\n** TEST FAILED **") is None, ran
    # A build stopped before any test ran: no summary, XCTest's zero count, or only xcodebuild's verdict.
    for not_ran in ("", "\t Executed 0 tests, with 0 failures (0 unexpected) in 0.000 (0.021) seconds",
                    "** TEST FAILED **"):
        assert cl.stopped_by("FAIL", poisoned + not_ran) == "cache", not_ran
    # A full disk stays the machine's, whatever ran.
    assert cl.stopped_by("FAIL", "No space left on device\nTest run with 3 tests in 1 suite failed after 1 seconds") \
        == "disk"


if __name__ == "__main__":
    failed = 0
    for test in [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]:
        try:
            test()
            print(f"  PASS {test.__name__}")
        except (Exception, SystemExit) as exc:
            failed += 1
            print(f"  FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"{failed} failed" if failed else "all passed")
    sys.exit(1 if failed else 0)
