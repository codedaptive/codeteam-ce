"""shell_text.code_only (share/claude-hooks/shell_text.py; D557): a command line with the text the shell does not run
as code (quoted strings, comments, here-document bodies) blanked out, at the same length so a match's span stays the
command's. Unit tests (rule 11): a pure function, no shell."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("shell_text", ROOT / "share" / "claude-hooks" / "shell_text.py")
shell_text = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shell_text)
code_only = shell_text.code_only


def test_quoted_text_is_blanked_and_the_quotes_and_code_stay():
    assert code_only("echo 'a b' \"c\" && ls") == "echo 'xxx' \"x\" && ls"


def test_an_escaped_quote_does_not_end_a_double_quoted_string():
    assert code_only('echo "a\\"b" ; ls') == 'echo "xxxx" ; ls'


def test_a_backslash_outside_quotes_escapes_the_quote_after_it():
    assert code_only("echo it\\'s; ls") == "echo it\\'s; ls"


def test_a_comment_is_blanked_to_the_end_of_its_line_and_a_mid_word_hash_is_not_one():
    assert code_only("ls # note\npwd") == "ls xxxxxx\npwd"
    assert code_only("echo a#b") == "echo a#b"


def test_a_here_document_body_is_blanked_up_to_its_delimiter_line():
    assert code_only("cat <<'EOF'\nab\ncd\nEOF\nls") == "cat <<'EOF'\nxx\nxx\nEOF\nls"
    assert code_only("cat <<EOF >f\nab\nEOF\nls") == "cat <<EOF >f\nxx\nEOF\nls"


def test_a_dash_here_document_ends_at_a_tab_indented_delimiter():
    assert code_only("cat <<-END\n\tab\n\tEND\nls") == "cat <<-END\nxxx\n\tEND\nls"


def test_two_here_documents_on_one_line_are_read_in_order():
    assert code_only("cat <<A <<B\n1\nA\n2\nB\nls") == "cat <<A <<B\nx\nA\nx\nB\nls"


def test_a_here_document_with_no_delimiter_line_runs_to_the_end():
    assert code_only("cat <<EOF\nab\ncd") == "cat <<EOF\nxx\nxx"


def test_a_here_string_is_not_a_here_document():
    assert code_only("cat <<< word\nls") == "cat <<< word\nls"


def test_an_unclosed_quote_is_blanked_to_the_end():
    assert code_only("echo 'ab") == "echo 'xx"


def test_the_result_always_has_the_commands_length():
    for cmd in ("", "'", '"\\', "#", "cat <<E\n", "a 'b\nc' d # e\n<<F\nf\nF"):
        assert len(code_only(cmd)) == len(cmd)
