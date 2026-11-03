"""
Algorithm templates and policies for Contextual Multi-Armed Bandits (CMAB).
"""

from .base import BaseCMABPolicy, ArmSelectionResult
from .linucb import LinUCBTemplate, DisjointLinUCB, HybridLinUCBTemplate
from .discounted_linucb import DiscountedLinUCBTemplate, DiscountedLinUCB

__all__ = [
    "BaseCMABPolicy",
    "ArmSelectionResult",
    "LinUCBTemplate",
    "DisjointLinUCB",
    "HybridLinUCBTemplate",
    "DiscountedLinUCBTemplate",
    "DiscountedLinUCB",
]
