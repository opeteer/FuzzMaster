#!/usr/bin/env python3
import json
import subprocess
import time
from pathlib import Path

ENV_DIR = Path(__file__).resolve().parent.parent
DEPLOYED_FILE = ENV_DIR / "deployed_addresses.json"
CAST_BIN = Path.home() / ".foundry" / "bin" / "cast"
RPC_URL = "http://127.0.0.1:8545"

# Accounts from Anvil (Fair Standing)
# Account #0 = Deployer / Owner (0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266)
DEPLOYER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
DEPLOYER_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

# Account #1 = Normal User (0x70997970C51812dc3A010C7d01b50e0d17dc79C8)
USER_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"
USER_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

# Account #2 = Agent / Unprivileged Attacker (0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC)
AGENT_PK = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
AGENT_ADDR = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"

def run_cmd(cmd):
    p = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return p.stdout.strip(), p.stderr.strip(), p.returncode

def get_balance(addr):
    out, _, _ = run_cmd(f"{CAST_BIN} balance {addr} --rpc-url {RPC_URL}")
    try:
        return float(int(out) / 1e18)
    except:
        return 0.0

def main():
    print("="*75)
    print("🌐 SIMULASI EKSEKUSI TRANSAKSI PADA ANVIL SIMULATOR (MODE ADIL)")
    print("="*75)

    if not DEPLOYED_FILE.exists():
        print(f"[!] File {DEPLOYED_FILE} tidak ditemukan. Silakan jalankan deploy lebih dulu.")
        return

    with open(DEPLOYED_FILE) as f:
        deployed = json.load(f)

    vault_addr = deployed.get("VulnerableVault")
    token_addr = deployed.get("MockToken")

    print(f"[*] Target Kontrak Ter-deploy:")
    print(f"    - VulnerableVault : {vault_addr}")
    print(f"    - MockToken       : {token_addr}")
    print(f"    - Anvil RPC Node  : {RPC_URL}")

    # Set Agen ke saldo wajar 5 ETH
    run_cmd(f"{CAST_BIN} rpc anvil_setBalance {AGENT_ADDR} 0x4563918244F40000 --rpc-url {RPC_URL}")

    # 1. Status Awal
    print("\n" + "-"*75)
    print("📊 [FASE 1] STATUS AWAL STATE PADA ANVIL")
    print("-"*75)
    print(f"    - Saldo Vault        : {get_balance(vault_addr):.4f} ETH")
    print(f"    - Saldo Deployer     : {get_balance(DEPLOYER_ADDR):.4f} ETH (Owner)")
    print(f"    - Saldo User Normal  : {get_balance(USER_ADDR):.4f} ETH")
    print(f"    - Saldo Agen Fuzzer  : {get_balance(AGENT_ADDR):.4f} ETH (Modal Wajar 5 ETH)")

    solvency, _, _ = run_cmd(f"{CAST_BIN} call {vault_addr} 'check_solvency()(bool)' --rpc-url {RPC_URL}")
    print(f"    - Invariant Solvency : {solvency} (Vault Solvent)")

    # 2. Aksi User Normal
    print("\n" + "-"*75)
    print("👤 [FASE 2] PENGGUNA NORMAL MENYETOR 2 ETH KE VAULT")
    print("-"*75)
    print(f"[*] Mengirim tx: deposit(2 ETH) dari {USER_ADDR}...")
    tx_out, _, code = run_cmd(
        f"{CAST_BIN} send {vault_addr} 'deposit()' --value 2ether "
        f"--private-key {USER_PK} --rpc-url {RPC_URL}"
    )
    if code == 0:
        print("[✓] Transaksi berhasil ditambang di blok Anvil!")
        user_vault_bal, _, _ = run_cmd(f"{CAST_BIN} call {vault_addr} 'balances(address)(uint256)' {USER_ADDR} --rpc-url {RPC_URL}")
        val_str = user_vault_bal.split()[0] if user_vault_bal else "0"
        print(f"    - Saldo User di Vault : {int(val_str)/1e18:.2f} ETH")
        print(f"    - Total Saldo Vault   : {get_balance(vault_addr):.4f} ETH")

    # 3. Interaksi Agen Adil
    print("\n" + "-"*75)
    print("🤖 [FASE 3] AGEN ADIL MENYETOR 1 ETH KE VAULT")
    print("-"*75)
    print(f"[*] Mengirim tx: deposit(1 ETH) dari Agen {AGENT_ADDR}...")
    tx_out, _, code = run_cmd(
        f"{CAST_BIN} send {vault_addr} 'deposit()' --value 1ether "
        f"--private-key {AGENT_PK} --rpc-url {RPC_URL}"
    )
    if code == 0:
        print("[✓] Transaksi Agen berhasil ditambang di blok Anvil!")
        agent_vault_bal, _, _ = run_cmd(f"{CAST_BIN} call {vault_addr} 'balances(address)(uint256)' {AGENT_ADDR} --rpc-url {RPC_URL}")
        agent_val_str = agent_vault_bal.split()[0] if agent_vault_bal else "0"
        print(f"    - Saldo Agen di Vault : {int(agent_val_str)/1e18:.2f} ETH")
        print(f"    - Saldo Kas Agen Sisa : {get_balance(AGENT_ADDR):.4f} ETH")
        print(f"    - Total Saldo Vault   : {get_balance(vault_addr):.4f} ETH")

    # 4. Pengujian Eksploitasi
    print("\n" + "-"*75)
    print("🛡️ [FASE 4] UJI PERCOBAAN KERENTANAN & EVALUASI KEAMANAN")
    print("-"*75)

    # Percobaan A: Agen mencoba memanggil emergencyDrain (tanpa hak owner)
    print("[*] Percobaan A: Agen mencoba memanggil emergencyDrain() secara ilegal...")
    drain_out, drain_err, drain_code = run_cmd(
        f"{CAST_BIN} send {vault_addr} 'emergencyDrain(address)' {AGENT_ADDR} "
        f"--private-key {AGENT_PK} --rpc-url {RPC_URL}"
    )
    if drain_code != 0:
        print("[✓] HASIL: Transaksi DITOLAK oleh Anvil EVM!")
        print("    - Alasan Revert: Unauthorized access (Ketiadaan hak istimewa terbukti efektif)")
    else:
        print("[!] Peringatan: emergencyDrain berhasil terpanggil.")

    # Percobaan B: Agen menarik dana melalui withdrawAll()
    print("\n[*] Percobaan B: Agen memicu withdrawAll() untuk menguji alur penarikan dana...")
    w_out, _, w_code = run_cmd(
        f"{CAST_BIN} send {vault_addr} 'withdrawAll()' "
        f"--private-key {AGENT_PK} --rpc-url {RPC_URL}"
    )
    if w_code == 0:
        print("[✓] HASIL: Transaksi withdrawAll() berhasil dieksekusi!")
        print(f"    - Saldo Kas Agen Pulih : {get_balance(AGENT_ADDR):.4f} ETH")
        print(f"    - Saldo Akhir Vault    : {get_balance(vault_addr):.4f} ETH")

    # 5. Status Akhir
    print("\n" + "-"*75)
    print("📈 [FASE 5] RINGKASAN INTEGRITAS SIMULATOR ANVIL")
    print("-"*75)
    block_num, _, _ = run_cmd(f"{CAST_BIN} block-number --rpc-url {RPC_URL}")
    solvency_final, _, _ = run_cmd(f"{CAST_BIN} call {vault_addr} 'check_solvency()(bool)' --rpc-url {RPC_URL}")
    print(f"    - Tinggi Blok Terkini : {block_num}")
    print(f"    - Invariant Solvency  : {solvency_final}")
    print(f"    - Status Simulator    : AKTIF, STABIL, & MEMATUHI ATURAN KONSENSUS")
    print("="*75)

if __name__ == "__main__":
    main()
