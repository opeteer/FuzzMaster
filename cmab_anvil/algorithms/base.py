"""
Base abstraction for Contextual Multi-Armed Bandit (CMAB) policies.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import numpy as np


@dataclass
class ArmSelectionResult:
    """
    Diagnostic container returned when a CMAB policy selects an arm.
    """
    arm_id: int
    ucb_score: float
    expected_reward: float
    uncertainty_bonus: float
    all_scores: Dict[int, float] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseCMABPolicy(ABC):
    """
    Abstract Base Class for Contextual Multi-Armed Bandit (CMAB) strategies.

    Formally, at each discrete round t = 1, ..., T:
      1. The agent observes a context vector x_t in R^d (or arm-dependent contexts {x_{t,a}}_{a in A}).
      2. The agent selects an arm a_t in A_t (where A_t subseteq A is the set of feasible arms).
      3. The environment reveals only the scalar reward r_{t, a_t} in R (bandit feedback).
      4. The agent updates its internal parameters to minimize cumulative regret:
         R_T = sum_{t=1}^T (E[r_{t, a_t^*} | x_t] - E[r_{t, a_t} | x_t]).
    """

    def __init__(self, n_arms: int, context_dim: int, name: str = "BaseCMAB"):
        if n_arms <= 0:
            raise ValueError("n_arms must be positive.")
        if context_dim <= 0:
            raise ValueError("context_dim must be positive.")
        self.n_arms = n_arms
        self.context_dim = context_dim
        self.name = name
        self.total_rounds: int = 0
        self.arm_counts = np.zeros(n_arms, dtype=np.int64)
        self.cumulative_reward: float = 0.0

    @abstractmethod
    def select_arm(
        self,
        context: np.ndarray,
        available_arms: Optional[List[int]] = None,
    ) -> ArmSelectionResult:
        """
        Select an arm given the current context vector x_t.
        """
        pass

    @abstractmethod
    def update(self, arm_id: int, context: np.ndarray, reward: float) -> None:
        """
        Update policy parameters after observing bandit feedback (x_t, a_t, r_t).
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """
        Reset all learned parameters to initial priors.
        """
        pass

    def validate_context(self, context: np.ndarray) -> np.ndarray:
        """
        Ensure context is a 1-D float64 numpy vector of shape (context_dim,).
        """
        x = np.asarray(context, dtype=np.float64).reshape(-1)
        if x.shape[0] != self.context_dim:
            raise ValueError(
                f"Context dimension mismatch: expected {self.context_dim}, got {x.shape[0]}"
            )
        return x

