#!/usr/bin/env python3
"""
Categorize SC-Bench dataset into 5 specialized folders:
  1. Vault_and_Liquidity
  2. AMM_and_DEX_Agent
  3. Lending_and_Borrowing_Agent
  4. Governance_and_Access_Control_Agent
  5. Others_Remaining

Uses declaration-aware Solidity code analysis (after stripping comments) and
filesystem hardlinks (with copy fallback) so all categorized folders contain
directly usable .sol and .json files with near-zero additional disk overhead.
"""

import json
import os
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


SCBENCH_ROOT = Path("/home/opeteer/FuzzMaster/SC-Bench")
DATASET_ROOT = SCBENCH_ROOT / "dataset"
OUTPUT_ROOT = SCBENCH_ROOT / "categorized_dataset"

CATEGORIES = [
    "Vault_and_Liquidity",
    "AMM_and_DEX_Agent",
    "Lending_and_Borrowing_Agent",
    "Governance_and_Access_Control_Agent",
    "Others_Remaining",
]

RE_COMMENTS = re.compile(r"(//[^\n]*|/\*[\s\S]*?\*/)")

# 1. Lending & Borrowing patterns (functions, contracts, interfaces)
RE_LENDING = re.compile(
    r"\b(function\s+(?:borrow|repay|liquidate\w*|flashLoan\w*|getBorrow\w*|borrowBalance\w*|collateral\w*|accrueInterest)\b"
    r"|contract\s+\w*(?:Lending|Borrow|Loan|FlashLoan|Aave|Compound|Credit)\w*"
    r"|interface\s+\w*(?:Lending|FlashLoan|Borrower)\w*)",
    re.IGNORECASE,
)

# 2. Vault & Liquidity custody patterns (deposit, withdraw, stake, redeem, claim, rescue, sweep, lock, vault)
RE_VAULT = re.compile(
    r"\b(function\s+(?:deposit\w*|withdraw\w*|stake\w*|unstake\w*|redeem\w*|claim\w*|emergencyWithdraw\w*|rescue\w*|sweep\w*|lock\w*|unlock\w*|totalAssets|convertToShares|convertToAssets|harvest\w*)\b"
    r"|contract\s+\w*(?:Vault|Staking|Treasury|Escrow|Timelock|Custody|Pool|Farm|Locker)\w*)",
    re.IGNORECASE,
)

# 3. AMM & DEX patterns (Uniswap/Pancake/Sushi routers, pairs, swaps, liquidity provision)
RE_AMM = re.compile(
    r"\b(IUniswapV2(?:Router|Factory|Pair)\w*|ISwapRouter\w*|IPancake\w*"
    r"|function\s+(?:swapExact\w+|swapTokensFor\w+|addLiquidity\w*|removeLiquidity\w*|getAmountsOut|getReserves|createPair)\b"
    r"|contract\s+\w*(?:DEX|Swap|AMM|Router|Pair)\w*)",
    re.IGNORECASE,
)

# 4. Governance & Access Control patterns (DAO voting, proposals, RBAC roles, Ownable, Pausable, fee/limit admin controls)
RE_GOV_AC = re.compile(
    r"\b(function\s+(?:castVote\w*|propose\w*|delegate\w*|getVotes|getPastVotes|executeProposal\w*|queue\w*"
    r"|grantRole|revokeRole|hasRole|renounceRole|transferOwnership|renounceOwnership|pause|unpause"
    r"|setTax\w*|setFee\w*|excludeFromFee\w*|excludeFromMaxTransaction\w*|removeLimits|setMaxWallet\w*|setMaxTx\w*|setBots|blacklist\w*)\b"
    r"|modifier\s+(?:onlyOwner|onlyRole|onlyAdmin|onlyGovernor|whenNotPaused)\b"
    r"|contract\s+\w*(?:Governor|Governance|DAO|AccessControl|Ownable|Pausable|Authorizable|Roles)\w*)",
    re.IGNORECASE,
)


def classify_solidity_code(raw_text: str) -> Tuple[str, List[str]]:
    """
    Classify Solidity source code into one of the 5 target categories
    and return (primary_category, matched_tags).
    """
    code = RE_COMMENTS.sub("", raw_text)

    matched_tags: List[str] = []
    m_lending = RE_LENDING.findall(code)
    m_vault = RE_VAULT.findall(code)
    m_amm = RE_AMM.findall(code)
    m_gov = RE_GOV_AC.findall(code)

    if m_lending:
        matched_tags.append("Lending_and_Borrowing_Agent")
    if m_vault:
        matched_tags.append("Vault_and_Liquidity")
    if m_amm:
        matched_tags.append("AMM_and_DEX_Agent")
    if m_gov:
        matched_tags.append("Governance_and_Access_Control_Agent")

    # Priority assignment from most domain-specific to general
    if m_lending:
        primary = "Lending_and_Borrowing_Agent"
    elif m_vault:
        primary = "Vault_and_Liquidity"
    elif m_amm:
        primary = "AMM_and_DEX_Agent"
    elif m_gov:
        primary = "Governance_and_Access_Control_Agent"
    else:
        primary = "Others_Remaining"

    return primary, matched_tags


