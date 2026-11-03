#!/usr/bin/env python3
import json
import os
from pathlib import Path

ENV_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = ENV_DIR / "out"
DEPLOYED_FILE = ENV_DIR / "deployed_addresses.json"
EXPORT_DIR = ENV_DIR / "fuzz_artifacts"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)

if not DEPLOYED_FILE.exists():
    print(f"[!] {DEPLOYED_FILE} not found. Run deploy_contracts.sh first!")
    exit(1)

with open(DEPLOYED_FILE) as f:
    deployed = json.load(f)

print("[*] Generating FuzzMaster artifacts from Foundry compilation...")

builder_artifacts = []

for contract_name, address in deployed.items():
    # Foundry output artifact path: out/<Contract>.sol/<Contract>.json
    artifact_json_path = OUT_DIR / f"{contract_name}.sol" / f"{contract_name}.json"
    if not artifact_json_path.exists():
        print(f"[-] Artifact not found for {contract_name} at {artifact_json_path}")
        continue

    with open(artifact_json_path) as f:
        artifact = json.load(f)

    abi = artifact.get("abi", [])
    bytecode_obj = artifact.get("bytecode", {})
    deployed_bytecode_obj = artifact.get("deployedBytecode", {})

    bytecode = bytecode_obj.get("object", "").removeprefix("0x")
    deployed_bytecode = deployed_bytecode_obj.get("object", "").removeprefix("0x")

    # 1. Export standard .abi and .bin files for Glob/Offline mode
    abi_path = EXPORT_DIR / f"{contract_name}.abi"
    bin_path = EXPORT_DIR / f"{contract_name}.bin"

    with open(abi_path, "w") as f:
        json.dump(abi, f, indent=2)

    with open(bin_path, "w") as f:
        f.write(deployed_bytecode or bytecode)

    print(f"[✓] {contract_name}:")
    print(f"    - Address: {address}")
    print(f"    - ABI: {abi_path}")
    print(f"    - BIN: {bin_path}")

    # 2. Prepare builder artifact entry
    builder_artifacts.append({
        "contracts": {
            f"src/{contract_name}.sol:{contract_name}": {
                "abi": json.dumps(abi),
                "deploy_bytecode": bytecode,
                "deployed_bytecode": deployed_bytecode,
                "source_map": artifact.get("sourceMap", ""),
                "source_map_replacements": []
            }
        },
        "sources": {
            f"src/{contract_name}.sol": ""
        }
    })

builder_file = EXPORT_DIR / "builder_artifacts.json"
with open(builder_file, "w") as f:
    json.dump(builder_artifacts, f, indent=2)

print(f"[✓] Builder artifacts saved to {builder_file}")

# Generate execution summary
vault_addr = deployed.get("VulnerableVault", "")
print("\n" + "="*70)
print("PANDUAN MENJALANKAN FUZZMASTER PADA SIMULATOR ANVIL:")
print("="*70)
print("\n1. Mode Anvil On-Chain Fork (Memfuzing kontrak yang sedang aktif di Anvil):")
print(f"cargo run --release --bin ityfuzz -- evm \\")
print(f"    -t '{vault_addr}' \\")
print(f"    -u http://127.0.0.1:8545 \\")
print(f"    -i 31337 \\")
print(f"    --chain-type local \\")
print(f"    --builder-artifacts-file {builder_file}")

print("\n2. Mode Standalone Fuzzing (Menggunakan ABI & BIN yang diekstrak dari Anvil):")
print(f"cargo run --release --bin ityfuzz -- evm -t '{EXPORT_DIR}/*'")
print("="*70)
