#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "=========================================================="
echo "🚀 FuzzMaster - Anvil Simulator Environment Orchestrator"
echo "=========================================================="

# 1. Start Anvil
"${SCRIPT_DIR}/start_anvil.sh" 8545

# 2. Build & Deploy Contracts
"${SCRIPT_DIR}/deploy_contracts.sh" "http://127.0.0.1:8545"

# 3. Export Artifacts for FuzzMaster
python3 "${SCRIPT_DIR}/export_artifacts.py"

echo ""
echo "[✓] Lingkungan Simulator Anvil siap digunakan sepenuhnya!"
