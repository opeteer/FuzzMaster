#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ANVIL_BIN="${HOME}/.foundry/bin/anvil"

PORT="${1:-8545}"
PID_FILE="${ENV_DIR}/.anvil.pid"
LOG_FILE="${ENV_DIR}/anvil_fair.log"

# Stop existing Anvil if running
"${SCRIPT_DIR}/stop_anvil.sh" > /dev/null 2>&1 || true

echo "[*] Memulai Anvil Simulator dengan Mode Keadilan Penuh (Strict Fair Mode)..."
echo "    - Batas Gas Blok: 30,000,000 (Standar Ethereum)"
echo "    - Base Fee: 1 Gwei (EIP-1559)"
echo "    - Interval Blok: 12 Detik (Ethereum PoS Slot Time)"
echo "    - Hardfork: Cancun"
echo "    - Cheatcode / God-Mode eksternal: Nonaktif"

ANVIL_ARGS=(
    "--port" "${PORT}"
    "--chain-id" "31337"
    "--gas-limit" "30000000"
    "--block-base-fee-per-gas" "1000000000"
    "--block-time" "12"
    "--hardfork" "cancun"
    "--accounts" "10"
    "--balance" "100"
)

nohup "${ANVIL_BIN}" "${ANVIL_ARGS[@]}" > "${LOG_FILE}" 2>&1 &
ANVIL_PID=$!
echo "${ANVIL_PID}" > "${PID_FILE}"

echo "[*] Menunggu node Anvil siap di http://127.0.0.1:${PORT}..."
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
    echo "[✓] Anvil Strict Fair Mode aktif!"
    echo "    - RPC: http://127.0.0.1:${PORT}"
    echo "    - PID: ${ANVIL_PID}"
else
    echo "[!] Gagal menghubungkan ke Anvil. Periksa ${LOG_FILE}"
    exit 1
fi
