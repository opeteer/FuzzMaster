#!/usr/bin/env python3
"""
Universal Simulation Runner: Unprivileged Contextual Multi-Armed Bandit
(LinUCB & Discounted LinUCB) running `Agen_Vault_Custody` on Anvil.
"""

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cmab_anvil.Agen_Vault_Custody import (
    VaultCustodyEnv,
    VaultCustodyCMABAgent,
    CONTEXT_DIM,
    FEATURE_NAMES,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Unprivileged CMAB Simulation (LinUCB / Discounted LinUCB) on Anvil"
    )
    parser.add_argument(
        "--rpc-url",
        type=str,
        default="http://127.0.0.1:8545",
        help="Anvil JSON-RPC endpoint URL",
    )
    parser.add_argument(
        "--algorithm",
        type=str,
        choices=["linucb", "d-linucb"],
        default="d-linucb",
        help="CMAB algorithm strategy: 'linucb' (Disjoint LinUCB) or 'd-linucb' (Discounted LinUCB)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=10,
        help="Number of CMAB interaction rounds T",
    )
    parser.add_argument(
        "--gamma",
        type=float,
        default=0.85,
        help="Discount factor gamma in (0, 1] for Discounted LinUCB (D-LinUCB)",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.50,
        help="Exploration confidence multiplier alpha",
    )
    parser.add_argument(
        "--l2-lambda",
        type=float,
        default=1.0,
        help="Ridge regularization parameter lambda",
    )
    parser.add_argument(
        "--theoretical-beta",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use Russac et al. (2019) analytical confidence radius beta_t in D-LinUCB",
    )
    parser.add_argument(
        "--decay-all-arms",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Apply synchronous exponential decay to all arms each round in D-LinUCB",
    )
    parser.add_argument(
        "--peer-traffic",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Simulate background peer user deposits during the run",
    )
    parser.add_argument(
        "--output-log",
        type=str,
        default=str(REPO_ROOT / "cmab_anvil" / "cmab_simulation_results.json"),
        help="Path to save simulation telemetry JSON",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    algo_label = (
        "Discounted LinUCB (D-LinUCB)"
        if args.algorithm == "d-linucb"
        else "Disjoint LinUCB"
    )

    print("=" * 88)
    print(f"🧠 SIMULASI CMAB ({algo_label}) - AGEN_VAULT_CUSTODY PADA ANVIL")
    print("=" * 88)

    env = VaultCustodyEnv(rpc_url=args.rpc_url)

    # 1. Verify Strict Zero-Privilege Standing via Universal RPC Client
    standing = env.verify_unprivileged_standing()
    print("[*] Verifikasi Kedudukan Tanpa Hak Istimewa (Zero-Privilege Check):")
    print(f"    - Spesifikasi Agen   : {standing['agent_name']}")
    print(f"    - Alamat EOA Agen    : {standing['agent_address']} (Pengguna Biasa)")
    print(f"    - Owner Kontrak Vault: {standing['vault_owner']} (Bukan Agen)")
    print(f"    - Alamat Vault       : {standing['vault_address']}")
    print(f"    - Alamat MockToken   : {standing['token_address']}")
    print(f"    - Status Kedudukan   : {standing['standing']}")

    # 2. Instantiate Agen_Vault_Custody with selected algorithm
    agent = VaultCustodyCMABAgent(
        env=env,
        algorithm=args.algorithm,
        alpha=args.alpha,
        l2_lambda=args.l2_lambda,
        gamma=args.gamma,
        use_theoretical_beta=args.theoretical_beta,
        decay_all_arms=args.decay_all_arms,
        seed=42,
    )

    print(f"\n[*] Konfigurasi Model CMAB & Strategi {agent.policy.name}:")
    print(
        f"    - Dimensi Konteks (d): {CONTEXT_DIM} fitur on-chain publik "
        f"({', '.join(FEATURE_NAMES[:4])}, ...)"
    )
    print(f"    - Jumlah Lengan (K)  : {env.n_arms} strategi transaksi EOA")
    if args.algorithm == "d-linucb":
        print(
            f"    - Parameter D-LinUCB : gamma = {args.gamma}, alpha = {args.alpha}, "
            f"lambda = {args.l2_lambda}, theoretical_beta = {args.theoretical_beta}, "
            f"decay_all_arms = {args.decay_all_arms}"
        )
    else:
        print(
            f"    - Parameter LinUCB   : alpha = {args.alpha}, lambda = {args.l2_lambda}"
        )
    print("-" * 88)

    history = []

    for t in range(1, args.rounds + 1):
        # Optional peer user background deposit to create realistic context shifts
        if args.peer_traffic and t == max(1, args.rounds // 2):
            env.simulate_peer_user_deposit(eth_amount=2.0)

        selection, transition = agent.act_and_learn()
        reward = transition.reward_breakdown.total_reward
        status_tag = "SUCCESS" if transition.tx_succeeded else "REVERT "

        print(
            f"[Round {t:02d}/{args.rounds:02d}] "
            f"Arm #{selection.arm_id} ({transition.arm_spec.name:<27}) | "
            f"UCB={selection.ucb_score:+.3f} (mu={selection.expected_reward:+.3f}, "
            f"bonus={selection.uncertainty_bonus:.3f}) | "
            f"Tx={status_tag} | Reward={reward:+.2f} | "
            f"VaultETH={transition.next_snapshot.vault_eth_balance:.2f} | "
            f"AgentStake={transition.next_snapshot.agent_vault_balance:.2f}"
        )
        for anomaly in transition.reward_breakdown.detected_anomalies:
            print(f"    [!] TEMUAN ANOMALI / KERENTANAN: {anomaly}")

        history.append(
            {
                "round": t,
                "arm_id": selection.arm_id,
                "arm_name": transition.arm_spec.name,
                "ucb_score": selection.ucb_score,
                "expected_reward": selection.expected_reward,
                "uncertainty_bonus": selection.uncertainty_bonus,
                "tx_succeeded": transition.tx_succeeded,
                "reward": reward,
                "reward_breakdown": transition.reward_breakdown.to_dict(),
                "context": transition.context_vector.tolist(),
                "vault_eth_after": transition.next_snapshot.vault_eth_balance,
                "agent_eoa_eth_after": transition.next_snapshot.agent_eoa_eth_balance,
                "agent_vault_stake_after": transition.next_snapshot.agent_vault_balance,
                "vault_solvent_after": transition.next_snapshot.vault_is_solvent,
            }
        )

    diag = agent.policy.get_diagnostics()
    print("-" * 88)
    print(f"📈 RINGKASAN EVALUASI AGEN_VAULT_CUSTODY ({agent.policy.name}):")
    print(f"    - Total Putaran (T)       : {diag['total_rounds']}")
    print(f"    - Akumulasi Reward        : {diag['cumulative_reward']:+.4f}")
    print(f"    - Rata-rata Reward / Tx   : {diag['mean_reward']:+.4f}")
    print(f"    - Total Anomali Terdeteksi: {len(agent.discovered_vulnerabilities)}")
    print("    - Distribusi Pemilihan Lengan & Bobot Parameter:")
    effective_pulls = diag.get("effective_pulls")
    for arm in env.arms:
        pulls = diag["arm_counts"][arm.arm_id]
        norm_theta = diag["theta_l2_norms"][arm.arm_id]
        if effective_pulls is not None:
            ess = effective_pulls[arm.arm_id]
            print(
                f"        [{arm.arm_id}] {arm.name:<28}: {pulls:3d}x dipilih "
                f"(ESS={ess:.3f}) | ||theta_{arm.arm_id}||_2 = {norm_theta:.4f}"
            )
        else:
            print(
                f"        [{arm.arm_id}] {arm.name:<28}: {pulls:3d}x dipilih | "
                f"||theta_{arm.arm_id}||_2 = {norm_theta:.4f}"
            )
    print("=" * 88)

    out_path = Path(args.output_log)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "standing": standing,
                "diagnostics": diag,
                "discovered_vulnerabilities": agent.discovered_vulnerabilities,
                "feature_names": FEATURE_NAMES,
                "history": history,
            },
            indent=2,
        )
    )
    if hasattr(agent.policy, "save_checkpoint"):
        ckpt_name = (
            "discounted_linucb_checkpoint.json"
            if args.algorithm == "d-linucb"
            else "linucb_checkpoint.json"
        )
        agent.policy.save_checkpoint(out_path.parent / ckpt_name)


if __name__ == "__main__":
    main()
