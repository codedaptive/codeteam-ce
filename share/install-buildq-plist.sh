#!/bin/bash
# Fill in share/codeteam-buildq.plist for this checkout and this user, then install and load it as a launchd job.
#   share/install-buildq-plist.sh            write ~/Library/LaunchAgents/<prefix>.codeteam-buildq.plist and load it
#   share/install-buildq-plist.sh --print    print the filled-in plist; install nothing
# Settings: CODETEAM_LAUNCHD_PREFIX (default com.codeteam), CODETEAM_PYTHON (default: python3 on PATH, absolute).
set -eu
CT="$(cd "$(dirname "$0")/.." && pwd -P)"
PREFIX="${CODETEAM_LAUNCHD_PREFIX:-com.codeteam}"
PY="${CODETEAM_PYTHON:-$(command -v python3)}"
case "$PY" in /*) ;; *) PY="$(command -v "$PY")" ;; esac
render() {
  sed -e "s|__PREFIX__|$PREFIX|g" -e "s|__PYTHON__|$PY|g" -e "s|__CODETEAM_HOME__|$CT|g" -e "s|__HOME__|$HOME|g" \
    "$CT/share/codeteam-buildq.plist"
}
if [ "${1:-}" = "--print" ]; then render; exit 0; fi
LABEL="$PREFIX.codeteam-buildq"
DEST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$CT/run" "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
render > "$DEST"
plutil -lint "$DEST" >/dev/null
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "installed $LABEL ($DEST)"
