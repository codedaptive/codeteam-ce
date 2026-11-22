#!/usr/bin/env -S python3 -u
"""harness-guard: distinguish use of the harness from writes to it, including writes from different folders.
A team's own codeteam-land calls are not writes even when a finding quotes code with >, ; or |. The hook runs as Claude Code runs it: a subprocess fed the tool call on stdin. Nothing outside a temp
folder is written."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "share" / "claude-hooks" / "harness-guard.py"


def decide(command, cwd=None, symlink=False):
    """Return the hook decision for a Bash command and cwd in a temporary acme session.

    {CT}, {OUT}, and {M} name the harness home, outside folder, and manifest in the command and cwd.
    The cwd defaults to the temporary folder. With symlink, {CT}/link points to {OUT}/target.
    """
    with tempfile.TemporaryDirectory() as d:
        home = Path(d) / "codeteam"
        (home / "teams").mkdir(parents=True)
        outside = Path(d) / "outside"
        outside.mkdir()
        if symlink:
            (outside / "target").mkdir()
            (home / "link").symlink_to(outside / "target", target_is_directory=True)
        manifest = home / "teams" / "acme.toml"
        manifest.write_text(f'product = "acme"\nworktree_root = "{Path(d) / "team-acme"}"\n')
        def expand(value):
            return value.replace("{CT}", str(home)).replace("{OUT}", str(outside)).replace("{M}", str(manifest))
        cmd = expand(command)
        env = dict(os.environ, CODETEAM_MANIFEST=str(manifest), CODETEAM_HOME=str(home))
        r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": expand(cwd) if cwd else d}),
            capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return "deny" if '"deny"' in r.stdout else "allow"


def test_a_finding_quoting_a_comparison_is_allowed():
    assert decide('{CT}/bin/codeteam-land {M} finding f --what "drop_seq > hook_seq is never checked"') == "allow"


def test_a_finding_quoting_separators_is_allowed():
    assert decide("{CT}/bin/codeteam-land {M} finding f --what 'a > b; rm x | tee y && z'") == "allow"


def test_reviewed_is_allowed():
    assert decide("{CT}/bin/codeteam-land {M} reviewed agent-a6fe02e0c938d7f8a") == "allow"


def test_env_kong_doc_fix_is_allowed():
    assert decide('env CODETEAM_SESSION=Kong {CT}/bin/codeteam-land {M} doc-fix wo-x -m "doc fix: the install is checked once per landing"', cwd="{OUT}") == "allow"


def test_env_rm_harness_is_refused():
    assert decide("env A=1 rm {CT}/x", cwd="{OUT}") == "deny"


def test_env_cd_does_not_hide_relative_harness_write():
    assert decide("env cd {OUT}; rm codeteam/teams/acme.toml") == "deny"


def test_timeout_doc_fix_is_allowed():
    assert decide('timeout 600 {CT}/bin/codeteam-land {M} doc-fix wo-x -m "install"', cwd="{OUT}") == "allow"


def test_a_redirect_into_the_harness_is_refused():
    assert decide("echo x > {CT}/bin/codeteam-land") == "deny"


def test_a_write_chained_after_codeteam_land_is_refused():
    assert decide("{CT}/bin/codeteam-land {M} queue; rm {CT}/teams/acme.toml") == "deny"


def test_a_redirect_after_2_and_1_on_codeteam_land_is_refused():
    assert decide("{CT}/bin/codeteam-land {M} queue 2>&1 > {CT}/teams/out.txt") == "deny"


def test_a_hash_inside_a_word_hides_no_later_write():
    assert decide("{CT}/bin/codeteam-land {M} finding x#y; rm {CT}/teams/acme.toml") == "deny"


def test_unbalanced_quotes_fall_back_to_the_old_split_and_still_refuse():
    assert decide('echo "x > {CT}/teams/acme.toml') == "deny"


def test_running_a_program_kept_in_the_harness_is_not_a_write_to_it():
    """`~/.local/bin/uv pip install --python <venv>/bin/python pkg` writes only into the venv; the
    program's own path is what runs, not what is written."""
    assert decide("{CT}/bin/uv pip install --python venv/bin/python pkg") == "allow"
    assert decide("PIP_NO_INPUT=1 {CT}/bin/uv pip install --python venv/bin/python pkg") == "allow"


