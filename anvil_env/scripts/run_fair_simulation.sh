#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "⚖️  Menjalankan Pipeline Simulator Anvil (Mode Keadilan Penuh)"
echo "=========================================================="

# 1. Jalankan Anvil dengan batasan ketat (Gas 30M, Base fee 1 Gwei, Slot time 12s, Cancun)
"${SCRIPT_DIR}/start_anvil_fair.sh" 8545

# 2. Deploy dan atur hak agen sebagai pengguna biasa (5 ETH, non-owner)
"${SCRIPT_DIR}/setup_fair_agent.sh" "http://127.0.0.1:8545"

echo ""
echo "[✓] Lingkungan Anvil Mode Adil telah aktif dan terverifikasi!"