def link_or_copy(src: Path, dst: Path) -> None:
    """Create a hardlink from src to dst (or copy if across filesystems)."""
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def main() -> None:
    if OUTPUT_ROOT.exists():
        shutil.rmtree(OUTPUT_ROOT)

    for cat in CATEGORIES:
        for split in ("injected", "origin", "audited"):
            (OUTPUT_ROOT / cat / split).mkdir(parents=True, exist_ok=True)

    summary_counts: Dict[str, Counter] = {
        "injected": Counter(),
        "origin": Counter(),
        "audited": Counter(),
    }
    manifests: Dict[str, List[Dict[str, object]]] = defaultdict(list)

    # 1. Process dataset/err-inj/injected/*.sol (+ companion .json and -res.json)
    injected_dir = DATASET_ROOT / "err-inj" / "injected"
    for sol_file in sorted(injected_dir.glob("*.sol")):
        raw = sol_file.read_text(errors="ignore")
        cat, tags = classify_solidity_code(raw)
        summary_counts["injected"][cat] += 1

        target_dir = OUTPUT_ROOT / cat / "injected"
        link_or_copy(sol_file, target_dir / sol_file.name)

        stem = sol_file.stem
        json_meta = injected_dir / f"{stem}.json"
        res_meta = injected_dir / f"{stem}-res.json"
        erc_std = "unknown"
        n_bugs = 0

        if json_meta.exists():
            link_or_copy(json_meta, target_dir / json_meta.name)
            try:
                jdata = json.loads(json_meta.read_text(errors="ignore"))
                erc_std = str(jdata.get("erc", "unknown"))
                n_bugs = len(jdata.get("inj_errors", []))
            except Exception:
                pass

        if res_meta.exists():
            link_or_copy(res_meta, target_dir / res_meta.name)

        manifests[cat].append(
            {
                "contract_file": sol_file.name,
                "split": "injected",
                "erc_standard": f"ERC-{erc_std}",
                "injected_bugs_count": n_bugs,
                "matched_capabilities": tags,
            }
        )

    # 2. Process dataset/err-inj/origin/*.sol
    origin_dir = DATASET_ROOT / "err-inj" / "origin"
    for sol_file in sorted(origin_dir.glob("*.sol")):
        raw = sol_file.read_text(errors="ignore")
        cat, tags = classify_solidity_code(raw)
        summary_counts["origin"][cat] += 1

        target_dir = OUTPUT_ROOT / cat / "origin"
        link_or_copy(sol_file, target_dir / sol_file.name)

        manifests[cat].append(
            {
                "contract_file": sol_file.name,
                "split": "origin",
                "matched_capabilities": tags,
            }
        )

    # 3. Process dataset/audited/contracts/*.sol (+ companion .json)
    audited_contracts_dir = DATASET_ROOT / "audited" / "contracts"
    audited_root = DATASET_ROOT / "audited"
    for sol_file in sorted(audited_contracts_dir.glob("*.sol")):
        raw = sol_file.read_text(errors="ignore")
        cat, tags = classify_solidity_code(raw)
        summary_counts["audited"][cat] += 1

        target_dir = OUTPUT_ROOT / cat / "audited"
        link_or_copy(sol_file, target_dir / sol_file.name)

        json_meta = audited_root / f"{sol_file.stem}.json"
        if json_meta.exists():
            link_or_copy(json_meta, target_dir / json_meta.name)

        manifests[cat].append(
            {
                "contract_file": sol_file.name,
                "split": "audited",
                "matched_capabilities": tags,
            }
        )

    # Write per-category manifest.json
    for cat in CATEGORIES:
        manifest_path = OUTPUT_ROOT / cat / "manifest.json"
        manifest_data = {
            "category": cat,
            "counts": {
                "injected_contracts": summary_counts["injected"][cat],
                "origin_contracts": summary_counts["origin"][cat],
                "audited_contracts": summary_counts["audited"][cat],
                "total_contracts": (
                    summary_counts["injected"][cat]
                    + summary_counts["origin"][cat]
                    + summary_counts["audited"][cat]
                ),
            },
            "contracts": manifests[cat],
        }
        manifest_path.write_text(json.dumps(manifest_data, indent=2))

    # Write global summary_report.json
    global_summary = {
        "dataset": "SC-Bench Categorized Dataset",
        "output_root": str(OUTPUT_ROOT),
        "categories": {},
    }
    for cat in CATEGORIES:
        global_summary["categories"][cat] = {
            "folder": str(OUTPUT_ROOT / cat),
            "injected_contracts": summary_counts["injected"][cat],
            "origin_contracts": summary_counts["origin"][cat],
            "audited_contracts": summary_counts["audited"][cat],
            "total_contracts": (
                summary_counts["injected"][cat]
                + summary_counts["origin"][cat]
                + summary_counts["audited"][cat]
            ),
        }

    (OUTPUT_ROOT / "summary_report.json").write_text(
        json.dumps(global_summary, indent=2)
    )

    print("=== SC-BENCH CATEGORIZATION COMPLETE ===")
    print(f"Output directory: {OUTPUT_ROOT}\n")
    print(f"{'Category Folder':38s} | {'Injected':>8s} | {'Origin':>8s} | {'Audited':>7s} | {'Total':>8s}")
    print("-" * 80)
    for cat in CATEGORIES:
        inj = summary_counts["injected"][cat]
        ori = summary_counts["origin"][cat]
        aud = summary_counts["audited"][cat]
        tot = inj + ori + aud
        print(f"{cat:38s} | {inj:8d} | {ori:8d} | {aud:7d} | {tot:8d}")


if __name__ == "__main__":
    main()