def test_a_program_kept_in_the_harness_that_names_a_harness_path_to_write_is_refused():
    assert decide("{CT}/bin/uv pip install --target {CT}/lib pkg") == "deny"
    assert decide("{CT}/bin/uv pip list > {CT}/teams/out.txt") == "deny"


def test_git_merge_with_outside_c_from_inside_harness_is_allowed():
    assert decide("git -C {OUT} merge --no-edit x", cwd="{CT}") == "allow"


def test_git_commit_with_outside_c_from_inside_harness_is_allowed():
    assert decide("git -C {OUT} commit -m x", cwd="{CT}") == "allow"


def test_git_commit_after_cd_outside_from_inside_harness_is_allowed():
    assert decide("cd {OUT} && git commit -m x", cwd="{CT}") == "allow"


def test_git_commit_in_session_harness_cwd_is_refused():
    assert decide("git commit -m x", cwd="{CT}") == "deny"


def test_git_commit_with_c_inside_harness_is_refused():
    assert decide("git -C {CT}/sub commit -m x", cwd="{CT}") == "deny"


def test_git_commit_after_cd_into_harness_from_outside_is_refused():
    assert decide("cd {CT} && git commit -m x", cwd="{OUT}") == "deny"


def test_git_commit_with_repeated_c_naming_harness_then_outside_is_refused():
    assert decide("git -C {CT} -C {OUT} commit -m x", cwd="{CT}") == "deny"


def test_git_commit_with_repeated_c_ending_inside_harness_is_refused():
    assert decide("git -C {OUT} -C {CT}/sub commit -m x", cwd="{OUT}") == "deny"


def test_git_commit_with_relative_second_c_into_harness_is_refused():
    """From the temp root, `../codeteam` is outside the harness; only resolved against the first -C is it the harness."""
    assert decide("git -C {OUT} -C ../codeteam commit -m x") == "deny"


def test_git_commit_after_bare_cd_from_harness_is_allowed():
    assert decide("cd && git commit -m x", cwd="{CT}") == "allow"


def test_git_commit_after_cd_dash_from_harness_is_refused():
    assert decide("cd - && git commit -m x", cwd="{CT}") == "deny"


def test_relative_harness_path_after_cd_outside_is_refused():
    assert decide("cd {OUT} && rm ../codeteam/teams/acme.toml") == "deny"


def test_relative_harness_path_from_outside_cwd_is_refused():
    assert decide("rm ../codeteam/teams/acme.toml", cwd="{OUT}") == "deny"


def test_relative_outside_path_after_cd_outside_is_allowed():
    assert decide("cd {OUT} && rm ../outside/x", cwd="{CT}") == "allow"


def test_git_commit_after_cd_with_only_options_from_harness_is_allowed():
    assert decide("cd -P && git commit -m x", cwd="{CT}") == "allow"


def test_cd_harness_or_cd_outside_keeps_harness_for_commit():
    assert decide("cd {CT} || cd {OUT}; git commit -m x") == "deny"


def test_cd_outside_or_cd_harness_keeps_outside_for_commit():
    assert decide("cd {OUT} || cd {CT}; git commit -m x", cwd="{CT}") == "allow"


def test_cd_outside_or_commit_judges_commit_from_harness():
    assert decide("cd {OUT} || git commit -m x", cwd="{CT}") == "deny"


def test_cd_outside_or_pipeline_judges_commit_from_harness():
    assert decide("cd {OUT} || true | git commit -m x", cwd="{CT}") == "deny"


