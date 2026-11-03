#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${ENV_DIR}/.anvil.pid"

if [ -f "${PID_FILE}" ]; then
    PID=$(cat "${PID_FILE}")
    if ps -p "${PID}" > /dev/null 2>&1; then
        echo "[*] Stopping Anvil (PID ${PID})..."
        kill "${PID}" 2>/dev/null || true
        sleep 1
        if ps -p "${PID}" > /dev/null 2>&1; then
            kill -9 "${PID}" 2>/dev/null || true
        fi
        echo "[✓] Anvil stopped."
    else
        echo "[*] Anvil process ${PID} is not running."
    fi
    rm -f "${PID_FILE}"
else
    # Fallback to pkill anvil
    pkill -f "anvil.*8545" 2>/dev/null || true
    echo "[✓] No active Anvil PID file found."
fi
