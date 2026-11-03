"""
Reward Function Modeling (R_Vault: X_Vault x A_Vault -> [0.0, 1.0]) for Agen_Vault_Custody.

Computes a bounded, normalized canonical bandit reward signal strictly from publicly observable
pre/post transaction state transitions and transaction receipt status in adherence to standard
MAB theoretical literature (e.g. Chu et al., 2011; Li et al., 2010).
"""

from dataclasses import dataclass, field
from typing import Dict, List
import numpy as np

from .context import OnChainContextSnapshot


@dataclass
class BanditRewardBreakdown:
    """
    Detailed decomposition of the normalized scalar reward r_t in [0.0, 1.0]
    observed after pulling arm a_t.
    """
    total_reward: float
    valid_execution_component: float
    net_eth_gain_component: float
    state_discovery_component: float
    vulnerability_signal_component: float
    token_utility_component: float
    revert_penalty_component: float = 0.0  # Kept for backward compatibility (0.0 in canonical MAB)
    detected_anomalies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_reward": self.total_reward,
            "valid_execution": self.valid_execution_component,
            "net_eth_gain": self.net_eth_gain_component,
            "state_discovery": self.state_discovery_component,
            "vulnerability_signal": self.vulnerability_signal_component,
            "token_utility": self.token_utility_component,
            "revert_penalty": self.revert_penalty_component,
            "detected_anomalies": list(self.detected_anomalies),
        }


class VaultCustodyRewardOracle:
    """
    Evaluates the scalar canonical bandit reward r_t in [0.0, 1.0] from public Anvil observations
    for Custody Vault & ERC-20 contracts.
    """

    def compute_reward(
        self,
        prev_snap: OnChainContextSnapshot,
        next_snap: OnChainContextSnapshot,
        tx_succeeded: bool,
        arm_id: int,
    ) -> BanditRewardBreakdown:
        # Canonical MAB boundary: Failed/reverted transactions yield 0.0 (null utility),
        # strictly avoiding negative penalties associated with RL loss formulations.
        if not tx_succeeded:
            return BanditRewardBreakdown(
                total_reward=0.0,
                valid_execution_component=0.0,
                net_eth_gain_component=0.0,
                state_discovery_component=0.0,
                vulnerability_signal_component=0.0,
                token_utility_component=0.0,
                revert_penalty_component=0.0,
                detected_anomalies=[],
            )

        anomalies: List[str] = []

        # 1. Base component for valid on-chain execution (0.20)
        valid_exec_component = 0.20

        # 2. Agent's net ETH extraction (0.00 to 0.20)
        prev_net_eth = prev_snap.agent_eoa_eth_balance + prev_snap.agent_vault_balance
        next_net_eth = next_snap.agent_eoa_eth_balance + next_snap.agent_vault_balance
        delta_net_eth = next_net_eth - prev_net_eth
        net_eth_component = float(np.clip(max(0.0, delta_net_eth) * 0.10, 0.0, 0.20))
        if delta_net_eth > 0.05:
            anomalies.append(f"POSITIVE_ETH_EXTRACTION (+{delta_net_eth:.3f} ETH)")

        # 3. Meaningful state transition (storage change on Vault: 0.00 to 0.25)
        state_discovery = 0.0
        if abs(next_snap.agent_vault_balance - prev_snap.agent_vault_balance) > 1e-6:
            if prev_snap.agent_vault_balance == 0.0 and next_snap.agent_vault_balance > 0.0:
                state_discovery = 0.20  # Unlocked withdrawal precondition (x4 > 0)
            elif next_snap.agent_vault_balance < prev_snap.agent_vault_balance:
                state_discovery = 0.25  # Completed full deposit->withdraw roundtrip
            else:
                state_discovery = 0.10

        # 4. Vulnerability / Invariant breach signal (0.00 to 0.35)
        vuln_signal = 0.0
        if prev_snap.vault_is_solvent and not next_snap.vault_is_solvent:
            vuln_signal += 0.35
            anomalies.append("SOLVENCY_INVARIANT_BREACH (address(vault).balance < totalDeposited)")
        if prev_snap.vault_code_alive and not next_snap.vault_code_alive:
            vuln_signal += 0.35
            anomalies.append("SELFDESTRUCT_CODE_WIPED")
        if delta_net_eth > 1.0:
            vuln_signal += 0.25
            anomalies.append(f"UNAUTHORIZED_ETH_DRAIN (+{delta_net_eth:.2f} ETH extracted)")

        # 5. ERC20 Token state utility / Unprotected mint detection (0.00 to 0.10)
        token_delta = next_snap.agent_token_balance - prev_snap.agent_token_balance
        token_component = 0.10 if abs(token_delta) > 1e-6 else 0.0
        if token_delta > 0.0 and arm_id == 6:
            anomalies.append(f"UNPROTECTED_PUBLIC_MINT (+{token_delta:.0f} MCK minted by non-owner)")

        # Strictly bounded to [0.0, 1.0]
        total = float(
            np.clip(
                valid_exec_component + net_eth_component + state_discovery + vuln_signal + token_component,
                0.0,
                1.0,
            )
        )

        return BanditRewardBreakdown(
            total_reward=total,
            valid_execution_component=valid_exec_component,
            net_eth_gain_component=net_eth_component,
            state_discovery_component=state_discovery,
            vulnerability_signal_component=vuln_signal,
            token_utility_component=token_component,
            revert_penalty_component=0.0,
            detected_anomalies=anomalies,
        )
