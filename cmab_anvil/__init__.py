"""
Contextual Multi-Armed Bandits (CMAB) Framework for Unprivileged Blockchain Agents on Anvil.

Directory Structure:
  - `algorithms/`         : Universal CMAB strategy templates (`LinUCBTemplate`, `DisjointLinUCB`,
                            `HybridLinUCBTemplate`, `DiscountedLinUCBTemplate`, `DiscountedLinUCB`)
  - `common/`             : Universal Anvil JSON-RPC client & base unprivileged environment
  - `Agen_Vault_Custody/` : Domain-specific CMAB agent for Custody Vault & ERC-20 contracts
"""

from .algorithms import (
    BaseCMABPolicy,
    ArmSelectionResult,
    LinUCBTemplate,
    DisjointLinUCB,
    HybridLinUCBTemplate,
    DiscountedLinUCBTemplate,
    DiscountedLinUCB,
)
from .common import (
    UnprivilegedAnvilClient,
    BaseArmSpec,
    BaseUnprivilegedBanditEnv,
    StepTransition,
)
from .Agen_Vault_Custody import (
    VaultCustodyEnv,
    VaultCustodyCMABAgent,
    CONTEXT_DIM,
    FEATURE_NAMES,
)

__all__ = [
    "BaseCMABPolicy",
    "ArmSelectionResult",
    "LinUCBTemplate",
    "DisjointLinUCB",
    "HybridLinUCBTemplate",
    "DiscountedLinUCBTemplate",
    "DiscountedLinUCB",
    "UnprivilegedAnvilClient",
    "BaseArmSpec",
    "BaseUnprivilegedBanditEnv",
    "StepTransition",
    "VaultCustodyEnv",
    "VaultCustodyCMABAgent",
    "CONTEXT_DIM",
    "FEATURE_NAMES",
]
