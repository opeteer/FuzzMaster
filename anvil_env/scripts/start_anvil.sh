#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANVIL_BIN="${HOME}/.foundry/bin/anvil"

PORT="${1:-8545}"
FORK_URL="${2:-}"
PID_FILE="${ENV_DIR}/.anvil.pid"
LOG_FILE="${ENV_DIR}/anvil.log"

if [ ! -x "${ANVIL_BIN}" ]; then
    echo "[!] Error: Anvil binary not found at ${ANVIL_BIN}"
    exit 1
fi

# Check if Anvil is already running
if [ -f "${PID_FILE}" ]; then
    OLD_PID=$(cat "${PID_FILE}")
    if ps -p "${OLD_PID}" > /dev/null 2>&1; then
        echo "[*] Anvil is already running with PID ${OLD_PID} on port ${PORT}"
        exit 0
    else
        rm -f "${PID_FILE}"
    fi
fi

echo "[*] Starting Anvil simulator on port ${PORT}..."
ANVIL_ARGS=("--port" "${PORT}" "--chain-id" "31337" "--accounts" "10" "--balance" "10000")

if [ -n "${FORK_URL}" ]; then
    echo "[*] Forking remote state from: ${FORK_URL}"
    ANVIL_ARGS+=("--fork-url" "${FORK_URL}")
fi

nohup "${ANVIL_BIN}" "${ANVIL_ARGS[@]}" > "${LOG_FILE}" 2>&1 &
ANVIL_PID=$!
echo "${ANVIL_PID}" > "${PID_FILE}"

echo "[*] Waiting for Anvil RPC to be ready on http://127.0.0.1:${PORT}..."
READY=0
for i in {1..30}; do
    if curl -s -X POST -H "Content-Type: application/json" \
         --data '{"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}' \
         "http://127.0.0.1:${PORT}" > /dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 0.5
done

if [ "${READY}" -eq 1 ]; then
    echo "[✓] Anvil node is active and ready!"
    echo "    - RPC URL: http://127.0.0.1:${PORT}"
    echo "    - PID: ${ANVIL_PID}"
    echo "    - Logs: ${LOG_FILE}"
else
    echo "[!] Failed to connect to Anvil within 15 seconds. Check ${LOG_FILE}"
    kill "${ANVIL_PID}" 2>/dev/null || true
    rm -f "${PID_FILE}"
    exit 1
fi
