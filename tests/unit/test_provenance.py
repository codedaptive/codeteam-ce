"""The provenance hook's command rewrite (share/claude-hooks/provenance.py, 2026-10-31): the trailers
go on a `git commit` and on nothing else. `git commit-tree` and `git commit-graph` are other commands: rewriting them
turned an upstream PR lead's commit-tree into a porcelain commit under the session's name, which the backup then
mirrored. Unit tests: the pure functions only, no git and no stdin."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("provenance", ROOT / "share" / "claude-hooks" / "provenance.py")
provenance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provenance)

ADD = " --trailer 'Agent: lead'"


def test_a_commit_is_one():
    assert provenance.is_commit("git commit -m x")
    assert provenance.is_commit("git commit --amend --no-edit")
    assert provenance.is_commit("git -C /w/tree commit -m x")
    assert provenance.is_commit("cd /w/tree && git commit")


def test_plumbing_and_other_subcommands_are_not():
    assert not provenance.is_commit("git commit-tree 360941d0 -p e2af4146 -m 'feat(scan): x'")
    assert not provenance.is_commit("git commit-graph write --reachable")
    assert not provenance.is_commit("git log --grep commit")
    assert not provenance.is_commit("git -C /w/tree commit-tree t -p p -m m")


def test_the_trailers_go_after_commit():
    assert provenance.add_trailers("git commit -m x", ADD) == "git commit --trailer 'Agent: lead' -m x"
    assert provenance.add_trailers("git -C /w commit --amend", ADD) == "git -C /w commit --trailer 'Agent: lead' --amend"


def test_a_model_written_trailer_is_dropped():
    assert (provenance.add_trailers("git commit --trailer 'Model: mine' -m x", ADD)
            == "git commit --trailer 'Agent: lead' -m x")


def test_commit_tree_is_left_as_it_is():
    cmd = "git commit-tree 360941d0 -p e2af4146 -m 'feat(scan): x'"
    assert provenance.add_trailers(cmd, ADD) == cmd


def test_the_commit_dir_skips_commit_tree():
    assert provenance.commit_dir("git -C /w/tree commit -m x", "/cwd") == "/w/tree"
    assert provenance.commit_dir("cd /w/tree && git commit -m x", "/cwd") == "/w/tree"


# The words in a heredoc body, a quoted string or a comment are text, not a command.
# The rewrite spliced trailers into a Python comment written by a heredoc, and into a message's words.
HEREDOC = "cat > f.py <<'EOF'\nx = 1    # a write from inside the harness (git commit)\nEOF\n"


def test_a_commit_named_in_text_is_not_one():
    assert not provenance.is_commit(HEREDOC)
    assert not provenance.is_commit('echo "then git commit -m x"')
    assert not provenance.is_commit("codeteam2 say m general Orc NOTE Coord 'the old hook garbled git commit text'")
    assert not provenance.is_commit("ls  # git commit later")
    assert not provenance.is_commit("cat <<-END\n\tgit commit -m x\n\tEND\n")


def test_a_commit_the_shell_runs_is_one_wherever_it_stands():
    assert provenance.is_commit("git add f\ngit commit -m x")
    assert provenance.is_commit("(cd /w; git commit -m x)")
    assert provenance.is_commit("if true; then git commit -m x; fi")
    assert provenance.is_commit("GIT_AUTHOR_NAME=a git commit -m x")
    assert provenance.is_commit("/usr/bin/git commit -m x")
    assert provenance.is_commit(HEREDOC + "git commit -m x")


def test_the_trailers_go_after_the_commit_the_shell_runs_and_text_is_left_alone():
    assert (provenance.add_trailers('echo "git commit" && git commit -m x', ADD)
            == "echo \"git commit\" && git commit --trailer 'Agent: lead' -m x")
    assert (provenance.add_trailers(HEREDOC + "git commit -m x", ADD)
            == HEREDOC + "git commit --trailer 'Agent: lead' -m x")
    assert (provenance.add_trailers('git commit -m "say git commit"', ADD)
            == "git commit --trailer 'Agent: lead' -m \"say git commit\"")


def test_the_commit_dir_is_the_running_commits():
    assert provenance.commit_dir("echo 'git -C /elsewhere commit' && git -C /w/tree commit -m x", "/cwd") == "/w/tree"
    assert provenance.commit_dir("cd /w/tree && echo 'cd /other' && git commit -m x", "/cwd") == "/w/tree"
