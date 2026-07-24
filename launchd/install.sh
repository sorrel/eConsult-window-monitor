#!/usr/bin/env bash
# Installs the eConsult monitor LaunchAgent for the current user.
# Substitutes the real repo path and uv path into the committed template so no
# machine path is ever stored in git.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.econsult.window-monitor"
TEMPLATE="${REPO_DIR}/launchd/${LABEL}.plist"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET="${TARGET_DIR}/${LABEL}.plist"

if ! command -v uv >/dev/null 2>&1; then
    echo "error: 'uv' not found on PATH. Install uv first." >&2
    exit 1
fi

# Create/refresh the project venv now, in this interactive shell where uv has
# network access. The LaunchAgent then runs the venv's Python directly and never
# invokes uv at runtime — so a locked-down launchd context (e.g. Little Snitch
# blocking uv's index access) cannot hang the daemon.
( cd "${REPO_DIR}" && uv sync )

if [[ ! -x "${REPO_DIR}/.venv/bin/python" ]]; then
    echo "error: ${REPO_DIR}/.venv/bin/python missing after 'uv sync'." >&2
    exit 1
fi

mkdir -p "${TARGET_DIR}" "${REPO_DIR}/data"

sed -e "s#__REPO_DIR__#${REPO_DIR}#g" \
    "${TEMPLATE}" > "${TARGET}"

# Reload cleanly if already present.
launchctl unload "${TARGET}" 2>/dev/null || true
launchctl load "${TARGET}"

echo "Loaded ${LABEL}."
echo "  plist:  ${TARGET}"
echo "  logs:   ${REPO_DIR}/data/daemon.{out,err}.log"
echo "  data:   ${REPO_DIR}/data/observations.jsonl"
echo "Check status: launchctl list | grep econsult"
