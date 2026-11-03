"""
LinUCB (Linear Upper Confidence Bound) Strategy Template for Contextual Multi-Armed Bandits.

Reference:
    Li, L., Chu, W., Langford, J., & Schapire, R. E. (2010).
    "A Contextual-Bandit Approach to Personalized News Article Recommendation."
    In Proceedings of the 19th International Conference on World Wide Web (WWW 2010).

Mathematical Formulation (Disjoint LinUCB):
    For each arm a in {0, ..., K-1}, we assume the expected reward is linear in the
    observed d-dimensional context vector x_{t,a} in R^d:
        E[r_{t,a} | x_{t,a}] = x_{t,a}^T theta_a^*

    At round t, each arm maintains:
        A_a = lambda * I_d + sum_{s in T_a(t-1)} x_{s,a} x_{s,a}^T   in R^{d x d}
        b_a = sum_{s in T_a(t-1)} r_{s,a} x_{s,a}                    in R^d

    The ridge regression estimator for arm a is:
        hat{theta}_a = A_a^{-1} b_a

    With probability at least 1 - delta, |x_{t,a}^T hat{theta}_a - x_{t,a}^T theta_a^*|
    is bounded by the confidence width:
        s_{t,a} = alpha * sqrt(x_{t,a}^T A_a^{-1} x_{t,a})

    The agent selects the arm maximizing the Upper Confidence Bound (OFU principle):
        a_t = argmax_{a in A_t} [ x_{t,a}^T hat{theta}_a + alpha * sqrt(x_{t,a}^T A_a^{-1} x_{t,a}) ]
"""

from typing import Dict, List, Optional, Any
import json
from pathlib import Path
import numpy as np

from .base import BaseCMABPolicy, ArmSelectionResult


