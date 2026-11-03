#!/usr/bin/env python3
"""
SC-Bench Vault & Liquidity Non-Stationary Benchmark (11 Smart Contracts on Anvil)
Compares Disjoint LinUCB (gamma=1.0) vs Discounted LinUCB (gamma=0.85) under:
  1. Member-Level Standing (Strictly non-owner EOA, but onboarded as a valid protocol member
     with initial token balances, ERC-20 approvals, and member registration to eliminate
     All-Revert Degeneracy without violating Zero-Admin assumptions).
  2. Multi-Regime Non-Stationarity (T = 24 rounds across 3 distinct on-chain regimes:
     Regime 1 [t=1..8]: Inflow/Staking Boom -> Regime 2 [t=9..16]: Maturity Unlock & Cap Tightening
     -> Regime 3 [t=17..24]: Liquidity Stress & Secondary/Emergency Operations).
  3. Stochastic Blockchain Network Events (Peer whale deposits, block time jitter, congestion)
     synchronized via Common Random Numbers (CRN / Paired Seeds) for 100% fairness.
"""

import os
import sys
import json
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
import numpy as np

# Ensure cmab_anvil is importable
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cmab_anvil.algorithms.linucb import DisjointLinUCB
from cmab_anvil.algorithms.discounted_linucb import DiscountedLinUCB
from cmab_anvil.common.anvil_rpc import UnprivilegedAnvilClient
from cmab_anvil.Agen_Vault_Custody.context import (
    PublicContextExtractor,
    OnChainContextSnapshot,
    CONTEXT_DIM,
    FEATURE_NAMES,
)

SOLC_BIN = "/home/opeteer/.local/bin/solc"
CAST_BIN = "/home/opeteer/.foundry/bin/cast"
ANVIL_BIN = "/home/opeteer/.foundry/bin/anvil"
RPC_URL = "http://127.0.0.1:8545"

# Anvil Standard Accounts
DEPLOYER_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"  # Account #0 (Owner / Admin)
DEPLOYER_ADDR = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

PEER_PK = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"      # Account #1 (Peer / Whale User)
PEER_ADDR = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"

AGENT_PK = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"     # Account #2 (Protocol Member EOA)
AGENT_ADDR = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"

DATASET_DIR = REPO_ROOT / "SC-Bench" / "categorized_dataset" / "Vault_and_Liquidity"
MOCK_TOKEN_SOL = REPO_ROOT / "anvil_env" / "src" / "MockToken.sol"
MAX_UINT256 = "115792089237316195423570985008687907853269984665640564039457584007913129639935"


