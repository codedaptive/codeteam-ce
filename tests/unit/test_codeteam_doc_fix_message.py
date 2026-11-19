import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "share"))
from codeteam_doc_fix_message import doc_fix_message


def test_message_has_exact_doc_fix_trailers():
    assert doc_fix_message("Correct the guide\n\nDetails.  \n", "Kong") == (
        "Correct the guide\n\nDetails.\n\n"
        "Made-By: codeteam-land doc-fix\nDoc-fix-by: Kong\n"
    )


@pytest.mark.parametrize("message", ["", "  \n\t"])
def test_blank_message_is_rejected(message):
    with pytest.raises(ValueError):
        doc_fix_message(message, "Kong")
