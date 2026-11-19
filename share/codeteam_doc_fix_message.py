"""The commit message of a doc-fix commit.

"Only changes to code go back through the entire process." A doc-fix commit carries the reviewer's message, then the
trailers `Made-By: codeteam-land doc-fix` and `Doc-fix-by: <reviewer>`. Not the bare MADE_BY line
`Made-By: codeteam-land`: tool_made_reason skips review for a commit carrying that line, and a doc-fix commit is the
reviewer's own change, read by the reviewer before it records its verdict.
"""


def doc_fix_message(message: str, reviewer: str) -> str:
    """`message` without trailing whitespace, then the doc-fix trailers; ValueError for a blank message."""
    if not message.strip():
        raise ValueError("a doc-fix commit needs a message")
    return message.rstrip() + "\n\nMade-By: codeteam-land doc-fix\n" + f"Doc-fix-by: {reviewer}\n"
