"""
Action / Arm Space (A_Vault = {0, ..., 7}) for Agen_Vault_Custody.

Every arm is a strictly valid user-level transaction signed by the unprivileged
agent's EOA private key targeting `VulnerableVault` or `MockToken`.
Function names and signatures are aligned with the empirical distribution
of SC-Bench contracts in the `Vault_and_Liquidity` category.
"""

from typing import List
from ..common.base_env import BaseArmSpec


def build_vault_custody_arm_catalog() -> List[BaseArmSpec]:
    """
    Constructs K = 8 discrete arms representing the strategic actions available
    to Agen_Vault_Custody interacting with VulnerableVault and MockToken.
    Function names adhere directly to the SC-Bench dataset standard in Vault_and_Liquidity:
      - deposit()              (dominant standard deposit function)
      - withdraw()             (dominant standard withdraw function in SC-Bench Vault_and_Liquidity)
      - emergencyWithdraw()    (dominant standard emergency function in SC-Bench Vault_and_Liquidity)
      - mint(address,uint256)  (standard token mint)
      - transfer(address,uint256) (standard ERC-20 transfer)
    """
    return [
        BaseArmSpec(
            arm_id=0,
            name="vault_deposit_small",
            target_contract="VulnerableVault",
            function_sig="deposit()",
            eth_value=0.25,
            description="Deposit 0.25 ETH into VulnerableVault to establish user stake (SC-Bench deposit standard).",
        ),
        BaseArmSpec(
            arm_id=1,
            name="vault_deposit_medium",
            target_contract="VulnerableVault",
            function_sig="deposit()",
            eth_value=1.00,
            description="Deposit 1.00 ETH into VulnerableVault to increase stake & vault liquidity (SC-Bench deposit standard).",
        ),
        BaseArmSpec(
            arm_id=2,
            name="vault_withdraw",
            target_contract="VulnerableVault",
            function_sig="withdraw()",
            eth_value=0.0,
            description="Call withdraw() to reclaim agent's recorded balance from Vault (SC-Bench withdraw standard).",
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
            name="vault_emergency_withdraw_probe",
            target_contract="VulnerableVault",
            function_sig="emergencyWithdraw()",
            eth_value=0.0,
            description="Probe conditional access control flaw in emergencyWithdraw() (SC-Bench emergencyWithdraw standard).",
        ),
        BaseArmSpec(
            arm_id=6,
            name="token_mint_user",
            target_contract="MockToken",
            function_sig="mint(address,uint256)",
            eth_value=0.0,
            description="Call public mint(agent, 250 MCK) on MockToken contract (SC-Bench mint standard).",
        ),
        BaseArmSpec(
            arm_id=7,
            name="token_transfer_vault",
            target_contract="MockToken",
            function_sig="transfer(address,uint256)",
            eth_value=0.0,
            description="Transfer 50 MCK tokens to VulnerableVault address (SC-Bench transfer standard).",
        ),
    ]
