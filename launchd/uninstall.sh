#!/usr/bin/env bash
# Unloads and removes the eConsult monitor LaunchAgent. Leaves data/ intact.
set -euo pipefail

LABEL="com.econsult.window-monitor"
TARGET="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if [[ -f "${TARGET}" ]]; then
    launchctl unload "${TARGET}" 2>/dev/null || true
    rm -f "${TARGET}"
    echo "Removed ${LABEL}. Observed data in data/ is untouched."
else
    echo "${LABEL} is not installed."
fi
