#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FORGE_BIN="${HOME}/.foundry/bin/forge"

RPC_URL="${1:-http://127.0.0.1:8545}"
OUTPUT_FILE="${ENV_DIR}/deployed_addresses.json"

cd "${ENV_DIR}"

echo "[*] Deploying contracts to Anvil simulator (${RPC_URL})..."
"${FORGE_BIN}" script script/Deploy.s.sol:DeployScript \
    --rpc-url "${RPC_URL}" \
    --broadcast \
    --slow

# Locate latest run broadcast JSON file
LATEST_RUN=$(find broadcast/Deploy.s.sol/31337/run-latest.json 2>/dev/null || true)

if [ -f "${LATEST_RUN}" ]; then
    echo "[*] Extracting deployed contract addresses from ${LATEST_RUN}..."
    python3 -c "
import json
with open('${LATEST_RUN}') as f:
    data = json.load(f)

deployed = {}
for receipt in data.get('receipts', []):
    contract_address = receipt.get('contractAddress')
    if contract_address:
        # Match with transaction
        for tx in data.get('transactions', []):
            if tx.get('hash') == receipt.get('transactionHash'):
                cname = tx.get('contractName', 'Unknown')
                deployed[cname] = contract_address

with open('${OUTPUT_FILE}', 'w') as out:
    json.dump(deployed, out, indent=2)

print('[✓] Deployment summary saved to ${OUTPUT_FILE}:')
for k, v in deployed.items():
    print(f'    - {k}: {v}')
"
else
    echo "[!] Warning: Broadcast file not found, check forge script output."
fi