def test_cd_harness_or_commit_judges_commit_from_outside():
    assert decide("cd {CT} || git commit -m x") == "allow"


def test_cd_in_pipeline_does_not_move_commit_outside():
    assert decide("cd {OUT} | git commit -m x", cwd="{CT}") == "deny"


def test_background_cd_does_not_move_commit_outside():
    assert decide("cd {OUT} & git commit -m x", cwd="{CT}") == "deny"


def test_background_and_list_does_not_move_commit_outside():
    assert decide("cd {OUT} && true & git commit -m x", cwd="{CT}") == "deny"


def test_cd_harness_with_fd_duplication_refuses_commit():
    assert decide("cd {CT} 2>&1 && git commit -m x") == "deny"


def test_cd_outside_with_fd_duplication_allows_commit():
    assert decide("cd {OUT} 2>&1 && git commit -m x", cwd="{CT}") == "allow"


def test_cd_harness_with_write_redirect_refuses_commit():
    assert decide("cd {CT} >/dev/null && git commit -m x") == "deny"


def test_clobber_redirect_into_harness_is_refused():
    assert decide("echo x >| {CT}/teams/out.txt") == "deny"


def test_glued_command_redirect_into_harness_is_refused():
    assert decide("cat>{CT}/x", cwd="{OUT}") == "deny"


def test_glued_argument_redirect_into_harness_is_refused():
    assert decide("echo x>{CT}/x", cwd="{OUT}") == "deny"


def test_quoted_redirect_operand_into_harness_is_refused():
    assert decide('echo x >"{CT}/a b"', cwd="{OUT}") == "deny"


def test_glued_redirect_outside_harness_is_allowed():
    assert decide("echo a>b", cwd="{OUT}") == "allow"


def test_quoted_redirect_text_is_allowed():
    assert decide("echo 'x>{CT}/x'", cwd="{OUT}") == "allow"


def test_tool_combined_redirect_into_harness_is_refused():
    assert decide("{CT}/bin/codeteam-land {M} queue &> {CT}/teams/out.txt") == "deny"


def test_tool_fd_duplication_and_pipe_without_write_is_allowed():
    assert decide("{CT}/bin/codeteam-land {M} queue 2>&1 | tail -3") == "allow"


def test_background_cd_then_spaced_redirect_keeps_harness_cwd():
    assert decide("cd {OUT} & >/dev/null && git commit -m x", cwd="{CT}") == "deny"


def test_conditional_and_cd_outside_then_commit_from_harness_is_refused():
    assert decide("false && cd {OUT}; git commit -m x", cwd="{CT}") == "deny"


def test_conditional_or_cd_outside_then_commit_from_harness_is_refused():
    assert decide("true || cd {OUT}; git commit -m x", cwd="{CT}") == "deny"


def test_conditional_cd_outside_and_commit_from_harness_is_allowed():
    assert decide("git fetch && cd {OUT} && git commit -m x", cwd="{CT}") == "allow"


def test_conditional_cd_harness_then_commit_from_outside_is_refused():
    assert decide("false && cd {CT}; git commit -m x") == "deny"


def test_conditional_cd_outside_or_cd_harness_then_commit_is_refused():
    assert decide("false && cd {OUT} || cd {CT}; git commit -m x") == "deny"


def test_heredoc_with_apostrophe_and_glued_harness_redirect_is_refused():
    assert decide("cat>{CT}/x <<EOF\nit's\nEOF", cwd="{OUT}") == "deny"


def test_builtin_cd_into_harness_refuses_commit():
    assert decide("builtin cd {CT}; git commit -m x", cwd="{OUT}") == "deny"


def test_negated_cd_into_harness_then_commit_is_refused():
    assert decide("! cd {CT}; git commit -m x", cwd="{OUT}") == "deny"


def test_negated_cd_into_harness_or_commit_is_refused():
    assert decide("! cd {CT} || git commit -m x", cwd="{OUT}") == "deny"


