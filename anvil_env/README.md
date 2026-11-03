# Lingkungan Simulator Anvil untuk FuzzMaster

Lingkungan ini mengintegrasikan node **Anvil (Foundry)** sebagai simulator state dan penyedia *initial state* / forking on-chain untuk fuzzer pintar **FuzzMaster (DQN-guided hybrid fuzzer)**.

---

## 🏛️ Arsitektur Integrasi

```
+-------------------------------------------------------------+
|                     ANVIL LOCAL SIMULATOR                   |
|  - JSON-RPC Endpoint: http://127.0.0.1:8545                |
|  - Chain ID: 31337 (atau forking mainnet block tertentu)   |
|  - Deployed: VulnerableVault (10 ETH) & MockToken          |
+-------------------------------------------------------------+
                              ▲
                              │ Lazy Storage Fetching
                              │ (eth_getStorageAt, eth_getCode)
+-----------------------------┴-------------------------------+
|                    FUZZMASTER CORE ENGINE                   |
|  - REVM in-memory execution (No Gas Limit, Fast In-RAM)     |
|  - DQN Agent: 28-dim state -> 16 macro actions -> 8-digits   |
|  - LibAFL Mutator: ABI, Caller, CallValue, Reentrancy       |
|  - Oracles: Selfdestruct, Reentrancy, Invariants            |
+-------------------------------------------------------------+
                              │
                              ▼
           Auto-Generated Exploit PoC (Foundry .t.sol)
```

---

## 📁 Struktur Direktori

```
anvil_env/
├── foundry.toml             # Konfigurasi Foundry untuk Anvil & FuzzMaster
├── src/
│   ├── VulnerableVault.sol  # Kontrak uji dengan bug Reentrancy, Solvency Invariant, & Selfdestruct
│   └── MockToken.sol        # Token ERC20 mock untuk pengujian aset
├── script/
│   └── Deploy.s.sol         # Skrip otomatis deploy ke Anvil & inisialisasi dana 10 ETH
├── test/
│   └── VaultTest.t.sol      # Unit test Foundry standar
├── scripts/
│   ├── start_anvil.sh       # Menjalankan Anvil di background & memantau health RPC
│   ├── stop_anvil.sh        # Menghentikan proses Anvil
│   ├── deploy_contracts.sh  # Menjalankan forge script deploy ke Anvil
│   ├── export_artifacts.py  # Ekspor artefak ABI/BIN & konfigurasi untuk FuzzMaster
│   └── run_anvil_simulation.sh # Otomasi 1-klik untuk seluruh pipeline
└── fuzz_artifacts/          # Artefak (.abi, .bin, builder_artifacts.json) siap pakai
```

---

## 🚀 Cara Penggunaan

### 1. Menjalankan 1-Klik (Otomatis)
Untuk menjalankan simulator Anvil, men-deploy kontrak, dan menyiapkan seluruh artefak:
```bash
./anvil_env/scripts/run_anvil_simulation.sh
```

### 2. Menghentikan Simulator Anvil
```bash
./anvil_env/scripts/stop_anvil.sh
```

### 3. Menjalankan Fuzzing dengan FuzzMaster

#### Pilihan A: Mode On-Chain Fork (Memfuzing kontrak yang aktif di Anvil)
```bash
cargo run --release --bin ityfuzz -- evm \
    -t "$(cat anvil_env/deployed_addresses.json | jq -r .VulnerableVault)" \
    -u http://127.0.0.1:8545 \
    -i 31337 \
    --chain-type local \
    --builder-artifacts-file anvil_env/fuzz_artifacts/builder_artifacts.json
```

#### Pilihan B: Mode Standalone Fuzzing (Menggunakan ABI & Deployed Bytecode)
```bash
cargo run --release --bin ityfuzz -- evm -t "anvil_env/fuzz_artifacts/*"
```

---

## 🌐 Simulasi dengan Forking Jaringan Nyata (Mainnet / Arbitrum / BSC)

Jika Anda ingin menguji kontrak yang bergantung pada protokol DeFi on-chain nyata (misalnya Uniswap, Aave, Curve), cukup jalankan `start_anvil.sh` dengan parameter RPC URL:
```bash
./anvil_env/scripts/start_anvil.sh 8545 "https://eth.llamarpc.com"
```
Anvil akan menyalin seluruh state mainnet pada blok terbaru, dan FuzzMaster dapat langsung memfuzing kontrak di atas state mainnet tersebut!
