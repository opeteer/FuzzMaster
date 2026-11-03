# Pemodelan Contextual Multi-Armed Bandits (CMAB) pada Simulator Anvil

Folder ini (`cmab_anvil/`) berisi reformulasi permasalahan eksplorasi & interaksi *smart contract* dari **Deep Reinforcement Learning (DQN)** pada FuzzMaster menjadi kerangka kerja **Contextual Multi-Armed Bandits (CMAB)** untuk **pengguna cerdas tanpa hak istimewa (*unprivileged intelligent user*)** di atas jaringan lokal **Anvil (Foundry)**.

---

## Arsitektur & Struktur Direktori

Kode yang bersifat **universal** ditempatkan di luar folder agen spesifik (`algorithms/`, `common/`, dan `run_cmab_simulation.py`), sedangkan kode spesifik domain agen ditempatkan di dalam folder **`Agen_Vault_Custody/`**:

```text
cmab_anvil/
├── __init__.py
├── README.md
├── run_cmab_simulation.py              # [UNIVERSAL] Skrip orkestrasi simulasi CMAB pada Anvil
├── algorithms/                         # [UNIVERSAL] Folder algoritma strategi CMAB
│   ├── __init__.py
│   ├── base.py                         # Abstraksi dasar kebijakan CMAB (BaseCMABPolicy)
│   ├── linucb.py                       # Template strategi LinUCB Stasioner (LinUCBTemplate, DisjointLinUCB, HybridLinUCBTemplate)
│   └── discounted_linucb.py            # Template strategi Discounted LinUCB Non-Stasioner (DiscountedLinUCBTemplate, DiscountedLinUCB)
├── common/                             # [UNIVERSAL] Klien RPC & kelas dasar lingkungan tanpa privilege
│   ├── __init__.py
│   ├── anvil_rpc.py                    # UnprivilegedAnvilClient (eth_call, cast send, verifikasi non-owner)
│   └── base_env.py                     # BaseUnprivilegedBanditEnv & StepTransition
└── Agen_Vault_Custody/                 # [AGEN SPESIFIK] Spesialis Kontrak Custody Vault & ERC-20
    ├── __init__.py
    ├── context.py                      # Ekstraktor konteks on-chain publik x_t in R^{10}
    ├── arms.py                         # Katalog 8 lengan (arm) transaksi pengguna biasa
    ├── reward.py                       # Oracle reward deteksi kerentanan Vault & Token
    └── agent.py                        # VaultCustodyEnv & VaultCustodyCMABAgent
```

---

## Cara Menjalankan Simulasi

1. Pastikan simulator Anvil aktif dan kontrak (`VulnerableVault` & `MockToken`) telah ter-deploy dalam mode adil:
   ```bash
   ./anvil_env/scripts/run_fair_simulation.sh
   ```
2. Jalankan simulasi `Agen_Vault_Custody` menggunakan **Discounted LinUCB (`d-linucb`)**:
   ```bash
   python3 cmab_anvil/run_cmab_simulation.py --algorithm d-linucb --gamma 0.85 --rounds 10
   ```
3. Atau jalankan dengan **Disjoint LinUCB Stasioner (`linucb`)**:
   ```bash
   python3 cmab_anvil/run_cmab_simulation.py --algorithm linucb --alpha 1.25 --rounds 8
   ```
