import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("redirects", ROOT / "share" / "claude-hooks" / "redirects.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
redirects = module.redirects


@pytest.mark.parametrize("words, expected", [
    (['cd', 'H', '2>&1'], (['cd', 'H'], [])),
    (['echo', 'x', '>', 'f'], (['echo', 'x'], ['f'])),
    (['echo', 'x', '>>f'], (['echo', 'x'], ['f'])),
    (['x', '&>f'], (['x'], ['f'])),
    (['x', '&>>', 'f'], (['x'], ['f'])),
    (['a', '>&', 'f'], (['a'], ['f'])),
    (['a', '>&2'], (['a'], [])),
    (['a', '>&-'], (['a'], [])),
    (['a', '2>|', 'f'], (['a'], ['f'])),
    (['cat', '<', 'in'], (['cat'], [])),
    (['cat', '<<', 'EOF'], (['cat'], [])),
    (['a', '<&3'], (['a'], [])),
    (['cd', 'X', '2>/dev/null'], (['cd', 'X'], ['/dev/null'])),
    (['git', 'commit', '-m', 'a > b'], (['git', 'commit', '-m', 'a > b'], [])),
    (['echo', '>'], (['echo'], [])),
    ([], ([], [])),
], ids=['cd-fd-dup', 'separate-write', 'append', 'combined-write', 'combined-append',
        'dup-file', 'dup-fd', 'close-fd', 'clobber', 'input', 'heredoc', 'input-fd',
        'cd-redirect', 'quoted-comparison', 'missing-target', 'empty'])
def test_redirects_examples(words, expected):
    assert redirects(words) == expected