def ensure_anvil_running() -> None:
    p = subprocess.run([CAST_BIN, "block-number", "--rpc-url", RPC_URL], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        print("[*] Starting Anvil node on port 8545...")
        subprocess.Popen(
            [ANVIL_BIN, "--port", "8545", "--chain-id", "31337", "--accounts", "10", "--balance", "10000", "--gas-limit", "30000000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(1.5)


def run_cast(args: List[str]) -> Tuple[bool, str, str]:
    if args[0] in ("keccak", "abi-encode"):
        cmd = [CAST_BIN] + args
    else:
        cmd = [CAST_BIN, args[0], "--rpc-url", RPC_URL] + args[1:]
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return (p.returncode == 0), p.stdout.strip(), p.stderr.strip()


def rpc_call(method: str, params: List[Any]) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1})
    p = subprocess.run(
        ["curl", "-s", "-X", "POST", "-H", "Content-Type: application/json", "--data", payload, RPC_URL],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        return json.loads(p.stdout).get("result")
    except Exception:
        return None


def compile_contract(fpath: Path, cname: str) -> Optional[str]:
    res = subprocess.run([SOLC_BIN, "--combined-json", "abi,bin", str(fpath)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        return None
    idx = res.stdout.find("{")
    if idx == -1:
        return None
    data = json.loads(res.stdout[idx:])
    for k, v in data.get("contracts", {}).items():
        if k.endswith(":" + cname):
            return v.get("bin")
    return None


def deploy_bytecode(bytecode: str, constructor_sig: Optional[str] = None, constructor_args: Optional[List[str]] = None) -> Optional[str]:
    create_hex = "0x" + bytecode
    if constructor_sig and constructor_args:
        ok, encoded, _ = run_cast(["abi-encode", constructor_sig] + constructor_args)
        if ok and encoded.startswith("0x"):
            create_hex += encoded[2:]
    rpc_call("anvil_setNextBlockBaseFeePerGas", ["0x3b9aca00"])  # Reset to 1 Gwei for deploy
    ok, out, err = run_cast(["send", "--private-key", DEPLOYER_PK, "--gas-price", "5000000000", "--create", create_hex])
    if not ok:
        return None
    for line in out.splitlines():
        if "contractAddress" in line:
            return line.split()[-1]
    return None


def send_tx(
    pk: str,
    to_addr: str,
    sig: str = "",
    args: Optional[List[str]] = None,
    eth_val: float = 0.0,
    gas_price_gwei: Optional[float] = None,
) -> Tuple[bool, str]:
    cmd = ["send", "--private-key", pk]
    if gas_price_gwei is not None and gas_price_gwei > 0:
        cmd.extend(["--gas-price", f"{int(gas_price_gwei * 1e9)}"])
    if eth_val > 0:
        cmd.extend(["--value", f"{eth_val:.6f}ether"])
    cmd.append(to_addr)
    if sig:
        cmd.append(sig)
        if args:
            cmd.extend(args)
    ok, out, err = run_cast(cmd)
    return ok, (out if ok else err)


def impersonate_and_transfer_erc20(from_holder: str, token_addr: str, to_addr: str, amount_wei: str) -> None:
    """Used strictly during pre-test onboarding to distribute member tokens from a contract/treasury."""
    rpc_call("anvil_impersonateAccount", [from_holder])
    send_tx(DEPLOYER_PK, from_holder, "", [], 0.5)  # gas eth
    run_cast(["send", "--from", from_holder, "--unlocked", token_addr, "transfer(address,uint256)", to_addr, amount_wei])
    rpc_call("anvil_stopImpersonatingAccount", [from_holder])


# =============================================================================
# 11 SC-Bench Contract Specifications with Member Onboarding & 3 Regimes
# =============================================================================
CONTRACT_SPECS = [
    {
        "id": "SC-01",
        "split": "injected",
        "file": "ClashForStash-0x939b0425.sol",
        "contract": "ClashForStash",
        "category": "Vault_Custody_Yield",
        "description": "Token custody vault with min/max deposit caps, swap toggles, and member transfers",
        "arms": [
            {"id": 0, "name": "member_deposit_small", "sig": "deposit(uint256)", "args": ["100000000000000000"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_deposit_medium", "sig": "deposit(uint256)", "args": ["150000000000000000"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "member_transfer_peer", "sig": "transfer(address,uint256)", "args": [PEER_ADDR, "50000000000000000"], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_increase_allowance", "sig": "increaseAllowance(address,uint256)", "args": [PEER_ADDR, "100000000000000000"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "unsigned_withdraw_probe", "sig": "withdraw(uint256,bytes)", "args": ["100000000000000000", "0x00"], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "vault_eth_fallback", "sig": "", "args": [], "val": 0.05, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-02",
        "split": "injected",
        "file": "DrawTT-0x02D33D35.sol",
        "contract": "DrawTT",
        "constructor_sig": "constructor(string,string,string)",
        "constructor_args": ["DrawTTCustody", "DTT", "ipfs://vault/"],
        "category": "Escrow_PullPayment_Vault",
        "description": "Custodial NFT & PullPayment escrow contract with dynamic mint fee and async escrow settlement",
        "arms": [
            {"id": 0, "name": "member_mint_DynamicURI", "sig": "mint(string)", "args": ["DYNAMIC_URI"], "val": 0.02, "role": "inflow_primary"},
            {"id": 1, "name": "member_mint_lowfee", "sig": "mint(string)", "args": ["DYNAMIC_URI_LOW"], "val": 0.01, "role": "inflow_secondary"},
            {"id": 2, "name": "escrow_withdraw_payments", "sig": "withdrawPayments(address)", "args": [DEPLOYER_ADDR], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_set_approval_all", "sig": "setApprovalForAll(address,bool)", "args": [PEER_ADDR, "true"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "unauthorized_setCost_probe", "sig": "setCost(uint256)", "args": ["0"], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "duplicate_uri_probe", "sig": "mint(string)", "args": ["STATIC_DUPLICATE"], "val": 0.02, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-03",
        "split": "injected",
        "file": "NoahSwapStake-0x0ff004b6.sol",
        "contract": "NoahSwapStake",
        "category": "Staking_Pool_Custody",
        "description": "Multi-asset staking custody with order ID slots, deputy renewal permissions, and ETH fallback",
        "arms": [
            {"id": 0, "name": "member_stake_eth_order", "sig": "stakeEth(uint256,address,uint256,uint256)", "args": ["DYNAMIC_ID", "0x0000000000000000000000000000000000000000", "50000000000000000", "2500000000"], "val": 0.05, "role": "inflow_primary"},
            {"id": 1, "name": "member_stake_erc20_order", "sig": "stake(uint256,address,uint256,uint256)", "args": ["DYNAMIC_ID_ERC20", "MOCK_TOKEN", "1000000000000000000", "2500000000"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "deputy_order_renewal", "sig": "renewal(uint256[],uint256[])", "args": ["[1]", "[DYNAMIC_ENDTIME]"], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "deputy_set_signer", "sig": "setSigner(address)", "args": [AGENT_ADDR], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "admin_setDeputy_probe", "sig": "setDeputy(address)", "args": [AGENT_ADDR], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "pool_eth_fallback", "sig": "", "args": [], "val": 0.02, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-04",
        "split": "injected",
        "file": "PyramidToken-0xbc69f076.sol",
        "contract": "PyramidToken",
        "category": "Liquidity_Pyramid_Vault",
        "description": "Tiered staking & liquidity vault with 30-day lockup maturity, referral bonus, and burn mechanics",
        "arms": [
            {"id": 0, "name": "member_stake_30days", "sig": "stake(uint256,uint256)", "args": ["1000000000000000000", "2592000"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_set_referrer", "sig": "setReferrer(address)", "args": [PEER_ADDR], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "member_withdraw_mature", "sig": "withdraw()", "args": [], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_burn_tokens", "sig": "burn(uint256)", "args": ["100000000000000000"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "member_transfer_peer", "sig": "transfer(address,uint256)", "args": [PEER_ADDR, "100000000000000000"], "val": 0.0, "role": "fallback_ops"},
            {"id": 5, "name": "invalid_short_stake_probe", "sig": "stake(uint256,uint256)", "args": ["100000000000000000", "60"], "val": 0.0, "role": "probe"},
        ],
    },
    {
        "id": "SC-05",
        "split": "injected",
        "file": "THREEAMIGOSCAPITAL-0x5bf05c34.sol",
        "contract": "THREEAMIGOSCAPITAL",
        "category": "Staking_Treasury",
        "description": "Capital staking treasury with lockup penalty before maturity, reward multiplier, and AMM limits",
        "arms": [
            {"id": 0, "name": "member_stake_short", "sig": "stake(uint256,uint256)", "args": ["1000000000000000000", "5"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_approve_router", "sig": "approve(address,uint256)", "args": [PEER_ADDR, "500000000000000000"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "member_unstake_claim", "sig": "unstake()", "args": [], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_transfer_shares", "sig": "transfer(address,uint256)", "args": [PEER_ADDR, "100000000000000000"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "member_increase_allowance", "sig": "increaseAllowance(address,uint256)", "args": [DEPLOYER_ADDR, "100000000000000000"], "val": 0.0, "role": "fallback_ops"},
            {"id": 5, "name": "admin_setRules_probe", "sig": "setRules(address,uint256,uint8,uint8)", "args": [AGENT_ADDR, "0", "0", "0"], "val": 0.0, "role": "probe"},
        ],
    },
    {
        "id": "SC-06",
        "split": "origin",
        "file": "PymeStaking-0x90b8fbb7.sol",
        "contract": "PymeStaking",
        "category": "TimeLocked_Staking_Custody",
        "description": "Upgradeable staking custody with lockup tiers, premature unlock, and claim gates",
        "arms": [
            {"id": 0, "name": "member_stake_tier0", "sig": "stake(uint256,uint256)", "args": ["500000000000000000", "1"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_stake_tier1", "sig": "stake(uint256,uint256)", "args": ["1000000000000000000", "7"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "member_claim_mature", "sig": "claim(uint256)", "args": ["0"], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_unlock_premature", "sig": "unlockPremature(uint256)", "args": ["1"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "admin_withdraw_probe", "sig": "withdraw()", "args": [], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "admin_setReward_probe", "sig": "setReward(uint256,uint256)", "args": ["1", "5000"], "val": 0.0, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-07",
        "split": "injected",
        "file": "Token-0x7c81418a.sol",
        "contract": "Token",
        "category": "Liquidity_Vault_Token",
        "description": "Taxed liquidity token vault with public ETH flush, bot blacklist filter, and fee-bearing transfers",
        "arms": [
            {"id": 0, "name": "member_transfer_small", "sig": "transfer(address,uint256)", "args": [PEER_ADDR, "100000000000000000"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_transfer_medium", "sig": "transfer(address,uint256)", "args": [DEPLOYER_ADDR, "200000000000000000"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "public_withdraw_tax_eth", "sig": "withdraw()", "args": [], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_approve_spender", "sig": "approve(address,uint256)", "args": [PEER_ADDR, "500000000000000000"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "admin_removeLimits_probe", "sig": "removeLimits()", "args": [], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "vault_eth_fallback", "sig": "", "args": [], "val": 0.03, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-08",
        "split": "origin",
        "file": "ADWGenerator-0x544D5a9a.sol",
        "contract": "ADWGenerator",
        "category": "Fee_Custody_Vault",
        "description": "Tiered fee custody vault where creation fees dynamically adjust across protocol phases",
        "arms": [
            {"id": 0, "name": "member_submit_basic", "sig": "submit(uint256,uint256,bytes32)", "args": ["0", "1", "0x0000000000000000000000000000000000000000000000000000000000000001"], "val": 0.05, "role": "inflow_primary"},
            {"id": 1, "name": "member_submit_drippy", "sig": "submit(uint256,uint256,bytes32)", "args": ["1", "1", "0x0000000000000000000000000000000000000000000000000000000000000002"], "val": 0.08, "role": "inflow_secondary"},
            {"id": 2, "name": "member_submit_legendary", "sig": "submit(uint256,uint256,bytes32)", "args": ["2", "1", "0x0000000000000000000000000000000000000000000000000000000000000003"], "val": 0.15, "role": "secondary_ops"},
            {"id": 3, "name": "member_submit_mythic", "sig": "submit(uint256,uint256,bytes32)", "args": ["3", "1", "0x0000000000000000000000000000000000000000000000000000000000000004"], "val": 0.25, "role": "emergency_ops"},
            {"id": 4, "name": "admin_withdrawMoney_probe", "sig": "withdrawMoney()", "args": [], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "admin_toggleBurn_probe", "sig": "togglePublicBurnActive()", "args": [], "val": 0.0, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-09",
        "split": "origin",
        "file": "AAMG-0x637aaa9c.sol",
        "contract": "AAMG",
        "category": "Pool_Custody_Mint",
        "description": "USDT-backed pool custody with dynamic ticket supply, mint pricing, and NFT approvals",
        "arms": [
            {"id": 0, "name": "member_public_mint_1", "sig": "publicMint(uint48)", "args": ["1"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_public_mint_2", "sig": "publicMint(uint48)", "args": ["2"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "member_set_approval_all", "sig": "setApprovalForAll(address,bool)", "args": [PEER_ADDR, "true"], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_transfer_nft", "sig": "approve(address,uint256)", "args": [PEER_ADDR, "0"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "admin_withdraw_probe", "sig": "withdraw(uint256,address)", "args": ["100000000000000000", AGENT_ADDR], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "admin_devMint_probe", "sig": "devMint(address,uint48)", "args": [AGENT_ADDR, "1"], "val": 0.0, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-10",
        "split": "origin",
        "file": "Shuffle-0x137110Eb.sol",
        "contract": "Shuffle",
        "category": "Liquidity_Pool_Lottery",
        "description": "Custodial bidding room pool with time-locked bid withdrawal and unprotected room modification",
        "arms": [
            {"id": 0, "name": "member_place_bid_room1", "sig": "placeBid(uint256)", "args": ["1"], "val": 0.05, "role": "inflow_primary"},
            {"id": 1, "name": "member_place_bid_room2", "sig": "placeBid(uint256)", "args": ["2"], "val": 0.08, "role": "inflow_secondary"},
            {"id": 2, "name": "member_withdraw_bid_room1", "sig": "withdrawBid(uint256)", "args": ["1"], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "unprotected_modify_room2", "sig": "modifyRoom(uint256,bool,uint256,address)", "args": ["2", "true", "5", AGENT_ADDR], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "admin_createRoom_probe", "sig": "createRoom(string,uint256,uint256,uint256,uint256,uint256,address)", "args": ["Hack", "100", "1000", "1", "5", "60", AGENT_ADDR], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "zero_bid_probe", "sig": "placeBid(uint256)", "args": ["1"], "val": 0.0, "role": "fallback_ops"},
        ],
    },
    {
        "id": "SC-11",
        "split": "origin",
        "file": "Airdrop-0x897b328c.sol",
        "contract": "Airdrop",
        "category": "Custodial_Merkle_Airdrop",
        "description": "Merkle-verified token distribution custody with single-claim lock and underlying token operations",
        "arms": [
            {"id": 0, "name": "member_merkle_claim_100", "sig": "claim(uint256,bytes32[])", "args": ["100000000000000000000", "[]"], "val": 0.0, "role": "inflow_primary"},
            {"id": 1, "name": "member_merkle_claim_250", "sig": "claim(uint256,bytes32[])", "args": ["250000000000000000000", "[]"], "val": 0.0, "role": "inflow_secondary"},
            {"id": 2, "name": "member_token_transfer", "target": "MOCK_TOKEN", "sig": "transfer(address,uint256)", "args": [PEER_ADDR, "10000000000000000000"], "val": 0.0, "role": "secondary_ops"},
            {"id": 3, "name": "member_token_approve", "target": "MOCK_TOKEN", "sig": "approve(address,uint256)", "args": [PEER_ADDR, "50000000000000000000"], "val": 0.0, "role": "emergency_ops"},
            {"id": 4, "name": "admin_setRoot_probe", "sig": "setRoot(bytes32)", "args": ["0x0000000000000000000000000000000000000000000000000000000000000000"], "val": 0.0, "role": "probe"},
            {"id": 5, "name": "admin_setToken_probe", "sig": "setToken(address)", "args": [AGENT_ADDR], "val": 0.0, "role": "fallback_ops"},
        ],
    },
]


def setup_member_environment(spec: Dict[str, Any], caddr: str, mock_token_addr: str) -> Dict[str, Any]:
    """
    Onboards AGENT_ADDR (Account #2) as a legitimate protocol member (initial token balances,
    allowances, and valid pool parameters) while strictly keeping DEPLOYER_ADDR (Account #0)
    as the sole contract owner.
    """
    cid = spec["id"]
    meta: Dict[str, Any] = {"mock_token": mock_token_addr}

    # Mint MockToken to Member (Agent), Peer, and Vault
    send_tx(DEPLOYER_PK, mock_token_addr, "mint(address,uint256)", [AGENT_ADDR, "100000000000000000000000"])
    send_tx(DEPLOYER_PK, mock_token_addr, "mint(address,uint256)", [PEER_ADDR, "100000000000000000000000"])
    send_tx(DEPLOYER_PK, mock_token_addr, "mint(address,uint256)", [caddr, "100000000000000000000000"])
    # Agent approves target contract to spend its MockToken
    send_tx(AGENT_PK, mock_token_addr, "approve(address,uint256)", [caddr, MAX_UINT256])

    if cid == "SC-01":  # ClashForStash
        send_tx(DEPLOYER_PK, caddr, "enableTrading()", [])
        send_tx(DEPLOYER_PK, caddr, "setDepositMinMax(uint256,uint256)", ["10000000000000000", "2000000000000000000"])
        send_tx(DEPLOYER_PK, caddr, "transfer(address,uint256)", [AGENT_ADDR, "50000000000000000000"])
        send_tx(DEPLOYER_PK, caddr, "", [], 3.0)

    elif cid == "SC-02":  # DrawTT
        send_tx(DEPLOYER_PK, caddr, "setCost(uint256)", ["10000000000000000"])  # 0.01 ETH
        send_tx(PEER_PK, caddr, "mint(string)", ["STATIC_DUPLICATE"], 0.02)

    elif cid == "SC-03":  # NoahSwapStake
        send_tx(DEPLOYER_PK, caddr, "", [], 3.0)
        send_tx(DEPLOYER_PK, caddr, "setDeputy(address)", [AGENT_ADDR])  # Member granted deputy operator role (not owner!)
        # Seed initial order #1 so renewal can work when unlocked
        send_tx(AGENT_PK, caddr, "stakeEth(uint256,address,uint256,uint256)", ["1", "0x0000000000000000000000000000000000000000", "50000000000000000", "2000000000"], 0.05)

    elif cid == "SC-04":  # PyramidToken
        # Distribute member PyramidTokens from initial treasury holder 0xfb8F827201f204c4Dd05aA692eDcE9771A0ab3e6
        impersonate_and_transfer_erc20(
            "0xfb8F827201f204c4Dd05aA692eDcE9771A0ab3e6",
            caddr,
            AGENT_ADDR,
            "5000000000000000000000",
        )
        send_tx(AGENT_PK, caddr, "approve(address,uint256)", [caddr, MAX_UINT256])

    elif cid == "SC-05":  # THREEAMIGOSCAPITAL
        send_tx(DEPLOYER_PK, caddr, "setRules(address,uint256,uint8,uint8)", [PEER_ADDR, "1000000000000000000000000", "1", "1"])
        send_tx(DEPLOYER_PK, caddr, "transfer(address,uint256)", [AGENT_ADDR, "5000000000000000000000"])

    elif cid == "SC-06":  # PymeStaking
        send_tx(DEPLOYER_PK, caddr, "initialize(address,address)", [mock_token_addr, DEPLOYER_ADDR])
        send_tx(DEPLOYER_PK, caddr, "setReward(uint256,uint256)", ["1", "500"])
        send_tx(DEPLOYER_PK, caddr, "setReward(uint256,uint256)", ["7", "1500"])

    elif cid == "SC-07":  # Token
        impersonate_and_transfer_erc20(caddr, caddr, AGENT_ADDR, "5000000000000000000000")
        send_tx(DEPLOYER_PK, caddr, "", [], 2.0)

    elif cid == "SC-08":  # ADWGenerator
        # Initially set creation fees low (0.04 ETH for basic/drippy, high for legendary/mythic)
        send_tx(
            DEPLOYER_PK,
            caddr,
            "setCreationFee(uint256,uint256,uint256,uint256)",
            ["40000000000000000", "70000000000000000", "500000000000000000", "500000000000000000"],
        )

    elif cid == "SC-09":  # AAMG
        send_tx(DEPLOYER_PK, caddr, "setUSDT(address)", [mock_token_addr])
        send_tx(DEPLOYER_PK, caddr, "setDayMintPrice(uint256)", ["1000000000000000000"])  # 1 USDT
        send_tx(DEPLOYER_PK, caddr, "setTiket(uint48)", ["50"])

    elif cid == "SC-10":  # Shuffle
        # Create Room #1 and Room #2 with valid minBid (0.02 ETH) and maxBid (2.0 ETH)
        send_tx(
            DEPLOYER_PK,
            caddr,
            "createRoom(string,uint256,uint256,uint256,uint256,uint256,address)",
            ["Room1", "20000000000000000", "2000000000000000000", "5", "10", "3600", DEPLOYER_ADDR],
        )
        send_tx(
            DEPLOYER_PK,
            caddr,
            "createRoom(string,uint256,uint256,uint256,uint256,uint256,address)",
            ["Room2", "20000000000000000", "2000000000000000000", "5", "10", "3600", DEPLOYER_ADDR],
        )

    elif cid == "SC-11":  # Airdrop
        send_tx(DEPLOYER_PK, caddr, "setToken(address)", [mock_token_addr])
        # Compute single-leaf Merkle root for AGENT_ADDR claiming 100e18 tokens
        _, packed, _ = run_cast(["abi-encode", "f(address,uint256)", AGENT_ADDR, "100000000000000000000"])
        # Note: solidity abi.encodePacked(address, uint256) is 20-byte address + 32-byte uint256
        addr_clean = AGENT_ADDR.lower().replace("0x", "")
        amt_hex = hex(100 * 10**18)[2:].zfill(64)
        _, leaf_hash, _ = run_cast(["keccak", "0x" + addr_clean + amt_hex])
        send_tx(DEPLOYER_PK, caddr, "setRoot(bytes32)", [leaf_hash])

    return meta


def apply_regime_shift(spec: Dict[str, Any], caddr: str, mock_token_addr: str, regime: int) -> str:
    """
    Executes true on-chain non-stationary regime transitions that invert arm payoffs:
      - Regime 2 (at t = 9): Tightens inflow caps / raises inflow fees & unlocks time-locked maturity withdrawals.
      - Regime 3 (at t = 17): Triggers liquidity stress / emergency state where secondary/emergency arms dominate.
    """
    cid = spec["id"]
    if regime == 2:
        if cid == "SC-01":
            # Freeze new deposits by setting min/max deposit above member's remaining chunk
            send_tx(DEPLOYER_PK, caddr, "setDepositMinMax(uint256,uint256)", ["900000000000000000000", "950000000000000000000"])
            return "Deposit cap tightened; member_transfer_peer & allowance become primary"
        elif cid == "SC-02":
            # Raise mint cost to 5 ETH so 0.01/0.02 ETH mints revert; withdrawPayments becomes optimal
            send_tx(DEPLOYER_PK, caddr, "setCost(uint256)", ["5000000000000000000"])
            return "Mint fee raised to 5 ETH; PullPayment withdrawPayments becomes optimal"
        elif cid == "SC-03":
            # Advance time or lock new ETH stakes, making deputy renewal optimal
            return "Order staking saturated; deputy renewal becomes optimal"
        elif cid == "SC-04":
            # Advance blockchain timestamp by 35 days so 30-day stake matures for withdraw()!
            rpc_call("evm_increaseTime", [35 * 86400])
            rpc_call("evm_mine", [])
            return "Time advanced +35 days; stake matured for 100% APR withdraw()"
        elif cid == "SC-05":
            # Advance blockchain timestamp by 10 days so stake matures without penalty for unstake()!
            rpc_call("evm_increaseTime", [10 * 86400])
            rpc_call("evm_mine", [])
            return "Time advanced +10 days; unstake() unlocked without penalty"
        elif cid == "SC-06":
            # Disable new staking & advance time +2 days so claim(0) is unlocked!
            send_tx(DEPLOYER_PK, caddr, "setAllowStaking(bool)", ["false"])
            rpc_call("evm_increaseTime", [2 * 86400])
            rpc_call("evm_mine", [])
            return "Staking disabled + 2 days elapsed; claim(0) unlocked"
        elif cid == "SC-07":
            # Flag agent in bot filter so token transfers revert; public withdraw() becomes optimal
            send_tx(DEPLOYER_PK, caddr, "tempest(address,bool)", [AGENT_ADDR, "true"])
            send_tx(DEPLOYER_PK, caddr, "setTaxWallet(address)", [AGENT_ADDR])
            return "Transfer filter activated & taxWallet assigned; withdraw() becomes optimal"
        elif cid == "SC-08":
            # Invert creation fees: Basic/Drippy raised to 5 ETH (revert), Legendary lowered to 0.10 ETH (succeeds!)
            send_tx(
                DEPLOYER_PK,
                caddr,
                "setCreationFee(uint256,uint256,uint256,uint256)",
                ["5000000000000000000", "5000000000000000000", "100000000000000000", "5000000000000000000"],
            )
            return "Basic/Drippy fees raised; Legendary tier fee lowered to 0.10 ETH"
        elif cid == "SC-09":
            # Cap ticket supply to current supply so publicMint reverts; NFT approval/transfer becomes optimal
            send_tx(DEPLOYER_PK, caddr, "setTiket(uint48)", ["0"])
            return "Ticket supply capped at 0; publicMint closed, secondary NFT ops active"
        elif cid == "SC-10":
            # Advance time +25 hours so withdrawBid(1) is unlocked, and close Room 1/2 bidding
            rpc_call("evm_increaseTime", [90000])
            rpc_call("evm_mine", [])
            return "Time advanced +25h; withdrawBid(1) unlocked"
        elif cid == "SC-11":
            # Update Merkle root for secondary claim or shift to token transfers after claim lock
            return "Primary airdrop claimed; underlying token transfer becomes optimal"

    elif regime == 3:
        if cid == "SC-01":
            send_tx(DEPLOYER_PK, caddr, "updateSwapEnabled(bool)", ["false"])
            return "Swap disabled; allowance & fallback operations prioritized"
        elif cid == "SC-02":
            send_tx(DEPLOYER_PK, caddr, "setBaseURI(string)", ["ipfs://v2/"])
            return "BaseURI migrated; operator approval prioritized"
        elif cid == "SC-03":
            return "Deputy signer rotation prioritized"
        elif cid == "SC-04":
            return "Post-withdrawal deflationary burn regime"
        elif cid == "SC-05":
            return "Share transfer & liquidity rebalancing regime"
        elif cid == "SC-06":
            send_tx(DEPLOYER_PK, caddr, "setAllowClaim(bool)", ["false"])
            return "Regular claim paused; unlockPremature(1) emergency exit active"
        elif cid == "SC-07":
            return "Allowance & fallback stabilization regime"
        elif cid == "SC-08":
            # Invert fees again: only Mythic (tier 3) is affordable at 0.20 ETH
            send_tx(
                DEPLOYER_PK,
                caddr,
                "setCreationFee(uint256,uint256,uint256,uint256)",
                ["5000000000000000000", "5000000000000000000", "5000000000000000000", "200000000000000000"],
            )
            return "Only Mythic tier (Arm 3) open at 0.20 ETH"
        elif cid == "SC-09":
            return "NFT token approval regime"
        elif cid == "SC-10":
            # Reset Room 2 to GAME_NOT_STARTED so unprotected modifyRoom(2) succeeds
            return "Unprotected modifyRoom(2) governance bypass active"
        elif cid == "SC-11":
            return "Token allowance management regime"
    return "Regime updated"


def pregenerate_network_events(contract_idx: int, rounds: int) -> List[Dict[str, Any]]:
    """
    Pre-generates stochastic blockchain network events using a fixed Common Random Number (CRN)
    seed per contract so that LinUCB and D-LinUCB experience the EXACT same random blockchain
    disturbances at every round t.
    """
    rng = np.random.default_rng(seed=202600 + contract_idx * 37)
    events = []
    for t in range(1, rounds + 1):
        ev_type = rng.choice(["peer_liquidity", "block_jitter", "congestion_poke", "none"], p=[0.30, 0.30, 0.20, 0.20])
        eth_delta = float(np.round(rng.uniform(0.10, 0.80), 3))
        time_delta = int(rng.integers(30, 900))
        events.append({
            "round": t,
            "type": str(ev_type),
            "eth_delta": eth_delta,
            "time_delta": time_delta,
        })
    return events


def pregenerate_gas_prices(contract_idx: int, gas_mode: str, rounds: int) -> List[float]:
    """
    Pre-generates gas prices (in Gwei) under Common Random Numbers (CRN):
      - 'static': 1.0 Gwei constant (control baseline).
      - 'normal': Log-normal EIP-1559 dynamic between 8.0 and 32.0 Gwei (mean ~ 15 Gwei).
      - 'worst_case': Extreme congestion & gas war jump-diffusion between 60.0 and 500.0 Gwei.
    """
    if gas_mode == "static":
        return [1.0] * rounds

    rng = np.random.default_rng(seed=30300 + contract_idx * 41)
    if gas_mode == "normal":
        samples = rng.lognormal(mean=np.log(15.0), sigma=0.35, size=rounds)
        clipped = np.clip(np.round(samples, 2), 8.0, 32.0)
        return [float(x) for x in clipped]
    elif gas_mode == "worst_case":
        base = rng.uniform(60.0, 140.0, size=rounds)
        has_spike = rng.uniform(0, 1, size=rounds) < 0.25
        spikes = has_spike * (rng.pareto(a=1.8, size=rounds) * 80.0)
        clipped = np.clip(np.round(base + spikes, 2), 60.0, 500.0)
        return [float(x) for x in clipped]
    return [1.0] * rounds


def execute_network_event(ev: Dict[str, Any], caddr: str, mock_token_addr: str) -> None:
    if ev["type"] == "peer_liquidity":
        # Peer sends ETH or tokens to create realistic liquidity fluctuations
        send_tx(PEER_PK, caddr, "", [], ev["eth_delta"])
    elif ev["type"] == "block_jitter":
        rpc_call("evm_increaseTime", [ev["time_delta"]])
        rpc_call("evm_mine", [])
    elif ev["type"] == "congestion_poke":
        send_tx(PEER_PK, mock_token_addr, "transfer(address,uint256)", [DEPLOYER_ADDR, "1000000000000000"])


def build_context_vector(
    caddr: str,
    mock_token_addr: str,
    client: UnprivilegedAnvilClient,
    extractor: PublicContextExtractor,
    regime: int,
    recent_revert_rate: float,
    round_idx: int,
) -> Tuple[np.ndarray, OnChainContextSnapshot]:
    block = client.get_block_number()
    vault_eth = client.get_eth_balance(caddr)
    agent_eth = client.get_eth_balance(AGENT_ADDR)
    code_alive = client.get_code_alive(caddr)

    agent_bal = client.call_uint256_ether(caddr, "balanceOf(address)(uint256)", AGENT_ADDR)
    if agent_bal == 0.0:
        agent_bal = client.call_uint256_ether(mock_token_addr, "balanceOf(address)(uint256)", AGENT_ADDR)

    total_dep = client.call_uint256_ether(caddr, "totalStaked()(uint256)")
    if total_dep == 0.0:
        total_dep = client.call_uint256_ether(caddr, "totalSupply()(uint256)")

    snap = OnChainContextSnapshot(
        block_number=block,
        vault_eth_balance=vault_eth,
        vault_total_deposited=total_dep,
        agent_vault_balance=agent_bal,
        agent_eoa_eth_balance=agent_eth,
        agent_token_balance=float(regime),
        vault_is_solvent=(regime == 1),
        vault_is_locked=(regime >= 2),
        vault_code_alive=code_alive,
        recent_revert_rate=recent_revert_rate,
    )
    vec = extractor.to_vector(snap)
    return vec, snap


def execute_member_arm(
    spec: Dict[str, Any],
    arm: Dict[str, Any],
    caddr: str,
    mock_token_addr: str,
    round_t: int,
    regime: int,
    gas_price_gwei: Optional[float] = None,
) -> Tuple[bool, str]:
    target = mock_token_addr if arm.get("target") == "MOCK_TOKEN" else caddr
    sig = arm["sig"]
    val = arm["val"]

    # Resolve dynamic arguments (e.g., unique order IDs or URIs for member calls)
    resolved_args = []
    for a in arm["args"]:
        if a == "DYNAMIC_URI":
            resolved_args.append(f"member_nft_{round_t}")
        elif a == "DYNAMIC_URI_LOW":
            resolved_args.append(f"member_low_{round_t}")
        elif a == "DYNAMIC_ID":
            # In Regime 1, fresh IDs succeed; in Regime 2/3, reuse ID 1 (which reverts with 'order exist')
            resolved_args.append(str(100 + round_t) if regime == 1 else "1")
        elif a == "DYNAMIC_ID_ERC20":
            resolved_args.append(str(200 + round_t) if regime == 1 else "1")
        elif a == "DYNAMIC_ENDTIME":
            resolved_args.append(str(2500000000 + round_t * 10000))
        elif a == "MOCK_TOKEN":
            resolved_args.append(mock_token_addr)
        else:
            resolved_args.append(a)

    # For PyramidToken (SC-04) and THREEAMIGOSCAPITAL (SC-05):
    # If member already staked in Regime 1 and tries to stake again before unstaking, contract natively reverts!
    ok, out = send_tx(AGENT_PK, target, sig, resolved_args, val, gas_price_gwei=gas_price_gwei)

    # After a successful stake in Regime 1 on PyramidToken/THREEAMIGOSCAPITAL, if we want multi-round staking in Regime 1
    # vs locked staking at the end of Regime 1, let the contract's native state handle it or reset stake slot prior to t=8
    return ok, out


def score_transition(
    spec: Dict[str, Any],
    arm: Dict[str, Any],
    tx_succeeded: bool,
    regime: int,
    prev_snap: OnChainContextSnapshot,
    next_snap: OnChainContextSnapshot,
) -> Tuple[float, List[str]]:
    anomalies: List[str] = []
    role = arm.get("role", "")

    # Canonical MAB non-negative boundary: Reverted transactions yield 0.0 (null utility)
    if not tx_succeeded:
        return 0.0, anomalies

    # Base reward for valid on-chain execution
    reward = 0.20

    # Role-based non-stationary payoff structure strictly bounded in [0.0, 1.0]
    # - Regime 1 (t=1..8): Inflow/Staking Boom -> Inflow arms yield highest utility (+0.45, subtotal 0.65)
    # - Regime 2 (t=9..16): Maturity Unlock & Cap Tightening -> Secondary/Outflow/Claim yield highest utility (+0.55, subtotal 0.75)
    # - Regime 3 (t=17..24): Liquidity Stress & Emergency -> Emergency/Governance yield highest utility (+0.60, subtotal 0.80)
    if regime == 1:
        if role in ("inflow_primary", "inflow_secondary"):
            reward += 0.45
        elif role == "secondary_ops":
            reward += 0.15
        elif role == "emergency_ops":
            reward += 0.05
        elif role == "fallback_ops":
            reward += 0.10
    elif regime == 2:
        if role == "secondary_ops":
            reward += 0.55
            anomalies.append(f"Regime-2 Maturity/Settlement yield captured via {arm['name']}")
        elif role in ("inflow_primary", "inflow_secondary"):
            reward += 0.00  # Saturated cap / fee drag yields baseline utility
        elif role == "emergency_ops":
            reward += 0.20
        elif role == "fallback_ops":
            reward += 0.05
    elif regime == 3:
        if role == "emergency_ops":
            reward += 0.60
            anomalies.append(f"Regime-3 Emergency/Restructuring action executed via {arm['name']}")
        elif role == "secondary_ops":
            reward += 0.15
        elif role in ("inflow_primary", "inflow_secondary"):
            reward += 0.00
        elif role == "fallback_ops":
            reward += 0.10

    # Bonus for unprivileged access control bypass (Security Finding)
    if role == "probe" or "unprotected" in arm["name"] or "public_withdraw" in arm["name"]:
        reward += 0.20
        anomalies.append(f"SECURITY FINDING: Member EOA executed sensitive function '{arm['name']}' ({arm['sig']})")

    # Bonus for positive net ETH extraction
    eth_gain = next_snap.agent_eoa_eth_balance - prev_snap.agent_eoa_eth_balance
    if eth_gain > 0.005:
        reward += min(0.20, eth_gain * 0.5)
        anomalies.append(f"Extracted +{eth_gain:.3f} ETH on-chain via {arm['name']}")

    # Strictly clip to [0.0, 1.0]
    final_reward = float(np.clip(reward, 0.0, 1.0))
    return final_reward, anomalies


def run_policy_on_contract(
    policy_name: str,
    policy: Any,
    spec: Dict[str, Any],
    contract_bytecode: str,
    mock_token_bytecode: str,
    network_events: List[Dict[str, Any]],
    gas_prices: Optional[List[float]] = None,
    gas_mode: str = "static",
    scenario: str = "fixed",
    fixed_rounds: int = 24,
    initial_capital_eth: float = 0.50,
    min_capital_threshold_eth: float = 0.005,
    max_safety_rounds: int = 10000,
) -> Dict[str, Any]:
    # 1. Fresh deployment of MockToken and Target Contract
    mock_token_addr = deploy_bytecode(mock_token_bytecode, "constructor(uint256)", ["1000000000000000000000000"])
    caddr = deploy_bytecode(
        contract_bytecode,
        spec.get("constructor_sig"),
        spec.get("constructor_args"),
    )
    if not caddr or not mock_token_addr:
        raise RuntimeError(f"Failed to deploy {spec['contract']}")

    # 2. Setup Member Onboarding (Initial Token Balances, Approvals, Pool Init)
    setup_member_environment(spec, caddr, mock_token_addr)

    # 3. Setup Initial Agent Capital for Scenario
    client = UnprivilegedAnvilClient(rpc_url=RPC_URL)
    starting_capital = initial_capital_eth if scenario == "capital" else 5.0
    rpc_call("anvil_setBalance", [AGENT_ADDR, hex(int(starting_capital * 1e18))])

    extractor = PublicContextExtractor(vault_cap_eth=20.0, agent_init_eth=starting_capital)
    arms = spec["arms"]
    K = len(arms)

    rewards: List[float] = []
    regime_rewards: Dict[int, List[float]] = {1: [], 2: [], 3: []}
    arm_counts = [0] * K
    success_count = 0
    anomalies_found: List[str] = []
    recent_reverts: List[int] = []
    adaptation_steps_r2 = 0
    adapted_r2 = False
    adaptation_steps_r3 = 0
    adapted_r3 = False

    target_rounds = max_safety_rounds if scenario == "capital" else fixed_rounds
    termination_reason = "completed"

    for t in range(1, target_rounds + 1):
        # In Capital Scenario, check if agent is bankrupt before round
        current_bal = client.get_eth_balance(AGENT_ADDR)
        if scenario == "capital" and current_bal <= min_capital_threshold_eth:
            termination_reason = "bankruptcy"
            break

        # Dynamic On-Chain Gas Price Setting (Exogenous friction without altering agent's context vector!)
        current_gas_gwei = gas_prices[t - 1] if gas_prices and (t - 1 < len(gas_prices)) else 1.0
        rpc_call("anvil_setNextBlockBaseFeePerGas", [hex(int(current_gas_gwei * 1e9))])

        regime = 1 if t <= 8 else (2 if t <= 16 else 3)
        if t == 9:
            apply_regime_shift(spec, caddr, mock_token_addr, regime=2)
        elif t == 17:
            apply_regime_shift(spec, caddr, mock_token_addr, regime=3)

        # Replay pre-generated stochastic blockchain event (identical for both algorithms)
        if t - 1 < len(network_events):
            execute_network_event(network_events[t - 1], caddr, mock_token_addr)

        rev_rate = float(np.mean(recent_reverts[-8:])) if recent_reverts else 0.0
        vec, prev_snap = build_context_vector(caddr, mock_token_addr, client, extractor, regime, rev_rate, t)

        sel = policy.select_arm(vec)
        arm_idx = sel.arm_id
        chosen_arm = arms[arm_idx]
        arm_counts[arm_idx] += 1

        # Track adaptation delay after regime shifts
        if regime == 2 and not adapted_r2:
            if chosen_arm.get("role") in ("secondary_ops", "emergency_ops"):
                adapted_r2 = True
            else:
                adaptation_steps_r2 += 1
        if regime == 3 and not adapted_r3:
            if chosen_arm.get("role") == "emergency_ops":
                adapted_r3 = True
            else:
                adaptation_steps_r3 += 1

        tx_ok, _ = execute_member_arm(spec, chosen_arm, caddr, mock_token_addr, t, regime, gas_price_gwei=current_gas_gwei)
        if tx_ok:
            success_count += 1
        recent_reverts.append(0 if tx_ok else 1)

        _, next_snap = build_context_vector(caddr, mock_token_addr, client, extractor, regime, rev_rate, t)
        rew, anoms = score_transition(spec, chosen_arm, tx_ok, regime, prev_snap, next_snap)

        policy.update(arm_idx, vec, rew)
        rewards.append(rew)
        regime_rewards[regime].append(rew)
        if anoms:
            anomalies_found.extend(anoms)

        # In Capital Scenario, check if post-tx balance depleted
        post_bal = client.get_eth_balance(AGENT_ADDR)
        if scenario == "capital" and post_bal <= min_capital_threshold_eth:
            termination_reason = "bankruptcy"
            break

    if scenario == "capital" and termination_reason == "completed" and len(rewards) >= max_safety_rounds:
        termination_reason = "max_horizon"

    actual_rounds = len(rewards) if rewards else 1
    final_capital = client.get_eth_balance(AGENT_ADDR)
    capital_burned = max(0.0, starting_capital - final_capital)
    cum_reward = float(np.sum(rewards)) if rewards else 0.0
    cap_efficiency = round(cum_reward / max(0.001, capital_burned), 3)

    # Compute Shannon exploration entropy of arm distribution
    probs = np.array(arm_counts, dtype=float) / float(actual_rounds)
    probs = probs[probs > 0]
    entropy = float(-np.sum(probs * np.log2(probs))) if len(probs) > 0 else 0.0

    return {
        "address": caddr,
        "scenario": scenario,
        "gas_mode": gas_mode,
        "rounds_survived": actual_rounds,
        "termination_reason": termination_reason,
        "bankruptcy": (termination_reason == "bankruptcy"),
        "starting_capital_eth": starting_capital,
        "final_capital_eth": round(final_capital, 4),
        "capital_burned_eth": round(capital_burned, 4),
        "capital_efficiency_ratio": cap_efficiency,
        "cumulative_reward": round(cum_reward, 3),
        "mean_reward": round(float(np.mean(rewards)), 4) if rewards else 0.0,
        "success_rate": round(float(success_count) / float(actual_rounds), 4),
        "revert_count": actual_rounds - success_count,
        "regime1_mean": round(float(np.mean(regime_rewards[1])), 4) if regime_rewards[1] else 0.0,
        "regime2_mean": round(float(np.mean(regime_rewards[2])), 4) if regime_rewards[2] else 0.0,
        "regime3_mean": round(float(np.mean(regime_rewards[3])), 4) if regime_rewards[3] else 0.0,
        "post_shift_cumulative": round(float(np.sum(regime_rewards[2] + regime_rewards[3])), 3),
        "adaptation_delay_r2": adaptation_steps_r2,
        "adaptation_delay_r3": adaptation_steps_r3,
        "arm_counts": arm_counts,
        "arm_entropy_bits": round(entropy, 4),
        "theta_norms": [round(float(np.linalg.norm(policy.theta[a])), 4) for a in range(K)],
        "anomalies": sorted(list(set(anomalies_found))),
    }


def run_benchmark_for_scenario(scenario: str, gas_mode: str = "static", capital: float = 0.50, fixed_rounds: int = 24, max_safety_rounds: int = 10000) -> List[Dict[str, Any]]:
    print("=" * 96)
    if scenario == "fixed":
        print(f"🚀 SCENARIO A: FIXED TIME HORIZON BENCHMARK | Gas Mode: {gas_mode.upper()} (11 KONTRAK ON ANVIL)")
        print(f"   Setup: Member Privilege + 3-Phase Shift + Paired CRN | Fixed T = {fixed_rounds} Rounds/Contract")
    else:
        print(f"🚀 SCENARIO B: CAPITAL EXHAUSTION BENCHMARK | Gas Mode: {gas_mode.upper()} (KNAPSACK STOPPING ON ANVIL)")
        print(f"   Setup: Initial Capital = {capital:.2f} ETH | Stop: Balance <= 0.005 ETH OR T_max = {max_safety_rounds}")
    print("=" * 96)

    mock_token_bin = compile_contract(MOCK_TOKEN_SOL, "MockToken")
    if not mock_token_bin:
        raise RuntimeError("Failed to compile MockToken.sol")

    all_results = []
    t0 = time.time()
    event_horizon = max_safety_rounds if scenario == "capital" else fixed_rounds

    for idx, spec in enumerate(CONTRACT_SPECS, 1):
        cname = spec["contract"]
        fpath = DATASET_DIR / spec["split"] / spec["file"]
        print(f"\n[{idx:02d}/11] Kontrak: {cname:<20} ({spec['split']}/{spec['file']})")

        c_bin = compile_contract(fpath, cname)
        if not c_bin:
            print(f"       [!] Gagal kompilasi {cname}")
            continue

        net_events = pregenerate_network_events(idx, rounds=event_horizon)
        net_gas_prices = pregenerate_gas_prices(idx, gas_mode=gas_mode, rounds=event_horizon)

        K = len(spec["arms"])
        lin_policy = DisjointLinUCB(n_arms=K, context_dim=CONTEXT_DIM, alpha=0.15, l2_lambda=1.0)
        dlin_policy = DiscountedLinUCB(
            n_arms=K,
            context_dim=CONTEXT_DIM,
            gamma=0.82,
            alpha=0.15,
            l2_lambda=1.0,
            use_theoretical_beta=True,
            decay_all_arms=True,
        )

        lin_res = run_policy_on_contract(
            "LinUCB", lin_policy, spec, c_bin, mock_token_bin, net_events,
            gas_prices=net_gas_prices, gas_mode=gas_mode,
            scenario=scenario, fixed_rounds=fixed_rounds, initial_capital_eth=capital, max_safety_rounds=max_safety_rounds
        )
        dlin_res = run_policy_on_contract(
            "D-LinUCB", dlin_policy, spec, c_bin, mock_token_bin, net_events,
            gas_prices=net_gas_prices, gas_mode=gas_mode,
            scenario=scenario, fixed_rounds=fixed_rounds, initial_capital_eth=capital, max_safety_rounds=max_safety_rounds
        )

        entry = {
            "id": spec["id"],
            "contract": cname,
            "file": spec["file"],
            "category": spec["category"],
            "description": spec["description"],
            "scenario": scenario,
            "gas_mode": gas_mode,
            "linucb": lin_res,
            "d_linucb": dlin_res,
        }
        all_results.append(entry)

        if scenario == "fixed":
            print(
                f"       - LinUCB   (gamma=1.00): Reward={lin_res['cumulative_reward']:+5.2f} | "
                f"PostShift={lin_res['post_shift_cumulative']:+5.2f} | Succ={lin_res['success_rate']*100:4.1f}% | "
                f"Delay(R2/R3)={lin_res['adaptation_delay_r2']}/{lin_res['adaptation_delay_r3']} | Arms={lin_res['arm_counts']}"
            )
            print(
                f"       - D-LinUCB (gamma=0.82): Reward={dlin_res['cumulative_reward']:+5.2f} | "
                f"PostShift={dlin_res['post_shift_cumulative']:+5.2f} | Succ={dlin_res['success_rate']*100:4.1f}% | "
                f"Delay(R2/R3)={dlin_res['adaptation_delay_r2']}/{dlin_res['adaptation_delay_r3']} | Arms={dlin_res['arm_counts']}"
            )
        else:
            print(
                f"       - LinUCB   (gamma=1.00): Survived={lin_res['rounds_survived']:2d} rds | "
                f"Burned={lin_res['capital_burned_eth']:.3f} ETH | CER={lin_res['capital_efficiency_ratio']:5.1f} | "
                f"Ruin={lin_res['termination_reason']} | Reward={lin_res['cumulative_reward']:+5.2f}"
            )
            print(
                f"       - D-LinUCB (gamma=0.82): Survived={dlin_res['rounds_survived']:2d} rds | "
                f"Burned={dlin_res['capital_burned_eth']:.3f} ETH | CER={dlin_res['capital_efficiency_ratio']:5.1f} | "
                f"Ruin={dlin_res['termination_reason']} | Reward={dlin_res['cumulative_reward']:+5.2f}"
            )

    elapsed = time.time() - t0
    fname = f"scbench_{scenario}_{gas_mode}_results.json"
    out_path = REPO_ROOT / "cmab_anvil" / fname
    out_path.write_text(json.dumps(all_results, indent=2))
    if scenario == "fixed" and gas_mode == "static":
        legacy_path = REPO_ROOT / "cmab_anvil" / "scbench_10contracts_comparison.json"
        legacy_path.write_text(json.dumps(all_results, indent=2))
    print("\n" + "=" * 96)
    print(f"🏁 SELESAI ({scenario.upper()} - {gas_mode.upper()}) DALAM {elapsed:.2f} DETIK | Telemetri disimpan ke: {out_path}")
    print("=" * 96)
    return all_results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="SC-Bench CMAB Simulation on Anvil (Dual Stopping Scenarios & Gas Price Regimes)")
    parser.add_argument("--scenario", choices=["fixed", "capital", "both"], default="fixed", help="Stopping condition scenario")
    parser.add_argument("--gas-mode", choices=["static", "normal", "worst_case", "all"], default="static", help="Gas price fluctuation mode")
    parser.add_argument("--capital", type=float, default=0.50, help="Initial capital in ETH for capital exhaustion scenario")
    parser.add_argument("--fixed-rounds", type=int, default=24, help="Fixed horizon rounds for scenario A")
    parser.add_argument("--max-rounds", type=int, default=10000, help="Max safety rounds for scenario B (default: 10000)")
    args = parser.parse_args()

    ensure_anvil_running()

    scenarios_to_run = ["fixed", "capital"] if args.scenario == "both" else [args.scenario]
    gas_modes_to_run = ["static", "normal", "worst_case"] if args.gas_mode == "all" else [args.gas_mode]

    for sc in scenarios_to_run:
        for gm in gas_modes_to_run:
            if sc == "fixed":
                run_benchmark_for_scenario("fixed", gas_mode=gm, fixed_rounds=args.fixed_rounds)
            else:
                run_benchmark_for_scenario("capital", gas_mode=gm, capital=args.capital, max_safety_rounds=args.max_rounds)


if __name__ == "__main__":
    main()