class LinUCBTemplate(BaseCMABPolicy):
    """
    Template Pattern for LinUCB Policies in Smart Contract / Blockchain Simulation.

    Subclasses or researchers can customize:
      1. `preprocess_context(context, arm_id)` : Feature engineering or arm-context interaction.
      2. `compute_alpha(round_idx)`            : Dynamic or static exploration schedule alpha_t.
      3. `post_update_hook(arm_id, x, reward)` : Custom telemetry, sliding-window forgetting, etc.
    """

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        alpha: float = 1.25,
        l2_lambda: float = 1.0,
        use_sherman_morrison: bool = True,
        gamma_forget: float = 1.0,
        seed: Optional[int] = 42,
        name: str = "LinUCB",
    ):
        """
        Parameters
        ----------
        n_arms : int
            Number of discrete arms (contract interaction strategies).
        context_dim : int
            Dimension d of the context feature vector x_t in R^d.
        alpha : float
            Exploration hyperparameter controlling confidence ellipsoid width (alpha > 0).
        l2_lambda : float
            Ridge regression L2 regularization parameter lambda > 0 (initializes A_a = lambda * I_d).
        use_sherman_morrison : bool
            If True (and gamma_forget == 1.0), updates A_a^{-1} online in O(d^2) via rank-1
            Sherman-Morrison formula instead of O(d^3) full matrix inversion.
        gamma_forget : float
            Discount/forgetting factor in (0, 1] for non-stationary blockchain environments:
            A_a <- gamma * A_a + x x^T + (1 - gamma) * lambda * I_d.
            Set to 1.0 for standard stationary Disjoint LinUCB.
        seed : Optional[int]
            Random seed for tie-breaking.
        """
        super().__init__(n_arms=n_arms, context_dim=context_dim, name=name)
        if alpha < 0.0:
            raise ValueError("alpha must be non-negative.")
        if l2_lambda <= 0.0:
            raise ValueError("l2_lambda must be strictly positive for invertibility.")
        if not (0.0 < gamma_forget <= 1.0):
            raise ValueError("gamma_forget must be in (0.0, 1.0].")

        self.alpha = float(alpha)
        self.l2_lambda = float(l2_lambda)
        self.use_sherman_morrison = bool(use_sherman_morrison and gamma_forget == 1.0)
        self.gamma_forget = float(gamma_forget)
        self.rng = np.random.default_rng(seed)

        # Initialize per-arm sufficient statistics: A_a, A_a^{-1}, b_a, theta_a
        self.A: np.ndarray = np.zeros((n_arms, context_dim, context_dim), dtype=np.float64)
        self.A_inv: np.ndarray = np.zeros((n_arms, context_dim, context_dim), dtype=np.float64)
        self.b: np.ndarray = np.zeros((n_arms, context_dim), dtype=np.float64)
        self.theta: np.ndarray = np.zeros((n_arms, context_dim), dtype=np.float64)
        self.reset()

    def reset(self) -> None:
        """Reset all arm covariance matrices A_a = lambda * I_d and response vectors b_a = 0."""
        self.total_rounds = 0
        self.arm_counts.fill(0)
        self.cumulative_reward = 0.0
        eye = np.eye(self.context_dim, dtype=np.float64)
        for a in range(self.n_arms):
            self.A[a] = self.l2_lambda * eye
            self.A_inv[a] = (1.0 / self.l2_lambda) * eye
            self.b[a].fill(0.0)
            self.theta[a].fill(0.0)

    # -------------------------------------------------------------------------
    # Template Hooks (Customizable by Researchers)
    # -------------------------------------------------------------------------
    def preprocess_context(self, context: np.ndarray, arm_id: int) -> np.ndarray:
        """
        Hook to transform raw context x_t into arm-specific context x_{t, a}.
        By default, returns the validated context vector x_t unchanged.
        """
        return self.validate_context(context)

    def compute_alpha(self, round_idx: int) -> float:
        """
        Hook to compute exploration coefficient alpha_t at round t.
        Can be overridden to implement theoretical schedules:
            alpha_t = sigma * sqrt(d * ln((1 + t / lambda) / delta)) + sqrt(lambda) * ||theta^*||
        By default, returns constant self.alpha.
        """
        return self.alpha

    def post_update_hook(
        self, arm_id: int, x: np.ndarray, reward: float, td_error: float
    ) -> None:
        """
        Optional hook invoked at the end of `update()` for custom logging or diagnostics.
        """
        pass

    # -------------------------------------------------------------------------
    # Core LinUCB Algorithm
    # -------------------------------------------------------------------------
    def select_arm(
        self,
        context: np.ndarray,
        available_arms: Optional[List[int]] = None,
    ) -> ArmSelectionResult:
        """
        Compute UCB_t(a) for all feasible arms and select the maximizer:
            UCB_t(a) = hat{theta}_a^T x_{t,a} + alpha_t * sqrt(x_{t,a}^T A_a^{-1} x_{t,a})
        """
        candidate_arms = (
            list(range(self.n_arms))
            if available_arms is None or len(available_arms) == 0
            else list(available_arms)
        )

        alpha_t = self.compute_alpha(self.total_rounds + 1)
        all_scores: Dict[int, float] = {}
        expected_rewards: Dict[int, float] = {}
        uncertainties: Dict[int, float] = {}

        best_score = -np.inf
        best_arms: List[int] = []

        for a in candidate_arms:
            x_a = self.preprocess_context(context, a)
            theta_a = self.theta[a]

            # Exploitation term: E[r_{t,a} | x_{t,a}] = theta_a^T x_{t,a}
            mean_est = float(np.dot(theta_a, x_a))

            # Exploration bonus (Mahalanobis norm in inverse covariance metric):
            # sqrt(x_{t,a}^T A_a^{-1} x_{t,a})
            quad_form = float(np.dot(x_a, np.dot(self.A_inv[a], x_a)))
            quad_form = max(quad_form, 0.0)  # Guard against floating-point numerical noise
            bonus = alpha_t * np.sqrt(quad_form)

            ucb = mean_est + bonus
            all_scores[a] = ucb
            expected_rewards[a] = mean_est
            uncertainties[a] = bonus

            if ucb > best_score + 1e-12:
                best_score = ucb
                best_arms = [a]
            elif abs(ucb - best_score) <= 1e-12:
                best_arms.append(a)

        # Random tie-breaking among arms achieving maximal UCB score
        chosen_arm = int(self.rng.choice(best_arms))

        return ArmSelectionResult(
            arm_id=chosen_arm,
            ucb_score=all_scores[chosen_arm],
            expected_reward=expected_rewards[chosen_arm],
            uncertainty_bonus=uncertainties[chosen_arm],
            all_scores=all_scores,
            metadata={
                "alpha_t": alpha_t,
                "arm_pulls": int(self.arm_counts[chosen_arm]),
                "expected_rewards": expected_rewards,
                "uncertainties": uncertainties,
            },
        )

    def update(self, arm_id: int, context: np.ndarray, reward: float) -> None:
        """
        Update linear ridge regression sufficient statistics (A_a, b_a, theta_a) for chosen arm.
        """
        if not (0 <= arm_id < self.n_arms):
            raise ValueError(f"Invalid arm_id {arm_id}; expected 0 <= arm_id < {self.n_arms}.")

        x = self.preprocess_context(context, arm_id)
        r = float(reward)

        pred_before = float(np.dot(self.theta[arm_id], x))
        prediction_error = r - pred_before

        # Update matrix A_a and vector b_a
        outer_xx = np.outer(x, x)
        if self.gamma_forget < 1.0:
            # Non-stationary discounted LinUCB update
            eye = np.eye(self.context_dim, dtype=np.float64)
            self.A[arm_id] = (
                self.gamma_forget * self.A[arm_id]
                + outer_xx
                + (1.0 - self.gamma_forget) * self.l2_lambda * eye
            )
            self.b[arm_id] = self.gamma_forget * self.b[arm_id] + r * x
            self.A_inv[arm_id] = np.linalg.inv(self.A[arm_id])
        else:
            # Standard stationary LinUCB update
            self.A[arm_id] += outer_xx
            self.b[arm_id] += r * x

            if self.use_sherman_morrison:
                # O(d^2) Sherman-Morrison rank-1 update:
                # (A + x x^T)^{-1} = A^{-1} - (A^{-1} x x^T A^{-1}) / (1 + x^T A^{-1} x)
                A_inv_x = np.dot(self.A_inv[arm_id], x)
                denom = 1.0 + float(np.dot(x, A_inv_x))
                self.A_inv[arm_id] -= np.outer(A_inv_x, A_inv_x) / denom
            else:
                self.A_inv[arm_id] = np.linalg.inv(self.A[arm_id])

        # Recompute parameter estimate theta_a = A_a^{-1} b_a
        self.theta[arm_id] = np.dot(self.A_inv[arm_id], self.b[arm_id])

        self.total_rounds += 1
        self.arm_counts[arm_id] += 1
        self.cumulative_reward += r

        self.post_update_hook(arm_id, x, r, prediction_error)

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return policy state summary for telemetry and evaluation."""
        theta_norms = [float(np.linalg.norm(self.theta[a])) for a in range(self.n_arms)]
        return {
            "policy_name": self.name,
            "total_rounds": self.total_rounds,
            "cumulative_reward": self.cumulative_reward,
            "mean_reward": (
                self.cumulative_reward / self.total_rounds if self.total_rounds > 0 else 0.0
            ),
            "arm_counts": self.arm_counts.tolist(),
            "theta_l2_norms": theta_norms,
            "alpha": self.alpha,
            "l2_lambda": self.l2_lambda,
            "gamma_forget": self.gamma_forget,
        }

    def save_checkpoint(self, path: Path) -> None:
        """Persist LinUCB matrices and parameters to JSON."""
        data = {
            "name": self.name,
            "n_arms": self.n_arms,
            "context_dim": self.context_dim,
            "alpha": self.alpha,
            "l2_lambda": self.l2_lambda,
            "gamma_forget": self.gamma_forget,
            "total_rounds": self.total_rounds,
            "cumulative_reward": self.cumulative_reward,
            "arm_counts": self.arm_counts.tolist(),
            "A": self.A.tolist(),
            "b": self.b.tolist(),
            "theta": self.theta.tolist(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))


class DisjointLinUCB(LinUCBTemplate):
    """
    Concrete Disjoint LinUCB implementation ready for direct deployment.
    Maintains disjoint parameter vectors theta_a in R^d for each arm a in A.
    """

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        alpha: float = 1.25,
        l2_lambda: float = 1.0,
        gamma_forget: float = 1.0,
        seed: Optional[int] = 42,
    ):
        super().__init__(
            n_arms=n_arms,
            context_dim=context_dim,
            alpha=alpha,
            l2_lambda=l2_lambda,
            use_sherman_morrison=(gamma_forget == 1.0),
            gamma_forget=gamma_forget,
            seed=seed,
            name="DisjointLinUCB",
        )


class HybridLinUCBTemplate(BaseCMABPolicy):
    """
    Template for Hybrid LinUCB (Li et al., 2010, Algorithm 2) with shared cross-arm parameters:
        E[r_{t,a} | x_{t,a}, z_{t,a}] = z_{t,a}^T beta^* + x_{t,a}^T theta_a^*
    where:
      - z_{t,a} in R^k are shared features across arms (e.g., global gas cost sensitivity).
      - x_{t,a} in R^d are arm-specific features.
    """

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        shared_dim: int,
        alpha: float = 1.25,
        l2_lambda: float = 1.0,
        seed: Optional[int] = 42,
    ):
        super().__init__(n_arms=n_arms, context_dim=context_dim, name="HybridLinUCB")
        self.shared_dim = shared_dim
        self.alpha = float(alpha)
        self.l2_lambda = float(l2_lambda)
        self.rng = np.random.default_rng(seed)
        self.reset()

    def reset(self) -> None:
        self.total_rounds = 0
        self.arm_counts.fill(0)
        self.cumulative_reward = 0.0
        self.A0 = self.l2_lambda * np.eye(self.shared_dim, dtype=np.float64)
        self.b0 = np.zeros(self.shared_dim, dtype=np.float64)
        self.A = np.array(
            [self.l2_lambda * np.eye(self.context_dim, dtype=np.float64) for _ in range(self.n_arms)]
        )
        self.B = np.zeros((self.n_arms, self.context_dim, self.shared_dim), dtype=np.float64)
        self.b = np.zeros((self.n_arms, self.context_dim), dtype=np.float64)

    def extract_shared_features(self, context: np.ndarray, arm_id: int) -> np.ndarray:
        """
        Template method: construct shared feature vector z_{t,a} in R^k.
        Default takes the first `shared_dim` features modulated by normalized arm index.
        """
        x = self.validate_context(context)
        z = np.zeros(self.shared_dim, dtype=np.float64)
        take = min(self.shared_dim, x.shape[0])
        z[:take] = x[:take] * ((arm_id + 1.0) / self.n_arms)
        return z

    def select_arm(
        self,
        context: np.ndarray,
        available_arms: Optional[List[int]] = None,
    ) -> ArmSelectionResult:
        x = self.validate_context(context)
        candidate_arms = (
            list(range(self.n_arms))
            if available_arms is None or len(available_arms) == 0
            else list(available_arms)
        )
        A0_inv = np.linalg.inv(self.A0)
        beta_hat = np.dot(A0_inv, self.b0)

        all_scores: Dict[int, float] = {}
        expected_rewards: Dict[int, float] = {}
        uncertainties: Dict[int, float] = {}
        best_score = -np.inf
        best_arms: List[int] = []

        for a in candidate_arms:
            z_a = self.extract_shared_features(x, a)
            A_a_inv = np.linalg.inv(self.A[a])
            theta_a = np.dot(A_a_inv, self.b[a] - np.dot(self.B[a], beta_hat))

            mean_est = float(np.dot(z_a, beta_hat) + np.dot(x, theta_a))

            # Hybrid variance term s_{t,a}
            B_T_A_inv_x = np.dot(self.B[a].T, np.dot(A_a_inv, x))
            s1 = float(np.dot(z_a, np.dot(A0_inv, z_a)))
            s2 = -2.0 * float(np.dot(z_a, np.dot(A0_inv, B_T_A_inv_x)))
            s3 = float(np.dot(x, np.dot(A_a_inv, x)))
            s4 = float(np.dot(B_T_A_inv_x, np.dot(A0_inv, B_T_A_inv_x)))
            var = max(s1 + s2 + s3 + s4, 0.0)
            bonus = self.alpha * np.sqrt(var)

            ucb = mean_est + bonus
            all_scores[a] = ucb
            expected_rewards[a] = mean_est
            uncertainties[a] = bonus

            if ucb > best_score + 1e-12:
                best_score = ucb
                best_arms = [a]
            elif abs(ucb - best_score) <= 1e-12:
                best_arms.append(a)

        chosen_arm = int(self.rng.choice(best_arms))
        return ArmSelectionResult(
            arm_id=chosen_arm,
            ucb_score=all_scores[chosen_arm],
            expected_reward=expected_rewards[chosen_arm],
            uncertainty_bonus=uncertainties[chosen_arm],
            all_scores=all_scores,
            metadata={"beta_norm": float(np.linalg.norm(beta_hat))},
        )

    def update(self, arm_id: int, context: np.ndarray, reward: float) -> None:
        x = self.validate_context(context)
        z = self.extract_shared_features(x, arm_id)
        r = float(reward)

        A_a_inv = np.linalg.inv(self.A[arm_id])
        self.A0 += np.dot(self.B[arm_id].T, np.dot(A_a_inv, self.B[arm_id]))
        self.b0 += np.dot(self.B[arm_id].T, np.dot(A_a_inv, self.b[arm_id]))

        self.A[arm_id] += np.outer(x, x)
        self.B[arm_id] += np.outer(x, z)
        self.b[arm_id] += r * x

        A_a_inv_new = np.linalg.inv(self.A[arm_id])
        self.A0 += np.outer(z, z) - np.dot(self.B[arm_id].T, np.dot(A_a_inv_new, self.B[arm_id]))
        self.b0 += r * z - np.dot(self.B[arm_id].T, np.dot(A_a_inv_new, self.b[arm_id]))

        self.total_rounds += 1
        self.arm_counts[arm_id] += 1
        self.cumulative_reward += r

