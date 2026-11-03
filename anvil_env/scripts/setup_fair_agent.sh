#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
CAST_BIN="${HOME}/.foundry/bin/cast"
RPC_URL="${1:-http://127.0.0.1:8545}"

# FuzzMaster default attacker/agent address
AGENT_ADDRESS="0x8EF508Aca04B32Ff3ba5003177cb18BfA6Cd79dd"
# Deployer address (Anvil account #0)
DEPLOYER_ADDRESS="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

echo "=========================================================="
echo "⚖️  Konfigurasi Kedudukan Agen Adil (Strict Fair Standing)"
echo "=========================================================="

# 1. Deploy contracts via deployer account
echo "[1] Melakukan deployment kontrak menggunakan identitas terpisah (Owner: ${DEPLOYER_ADDRESS})..."
"${SCRIPT_DIR}/deploy_contracts.sh" "${RPC_URL}"

DEPLOYED_FILE="${ENV_DIR}/deployed_addresses.json"
VAULT_ADDRESS=$(python3 -c "import json; print(json.load(open('${DEPLOYED_FILE}'))['VulnerableVault'])")
TOKEN_ADDRESS=$(python3 -c "import json; print(json.load(open('${DEPLOYED_FILE}'))['MockToken'])")

# 2. Set strict finite balance for the agent (5 ETH = 0x4563918244f40000)
echo "[2] Membatasi modal awal agen ke saldo wajar (5 ETH)..."
"${CAST_BIN}" rpc anvil_setBalance "${AGENT_ADDRESS}" "0x4563918244F40000" --rpc-url "${RPC_URL}" > /dev/null

AGENT_BAL=$("${CAST_BIN}" balance "${AGENT_ADDRESS}" --rpc-url "${RPC_URL}")
echo "    - Alamat Agen: ${AGENT_ADDRESS}"
echo "    - Saldo Modal Agen: $(python3 -c "print(int('${AGENT_BAL}') / 1e18)") ETH"

# 3. Verifikasi ketiadaan hak istimewa (Privilege Verification)
echo "[3] Memverifikasi batasan hak akses agen pada smart contract..."
VAULT_OWNER=$("${CAST_BIN}" call "${VAULT_ADDRESS}" "owner()(address)" --rpc-url "${RPC_URL}")

if [ "${VAULT_OWNER,,}" == "${AGENT_ADDRESS,,}" ]; then
    echo "[!] Kesalahan: Agen terdaftar sebagai owner!"
    exit 1
else
    echo "    - Owner Kontrak Vault: ${VAULT_OWNER} (Terverifikasi BUKAN agen)"
    echo "    - Status Agen: Pengguna Publik Biasa (Unprivileged User)"
fi

# 4. Export artifacts for FuzzMaster
echo "[4] Mengekspor artefak kompilasi untuk FuzzMaster..."
python3 "${SCRIPT_DIR}/export_artifacts.py" > /dev/null

BUILDER_FILE="${ENV_DIR}/fuzz_artifacts/builder_artifacts.json"

echo ""
echo "=========================================================="
echo "✓ LINGKUNGAN SIMULATOR ANVIL BERKEDUDUKAN ADIL TELAH SIAP"
echo "=========================================================="
echo "Perintah eksekusi FuzzMaster dalam mode adil (Strict Fair):"
echo ""
cat <<EOF
cargo run --release --bin ityfuzz -- evm \\
    -t '${VAULT_ADDRESS}' \\
    -u ${RPC_URL} \\
    -i 31337 \\
    --chain-type local \\
    --flashloan false \\
    --sha3-bypass false \\
    --concolic false \\
    --concolic-caller false \\
    --builder-artifacts-file ${BUILDER_FILE}
EOF
echo "=========================================================="