def test_negated_cd_into_harness_and_commit_is_refused():
    """The union of both folders is conservative for &&."""
    assert decide("! cd {CT} && git commit -m x", cwd="{OUT}") == "deny"


def test_command_cd_outside_may_leave_commit_in_harness():
    assert decide("cd {CT}; command cd {OUT}; git commit -m x", cwd="{OUT}") == "deny"


def test_time_p_cd_outside_may_leave_add_in_harness():
    assert decide("cd {CT}; time -p cd {OUT}; git add -A", cwd="{OUT}") == "deny"


def test_time_end_options_cd_outside_may_leave_add_in_harness():
    assert decide("cd {CT}; time -- cd {OUT}; git add -A", cwd="{OUT}") == "deny"


def test_builtin_command_cd_outside_may_leave_add_in_harness():
    assert decide("cd {CT}; builtin command cd {OUT}; git add -A", cwd="{OUT}") == "deny"


def test_builtin_end_options_cd_into_harness_may_refuse_commit():
    assert decide("builtin -- cd {CT}; git commit -m x", cwd="{OUT}") == "deny"


def test_noglob_cd_into_harness_may_refuse_commit():
    assert decide("noglob cd {CT}; git commit -m x", cwd="{OUT}") == "deny"


def test_builtin_cd_outside_allows_commit():
    assert decide("builtin cd {OUT}; git commit -m x", cwd="{CT}") == "allow"


def test_fallback_quoted_spaced_harness_redirect_is_refused():
    assert decide('echo x >"{CT}/a b" <<EOF\nit\'s\nEOF', cwd="{OUT}") == "deny"


def test_fallback_quoted_harness_redirect_before_apostrophe_is_refused():
    assert decide('echo x >"{CT}/ab" # it\'s', cwd="{OUT}") == "deny"


def test_fallback_heredoc_harness_commit_is_refused():
    assert decide("bash <<EOF\ncd {CT}; git commit -m x\nit's\nEOF", cwd="{OUT}") == "deny"


def test_redirect_after_numbered_output_dup_into_harness_is_refused():
    assert decide("echo x 2>&1>{CT}/ab", cwd="{OUT}") == "deny"


def test_redirect_after_output_dup_into_harness_is_refused():
    assert decide("echo x >&2>{CT}/ab", cwd="{OUT}") == "deny"


def test_fallback_quoted_spaced_outside_redirect_is_allowed():
    assert decide('echo x >"{OUT}/a b" <<EOF\nit\'s\nEOF', cwd="{OUT}") == "allow"


def test_link_then_parent_from_harness_refuses_commit():
    assert decide("cd link && cd .. && git commit -m x", cwd="{CT}", symlink=True) == "deny"


def test_link_then_parent_from_outside_refuses_commit():
    assert decide("cd {CT}/link && cd .. && git commit -m x", cwd="{OUT}", symlink=True) == "deny"


def test_newline_after_cd_into_harness_refuses_commit():
    assert decide("cd {CT}\ngit commit -m x", cwd="{OUT}") == "deny"


def test_newline_after_make_refuses_harness_removal():
    assert decide("make -v\nrm -rf {CT}/teams", cwd="{OUT}") == "deny"


def test_quoted_newline_is_allowed():
    assert decide("echo 'a\nb'", cwd="{OUT}") == "allow"


def test_heredoc_body_cd_does_not_move_following_commit():
    assert decide("cat <<EOF\ncd {CT}\nEOF\ngit commit -m x", cwd="{OUT}") == "allow"


if __name__ == "__main__":
    import inspect
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and inspect.isfunction(fn):
            try:
                fn()
                print(f"  PASS {name}")
            except Exception as ex:          # report every case, then fail once
                failed += 1
                print(f"  FAIL {name}: {type(ex).__name__}: {ex}")
    print("all passed" if not failed else f"{failed} failed")
    raise SystemExit(1 if failed else 0)
