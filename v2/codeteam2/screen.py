"""Reading a Claude Code session's screen (herdr `agent read --format ansi`): is someone typing in
its input box, does the pane show a subagent's view instead of the session's main conversation, and
did its last turn end on an API error.

The input box is the line that starts with ❯ between two horizontal rules. Claude Code shows a
suggested next prompt there in faint text (SGR 2) when the box is empty, so only text drawn at
normal intensity counts as a draft: something a person typed and has not sent. Seen on the smoke
team, 2026-10-25: `❯\\xa0\\x1b[2mSmoke task 4\\x1b[0m` is a suggestion, not a draft.

A session that has started agents can show one of them instead of its own conversation (Claude Code's
agent view): its agent list is drawn below the input box, one row per agent, the shown one marked ⏺
and the others ◯ (`main` is the session itself), and the empty box's faint placeholder reads
`Message @<agent>…`. Anything typed then goes to that agent, not to the session (Coord-model-benchmarks,
2026-10-29: three deliveries typed into its request lead's view started no turn of its own).
"""
import re

SGR = re.compile(r"\x1b\[([0-9;:]*)m")
OTHER_ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-ln-z]|\x1b\][^\x07]*\x07")
PROMPT = "❯"
RULE_CHARS = set("─━—- ")
# One row of the agent list below the input box: `  ⏺ main`, `  ◯ request-lead (+1)  Lead ...`, and a
# child row `  └ ◯ change-reviewer ...`. The rows not shown are greyed by colour, not by SGR 2, so the
# marker, not the intensity, says which agent's view the pane shows.
AGENT_ROW = re.compile(r"^\s*(?:❯\s*)?(?:└\s*)?([⏺◯])\s+(\S+)")
# A row of the background-tasks list with the selection marker on it: keyboard focus is in that list, not in the
# input box (Claude Code shows "↑/↓ to select"). Text typed now goes nowhere useful (found 2026-11-05:
# "❯ ⏺ main" was read as a draft and its mail held 14 hours).
TASK_ROW_SELECTED = re.compile(r"^\s*❯\s*(?:└\s*)?[⏺◯]\s+\S")
# The empty input box's faint placeholder in an agent's view.
VIEW_PLACEHOLDER = re.compile(r"^Message @(\S+?)…")

# Claude Code's own error lines (`⎿  API Error: 529 Overloaded`, usage-limit and credit notices), not
# a bare number that could appear in any conversation.
API_ERROR = re.compile(r"API Error|Request was rejected|usage limit reached|hit your (usage )?limit|"
                       r"credit balance is too low|credentials cooling down", re.I)


def plain(line):
    return OTHER_ESC.sub("", SGR.sub("", line))


def _is_rule(text):
    t = text.strip()
    return len(t) >= 10 and t[:3] == "───"


def _by_intensity(line):
    """(normal, faint): the characters of one ANSI line drawn at normal intensity, and those drawn faint."""
    out, dim, faint, pos = [], [], False, 0
    line = OTHER_ESC.sub("", line)
    for m in SGR.finditer(line):
        (dim if faint else out).append(line[pos:m.start()])
        for p in (m.group(1) or "0").replace(":", ";").split(";"):
            if p in ("", "0", "22"):
                faint = False
            elif p == "2":
                faint = True
        pos = m.end()
    (dim if faint else out).append(line[pos:])
    return "".join(out), "".join(dim)


def typed_text(line):
    """The characters of one ANSI line drawn at normal intensity (faint text dropped)."""
    return _by_intensity(line)[0]


def _input_line(plains):
    """The index of the input box's ❯ line, or None: the last ❯ line that is not a selected row of the
    background-tasks list (that list has its own ❯ marker when it has the keyboard)."""
    for i in range(len(plains) - 1, -1, -1):
        if plains[i].lstrip().startswith(PROMPT) and not TASK_ROW_SELECTED.match(plains[i]):
            return i
    return None


def task_list_focused(ansi_screen):
    """True when the keyboard is in the background-tasks list below the input box, not in the box."""
    return any(TASK_ROW_SELECTED.match(plain(x)) for x in ansi_screen.splitlines())


def draft(ansi_screen):
    """Unsent text a person typed into the session's input box, or "" when the box is empty (or
    shows only Claude Code's faint suggestion), or None when no input box is on screen."""
    lines = ansi_screen.splitlines()
    plains = [plain(x) for x in lines]
    start = _input_line(plains)
    if start is None:
        return None
    parts = []
    for j in range(start, len(lines)):
        if j > start and _is_rule(plains[j]):
            break
        text = typed_text(lines[j])
        if j == start:
            text = text.lstrip()
            text = text[len(PROMPT):] if text.startswith(PROMPT) else text
        parts.append(text.replace("\xa0", " "))
    return " ".join(p.strip() for p in parts if p.strip())


def agent_view(ansi_screen):
    """The name of the agent whose view the pane shows instead of the session's main conversation, or None
    when it shows the main conversation (or no input box is on screen).

    The agent list below the input box decides only when it has a `main` row: `main` marked ⏺ means the
    main conversation; `main` marked ◯ means the row marked ⏺ is the one shown. Otherwise (no list, no
    `main` row, or no row marked ⏺) the empty box's faint `Message @<name>…` placeholder decides. The
    same words at normal intensity are a person's draft, not a view."""
    lines = ansi_screen.splitlines()
    plains = [plain(x) for x in lines]
    start = _input_line(plains)
    if start is None:
        return None
    below = start + 1
    while below < len(plains) and not _is_rule(plains[below]):
        below += 1
    rows = [m for m in (AGENT_ROW.match(p) for p in plains[below + 1:]) if m]
    main = next((m.group(1) for m in rows if m.group(2) == "main"), None)
    if main == "⏺":
        return None
    if main == "◯":
        shown = [m.group(2) for m in rows if m.group(1) == "⏺"]
        if shown:
            return shown[0]
    normal, faint = _by_intensity(lines[start])
    normal = normal.replace("\xa0", " ").strip()
    if normal.startswith(PROMPT):
        normal = normal[len(PROMPT):].strip()
    if normal:
        return None             # a person's draft: not a view
    m = VIEW_PLACEHOLDER.match(faint.replace("\xa0", " ").strip())
    return m.group(1) if m else None


def api_error(text, last=15):
    """The last API error line in the bottom of a screen, or None."""
    for line in reversed([plain(x) for x in text.splitlines()][-last:]):
        if API_ERROR.search(line):
            return line.strip()[:200]
    return None
