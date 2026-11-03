"""
Reward Function Modeling (R_Vault: X_Vault x A_Vault -> [-1.0, 5.0]) for Agen_Vault_Custody.

Computes a bounded, informative bandit reward signal strictly from publicly observable
pre/post transaction state transitions and transaction receipt status.
"""

from dataclasses import dataclass, field
from typing import Dict, List
import numpy as np

from .context import OnChainContextSnapshot


@dataclass
class BanditRewardBreakdown:
    """
    Detailed decomposition of the scalar reward r_t observed after pulling arm a_t.
    """
    total_reward: float
    net_eth_gain_component: float
    state_discovery_component: float
    vulnerability_signal_component: float
    token_utility_component: float
    revert_penalty_component: float
    detected_anomalies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_reward": self.total_reward,
            "net_eth_gain": self.net_eth_gain_component,
            "state_discovery": self.state_discovery_component,
            "vulnerability_signal": self.vulnerability_signal_component,
            "token_utility": self.token_utility_component,
            "revert_penalty": self.revert_penalty_component,
            "detected_anomalies": list(self.detected_anomalies),
        }


class VaultCustodyRewardOracle:
    """
    Evaluates the scalar bandit reward r_t in [-1.0, 5.0] from public Anvil observations
    for Custody Vault & ERC-20 contracts.
    """

    def compute_reward(
        self,
        prev_snap: OnChainContextSnapshot,
        next_snap: OnChainContextSnapshot,
        tx_succeeded: bool,
        arm_id: int,
    ) -> BanditRewardBreakdown:
        if not tx_succeeded:
            return BanditRewardBreakdown(
                total_reward=-0.60,
                net_eth_gain_component=0.0,
                state_discovery_component=0.0,
                vulnerability_signal_component=0.0,
                token_utility_component=0.0,
                revert_penalty_component=-0.60,
                detected_anomalies=[],
            )

        anomalies: List[str] = []

        # 1. Agent's total ETH net worth (EOA liquid ETH + claimable Vault deposit)
        prev_net_eth = prev_snap.agent_eoa_eth_balance + prev_snap.agent_vault_balance
        next_net_eth = next_snap.agent_eoa_eth_balance + next_snap.agent_vault_balance
        delta_net_eth = next_net_eth - prev_net_eth

        net_eth_component = float(np.clip(delta_net_eth * 0.25, -0.5, 2.5))

        # 2. Meaningful state transition (storage change on Vault)
        state_discovery = 0.0
        if abs(next_snap.agent_vault_balance - prev_snap.agent_vault_balance) > 1e-6:
            if prev_snap.agent_vault_balance == 0.0 and next_snap.agent_vault_balance > 0.0:
                state_discovery = 0.65  # Unlocked withdrawal precondition (x4 > 0)
            elif next_snap.agent_vault_balance < prev_snap.agent_vault_balance:
                state_discovery = 0.75  # Completed full deposit->withdraw roundtrip
            else:
                state_discovery = 0.30

        # 3. Vulnerability / Invariant breach signal
        vuln_signal = 0.0
        if prev_snap.vault_is_solvent and not next_snap.vault_is_solvent:
            vuln_signal += 2.0
            anomalies.append("SOLVENCY_INVARIANT_BREACH (address(vault).balance < totalDeposited)")
        if prev_snap.vault_code_alive and not next_snap.vault_code_alive:
            vuln_signal += 2.0
            anomalies.append("SELFDESTRUCT_CODE_WIPED")
        if delta_net_eth > 1.0:
            vuln_signal += 1.5
            anomalies.append(f"UNAUTHORIZED_ETH_DRAIN (+{delta_net_eth:.2f} ETH extracted)")

        # 4. ERC20 Token state utility / Unprotected mint detection
        token_delta = next_snap.agent_token_balance - prev_snap.agent_token_balance
        token_component = 0.25 if abs(token_delta) > 1e-6 else 0.0
        if token_delta > 0.0 and arm_id == 6:
            anomalies.append(f"UNPROTECTED_PUBLIC_MINT (+{token_delta:.0f} MCK minted by non-owner)")

        total = float(
            np.clip(
                net_eth_component + state_discovery + vuln_signal + token_component,
                -1.0,
                5.0,
            )
        )

        return BanditRewardBreakdown(
            total_reward=total,
            net_eth_gain_component=net_eth_component,
            state_discovery_component=state_discovery,
            vulnerability_signal_component=vuln_signal,
            token_utility_component=token_component,
            revert_penalty_component=0.0,
            detected_anomalies=anomalies,
        )

