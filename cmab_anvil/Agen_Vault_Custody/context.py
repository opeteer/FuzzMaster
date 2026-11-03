"""
Context Space Modeling (X_Vault subset R^10) for Agen_Vault_Custody.

Re-models FuzzMaster's 28-dimensional internal REVM state into a 10-dimensional
publicly observable on-chain context vector x_t in R^{10} queried strictly via
read-only JSON-RPC calls (eth_getBalance, eth_call, eth_getCode, eth_blockNumber).
"""

from dataclasses import dataclass
from typing import List
import numpy as np

CONTEXT_DIM: int = 10

FEATURE_NAMES: List[str] = [
    "x0_bias",                     # Constant intercept = 1.0
    "x1_vault_eth_norm",           # Vault ETH balance normalized by 15 ETH reference cap
    "x2_vault_total_dep_norm",     # Vault recorded totalDeposited normalized by 15 ETH
    "x3_vault_drain_threshold",    # Indicator/ratio: Vault ETH >= 5 ETH (unlocks emergencyDrain condition)
    "x4_agent_vault_stake_norm",   # Agent's deposited balance inside Vault (unlocks withdrawAll)
    "x5_agent_liquid_eth_norm",    # Agent's liquid EOA ETH balance normalized by initial 5 ETH budget
    "x6_solvency_gap_ratio",       # (Vault_ETH - totalDeposited) / max(totalDeposited, 1.0)
    "x7_agent_token_share",        # Agent's MockToken balance normalized by 1,000 MCK scale
    "x8_recent_revert_rate",       # Moving average revert rate of agent's recent transactions
    "x9_vault_code_alive",         # 1.0 if VulnerableVault bytecode is intact, 0.0 if selfdestructed
]


@dataclass
class OnChainContextSnapshot:
    """
    Raw public on-chain state observed by Agen_Vault_Custody on Anvil at round t.
    """
    block_number: int
    vault_eth_balance: float
    vault_total_deposited: float
    agent_vault_balance: float
    agent_eoa_eth_balance: float
    agent_token_balance: float
    vault_is_solvent: bool
    vault_is_locked: bool
    vault_code_alive: bool
    recent_revert_rate: float


class PublicContextExtractor:
    """
    Maps a public `OnChainContextSnapshot` into a bounded context vector x_t in R^{10}.
    """

    def __init__(self, vault_cap_eth: float = 15.0, agent_init_eth: float = 5.0):
        self.vault_cap_eth = max(vault_cap_eth, 1e-6)
        self.agent_init_eth = max(agent_init_eth, 1e-6)

    def to_vector(self, snap: OnChainContextSnapshot) -> np.ndarray:
        x0_bias = 1.0
        x1_vault_eth = float(np.clip(snap.vault_eth_balance / self.vault_cap_eth, 0.0, 2.0))
        x2_total_dep = float(np.clip(snap.vault_total_deposited / self.vault_cap_eth, 0.0, 2.0))

        # Smooth indicator around the 5 ETH threshold in VulnerableVault.sol line 53
        x3_drain_thresh = (
            1.0 if snap.vault_eth_balance >= 5.0 else (snap.vault_eth_balance / 5.0)
        )

        # Agent's own stake inside Vault (critical context for withdrawAll vs deposit)
        x4_agent_stake = float(np.clip(snap.agent_vault_balance / self.agent_init_eth, 0.0, 2.0))
        x5_agent_liquid = float(np.clip(snap.agent_eoa_eth_balance / self.agent_init_eth, 0.0, 3.0))

        denom = max(snap.vault_total_deposited, 1.0)
        x6_solvency_gap = float(
            np.clip((snap.vault_eth_balance - snap.vault_total_deposited) / denom, -1.0, 1.0)
        )

        x7_token_share = float(np.clip(snap.agent_token_balance / 1000.0, 0.0, 1.0))
        x8_revert_rate = float(np.clip(snap.recent_revert_rate, 0.0, 1.0))
        x9_code_alive = 1.0 if snap.vault_code_alive else 0.0

        return np.array(
            [
                x0_bias,
                x1_vault_eth,
                x2_total_dep,
                x3_drain_thresh,
                x4_agent_stake,
                x5_agent_liquid,
                x6_solvency_gap,
                x7_token_share,
                x8_revert_rate,
                x9_code_alive,
            ],
            dtype=np.float64,
        )

