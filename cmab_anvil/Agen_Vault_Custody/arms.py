"""
Action / Arm Space (A_Vault = {0, ..., 7}) for Agen_Vault_Custody.

Every arm is a strictly valid user-level transaction signed by the unprivileged
agent's EOA private key targeting `VulnerableVault` or `MockToken`.
"""

from typing import List
from ..common.base_env import BaseArmSpec


def build_vault_custody_arm_catalog() -> List[BaseArmSpec]:
    """
    Constructs K = 8 discrete arms representing the strategic actions available
    to Agen_Vault_Custody interacting with VulnerableVault and MockToken.
    """
    return [
        BaseArmSpec(
            arm_id=0,
            name="vault_deposit_small",
            target_contract="VulnerableVault",
            function_sig="deposit()",
            eth_value=0.25,
            description="Deposit 0.25 ETH into VulnerableVault to establish user stake.",
        ),
        BaseArmSpec(
            arm_id=1,
            name="vault_deposit_medium",
            target_contract="VulnerableVault",
            function_sig="deposit()",
            eth_value=1.00,
            description="Deposit 1.00 ETH into VulnerableVault to increase stake & vault liquidity.",
        ),
        BaseArmSpec(
            arm_id=2,
            name="vault_withdraw_all",
            target_contract="VulnerableVault",
            function_sig="withdrawAll()",
            eth_value=0.0,
            description="Call withdrawAll() to reclaim agent's recorded balance from Vault.",
        ),
        BaseArmSpec(
            arm_id=3,
            name="vault_fallback_transfer",
            target_contract="VulnerableVault",
            function_sig="",
            eth_value=0.10,
            description="Send 0.10 ETH directly via receive() fallback to test accounting parity.",
        ),
        BaseArmSpec(
            arm_id=4,
            name="vault_deposit_zero_probe",
            target_contract="VulnerableVault",
            function_sig="deposit()",
            eth_value=0.0,
            description="Boundary probe: call deposit() with 0 ETH (tests require(msg.value > 0)).",
        ),
        BaseArmSpec(
            arm_id=5,
            name="vault_emergency_drain_probe",
            target_contract="VulnerableVault",
            function_sig="emergencyDrain(address)",
            eth_value=0.0,
            description="Probe conditional access control flaw in emergencyDrain(agent_address).",
        ),
        BaseArmSpec(
            arm_id=6,
            name="token_mint_user",
            target_contract="MockToken",
            function_sig="mint(address,uint256)",
            eth_value=0.0,
            description="Call public mint(agent, 250 MCK) on MockToken contract.",
        ),
        BaseArmSpec(
            arm_id=7,
            name="token_transfer_vault",
            target_contract="MockToken",
            function_sig="transfer(address,uint256)",
            eth_value=0.0,
            description="Transfer 50 MCK tokens to VulnerableVault address (requires MCK balance).",
        ),
    ]

