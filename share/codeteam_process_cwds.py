"""The working folders of this machine's processes, read once per idle-clean pass (D599): codeteam-land's clean_idle
skips a tree some process works inside. The same measure as v1's patrol (`_someone_inside`): one lsof call."""
import subprocess


def process_cwds() -> list[str] | None:
    """The paths of `lsof -a -d cwd -Fn`'s name lines, or None when it gives none (lsof missing, or nothing readable).
    lsof exits 1 when it could not read some processes yet still prints the rest, so its lines decide, not its exit
    code."""
    try:
        lsof = subprocess.run(["lsof", "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True)
    except FileNotFoundError:
        return None
    return [line[1:] for line in lsof.stdout.splitlines() if line.startswith("n")] or None
