"""
Discounted LinUCB (D-LinUCB) Strategy Template for Non-Stationary Contextual Bandits.

Reference:
    Russac, Y., Vernade, C., & Cappé, O. (2019).
    "Weighted Linear Bandits for Non-Stationary Environments."
    In Advances in Neural Information Processing Systems (NeurIPS 2019), Vol. 32.

Mathematical Formulation (D-LinUCB):
    In non-stationary environments (such as stateful smart contracts undergoing liquidity
    shifts, access-control state transitions, or insolvency events), the true reward
    parameter vector theta_{t,a}^* in R^d drifts or switches across rounds t = 1, ..., T:
        E[r_{t,a} | x_{t,a}] = x_{t,a}^T theta_{t,a}^*

    To adapt to regime changes, D-LinUCB applies exponential discounting with factor
    gamma in (0, 1). For each arm a in {0, ..., K-1}, it maintains TWO covariance matrices
    and ONE weighted response vector:

    1. Discounted Design Matrix (weights gamma^{t-s}):
        V_{t,a} = lambda * I_d + sum_{s in T_a(t-1)} gamma^{t-1-s} x_{s,a} x_{s,a}^T

    2. Squared-Discount Noise Covariance Matrix (weights gamma^{2(t-s)}):
        tilde{V}_{t,a} = lambda * (I_d) + sum_{s in T_a(t-1)} gamma^{2(t-1-s)} x_{s,a} x_{s,a}^T

    3. Discounted Reward-Weighted Context Vector:
        b_{t,a} = sum_{s in T_a(t-1)} gamma^{t-1-s} r_{s,a} x_{s,a}

    4. Weighted Ridge Regression Estimator:
        hat{theta}_{t,a} = V_{t,a}^{-1} b_{t,a}

    5. Sandwiched Confidence Ellipsoid & Upper Confidence Bound (Russac et al., Theorem 1):
        s_{t,a} = sqrt( x_{t,a}^T V_{t,a}^{-1} tilde{V}_{t,a} V_{t,a}^{-1} x_{t,a} )
        UCB_t(a) = hat{theta}_{t,a}^T x_{t,a} + beta_{t,a} * s_{t,a}

    where the theoretical confidence radius beta_{t,a} is:
        beta_{t,a} = alpha * [ sqrt(lambda) * S + sigma * sqrt( 2 ln(1 / delta)
                     + d * ln( 1 + (L^2 (1 - gamma^{2 t_a})) / (lambda * d * (1 - gamma^2)) ) ) ]
"""

from typing import Dict, List, Optional, Any
import json
from pathlib import Path
import numpy as np

from .base import BaseCMABPolicy, ArmSelectionResult


class DiscountedLinUCBTemplate(BaseCMABPolicy):
    """
    Template Pattern for Discounted LinUCB (D-LinUCB) in Non-Stationary Blockchain Environments.

    Key Capabilities:
      - Dual-matrix sandwich variance estimation: V_a^{-1} @ V_tilde_a @ V_a^{-1}.
      - Synchronous exponential decay across all arms (`decay_all_arms=True`) so idle arms
        gradually recover their prior uncertainty and re-explore after on-chain regime shifts.
      - Effective Sample Size (ESS) tracking per arm: N_eff(a) = sum gamma^{t-s}.
      - Customizable hooks (`preprocess_context`, `compute_beta`, `post_update_hook`).
    """

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        gamma: float = 0.85,
        alpha: float = 1.0,
        l2_lambda: float = 1.0,
        delta: float = 0.05,
        sigma_noise: float = 0.5,
        param_norm_bound: float = 1.0,
        context_norm_bound: float = 2.5,
        use_theoretical_beta: bool = True,
        decay_all_arms: bool = True,
        seed: Optional[int] = 42,
        name: str = "DiscountedLinUCB",
    ):
        """
        Parameters
        ----------
        n_arms : int
            Number of discrete arms K.
        context_dim : int
            Dimension d of the context vector x_t in R^d.
        gamma : float
            Exponential discount factor in (0, 1]. Values in [0.75, 0.95] are typical
            for non-stationary environments; gamma == 1.0 recovers stationary LinUCB.
        alpha : float
            Exploration scaling multiplier (> 0). Scales the theoretical radius beta_{t,a}
            when `use_theoretical_beta=True`, or serves directly as beta when False.
        l2_lambda : float
            Ridge regularization parameter lambda > 0.
        delta : float
            Failure probability delta in (0, 1) for the high-probability confidence bound.
        sigma_noise : float
            Sub-Gaussian noise scale sigma > 0 of the reward signal.
        param_norm_bound : float
            Assumed upper bound S >= ||theta_{t,a}^*||_2.
        context_norm_bound : float
            Assumed upper bound L >= ||x_{t,a}||_2.
        use_theoretical_beta : bool
            If True, computes the Russac et al. (2019) analytical confidence radius beta_{t,a}.
            If False, uses constant `alpha` directly as the exploration multiplier.
        decay_all_arms : bool
            If True, applies exponential decay to ALL arms at every round t (global clock),
            allowing unpulled arms to gradually return to prior uncertainty for re-exploration.
            If False, decays an arm only when it is pulled (arm-local clock).
        seed : Optional[int]
            Random seed for tie-breaking.
        """
        super().__init__(n_arms=n_arms, context_dim=context_dim, name=name)
        if not (0.0 < gamma <= 1.0):
            raise ValueError("gamma must be in (0.0, 1.0].")
        if alpha < 0.0:
            raise ValueError("alpha must be non-negative.")
        if l2_lambda <= 0.0:
            raise ValueError("l2_lambda must be strictly positive.")
        if not (0.0 < delta < 1.0):
            raise ValueError("delta must be in (0.0, 1.0).")

        self.gamma = float(gamma)
        self.gamma_sq = float(gamma * gamma)
        self.alpha = float(alpha)
        self.l2_lambda = float(l2_lambda)
        self.delta = float(delta)
        self.sigma_noise = float(sigma_noise)
        self.param_norm_bound = float(param_norm_bound)
        self.context_norm_bound = float(context_norm_bound)
        self.use_theoretical_beta = bool(use_theoretical_beta)
        self.decay_all_arms = bool(decay_all_arms)
        self.rng = np.random.default_rng(seed)

        # Dual covariance matrices V_a (weight gamma), V_tilde_a (weight gamma^2),
        # inverse V_inv_a, response vector b_a, parameter estimate theta_a, and ESS
        self.V: np.ndarray = np.zeros((n_arms, context_dim, context_dim), dtype=np.float64)
        self.V_tilde: np.ndarray = np.zeros((n_arms, context_dim, context_dim), dtype=np.float64)
        self.V_inv: np.ndarray = np.zeros((n_arms, context_dim, context_dim), dtype=np.float64)
        self.b: np.ndarray = np.zeros((n_arms, context_dim), dtype=np.float64)
        self.theta: np.ndarray = np.zeros((n_arms, context_dim), dtype=np.float64)
        self.effective_pulls: np.ndarray = np.zeros(n_arms, dtype=np.float64)
        self.reset()

    def reset(self) -> None:
        """Reset V_a = lambda * I_d, V_tilde_a = lambda * I_d, b_a = 0, and ESS = 0."""
        self.total_rounds = 0
        self.arm_counts.fill(0)
        self.effective_pulls.fill(0.0)
        self.cumulative_reward = 0.0

        eye = np.eye(self.context_dim, dtype=np.float64)
        for a in range(self.n_arms):
            self.V[a] = self.l2_lambda * eye
            self.V_tilde[a] = self.l2_lambda * eye
            self.V_inv[a] = (1.0 / self.l2_lambda) * eye
            self.b[a].fill(0.0)
            self.theta[a].fill(0.0)

    # -------------------------------------------------------------------------
    # Template Hooks (Customizable by Researchers)
    # -------------------------------------------------------------------------
    def preprocess_context(self, context: np.ndarray, arm_id: int) -> np.ndarray:
        """
        Hook to transform raw context x_t into arm-specific context x_{t, a}.
        """
        return self.validate_context(context)

    def compute_beta(self, arm_id: int) -> float:
        """
        Compute the D-LinUCB confidence ellipsoid multiplier beta_{t,a}
        (Russac, Vernade, & Cappé, NeurIPS 2019, Proposition 1 / Theorem 1):

            beta_{t,a} = alpha * [ sqrt(lambda) * S + sigma * sqrt(
                2 * ln(1 / delta) + d * ln(1 + (L^2 * H_t) / (lambda * d))
            ) ]
        where H_t = (1 - gamma^{2 * t_eff}) / (1 - gamma^2) for gamma < 1, else t_eff.
        """
        if not self.use_theoretical_beta:
            return self.alpha

        t_horizon = (
            float(self.total_rounds + 1)
            if self.decay_all_arms
            else float(self.arm_counts[arm_id] + 1)
        )
        if self.gamma < 1.0 - 1e-9:
            effective_horizon = (1.0 - (self.gamma_sq ** t_horizon)) / (1.0 - self.gamma_sq)
        else:
            effective_horizon = t_horizon

        d = float(self.context_dim)
        log_det_bound = d * np.log(
            1.0
            + (self.context_norm_bound ** 2)
            * effective_horizon
            / (self.l2_lambda * d)
        )
        confidence_term = self.sigma_noise * np.sqrt(
            2.0 * np.log(1.0 / self.delta) + log_det_bound
        )
        bias_regularization_term = np.sqrt(self.l2_lambda) * self.param_norm_bound

        return float(self.alpha * (bias_regularization_term + confidence_term))

    def post_update_hook(
        self, arm_id: int, x: np.ndarray, reward: float, td_error: float
    ) -> None:
        """Optional hook called after each `update()` step."""
        pass

    # -------------------------------------------------------------------------
    # Core Discounted LinUCB Algorithm
    # -------------------------------------------------------------------------
    def _compute_sandwich_radius(self, arm_id: int, x_a: np.ndarray) -> float:
        """
        Compute the sandwiched Mahalanobis confidence width:
            s_{t,a} = sqrt( x_a^T @ V_a^{-1} @ V_tilde_a @ V_a^{-1} @ x_a )
        Note: Let u = V_a^{-1} @ x_a. Then s_{t,a} = sqrt( u^T @ V_tilde_a @ u ),
        which requires only O(d^2) matrix-vector products!
        """
        u = np.dot(self.V_inv[arm_id], x_a)
        quad = float(np.dot(u, np.dot(self.V_tilde[arm_id], u)))
        return float(np.sqrt(max(quad, 0.0)))

    def select_arm(
        self,
        context: np.ndarray,
        available_arms: Optional[List[int]] = None,
    ) -> ArmSelectionResult:
        """
        Select the arm maximizing the Discounted Upper Confidence Bound:
            UCB_t(a) = hat{theta}_{t,a}^T x_{t,a} + beta_{t,a} * sqrt(x_{t,a}^T V_{t,a}^{-1} tilde{V}_{t,a} V_{t,a}^{-1} x_{t,a})
        """
        candidate_arms = (
            list(range(self.n_arms))
            if available_arms is None or len(available_arms) == 0
            else list(available_arms)
        )

        all_scores: Dict[int, float] = {}
        expected_rewards: Dict[int, float] = {}
        uncertainties: Dict[int, float] = {}
        betas: Dict[int, float] = {}

        best_score = -np.inf
        best_arms: List[int] = []

        for a in candidate_arms:
            x_a = self.preprocess_context(context, a)
            mean_est = float(np.dot(self.theta[a], x_a))

            beta_a = self.compute_beta(a)
            sandwich_radius = self._compute_sandwich_radius(a, x_a)
            bonus = beta_a * sandwich_radius

            ucb = mean_est + bonus
            all_scores[a] = ucb
            expected_rewards[a] = mean_est
            uncertainties[a] = bonus
            betas[a] = beta_a

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
            metadata={
                "gamma": self.gamma,
                "beta_chosen": betas[chosen_arm],
                "effective_pulls_chosen": float(self.effective_pulls[chosen_arm]),
                "arm_pulls": int(self.arm_counts[chosen_arm]),
                "expected_rewards": expected_rewards,
                "uncertainties": uncertainties,
            },
        )

    def _decay_single_arm(self, arm_id: int, eye: np.ndarray) -> None:
        """
        Apply exponential discounting to arm `arm_id` while preserving the prior lambda * I_d:
            V_a       <- gamma * V_a + (1 - gamma) * lambda * I_d
            V_tilde_a <- gamma^2 * V_tilde_a + (1 - gamma^2) * lambda * I_d
            b_a       <- gamma * b_a
            ESS_a     <- gamma * ESS_a
        """
        if self.gamma >= 1.0 - 1e-12:
            return

        self.V[arm_id] = (
            self.gamma * self.V[arm_id]
            + (1.0 - self.gamma) * self.l2_lambda * eye
        )
        self.V_tilde[arm_id] = (
            self.gamma_sq * self.V_tilde[arm_id]
            + (1.0 - self.gamma_sq) * self.l2_lambda * eye
        )
        self.b[arm_id] *= self.gamma
        self.effective_pulls[arm_id] *= self.gamma

    def update(self, arm_id: int, context: np.ndarray, reward: float) -> None:
        """
        Update D-LinUCB sufficient statistics (V_a, V_tilde_a, b_a, theta_a).
        """
        if not (0 <= arm_id < self.n_arms):
            raise ValueError(f"Invalid arm_id {arm_id}; expected 0 <= arm_id < {self.n_arms}.")

        x = self.preprocess_context(context, arm_id)
        r = float(reward)

        pred_before = float(np.dot(self.theta[arm_id], x))
        prediction_error = r - pred_before

        eye = np.eye(self.context_dim, dtype=np.float64)

        # Step 1: Exponential decay of historical observations
        if self.decay_all_arms:
            for a in range(self.n_arms):
                self._decay_single_arm(a, eye)
        else:
            self._decay_single_arm(arm_id, eye)

        # Step 2: Incorporate current observation (x_{t, a_t}, r_t) with weight 1.0
        outer_xx = np.outer(x, x)
        self.V[arm_id] += outer_xx
        self.V_tilde[arm_id] += outer_xx
        self.b[arm_id] += r * x
        self.effective_pulls[arm_id] += 1.0

        # Step 3: Recompute matrix inverses and parameter estimates
        if self.decay_all_arms and self.gamma < 1.0 - 1e-12:
            for a in range(self.n_arms):
                self.V_inv[a] = np.linalg.inv(self.V[a])
                self.theta[a] = np.dot(self.V_inv[a], self.b[a])
        else:
            self.V_inv[arm_id] = np.linalg.inv(self.V[arm_id])
            self.theta[arm_id] = np.dot(self.V_inv[arm_id], self.b[arm_id])

        self.total_rounds += 1
        self.arm_counts[arm_id] += 1
        self.cumulative_reward += r

        self.post_update_hook(arm_id, x, r, prediction_error)

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return D-LinUCB diagnostics including Effective Sample Size (ESS) per arm."""
        theta_norms = [float(np.linalg.norm(self.theta[a])) for a in range(self.n_arms)]
        return {
            "policy_name": self.name,
            "total_rounds": self.total_rounds,
            "cumulative_reward": self.cumulative_reward,
            "mean_reward": (
                self.cumulative_reward / self.total_rounds if self.total_rounds > 0 else 0.0
            ),
            "arm_counts": self.arm_counts.tolist(),
            "effective_pulls": [round(float(v), 4) for v in self.effective_pulls],
            "theta_l2_norms": theta_norms,
            "gamma": self.gamma,
            "alpha": self.alpha,
            "l2_lambda": self.l2_lambda,
            "delta": self.delta,
            "use_theoretical_beta": self.use_theoretical_beta,
            "decay_all_arms": self.decay_all_arms,
        }

    def save_checkpoint(self, path: Path) -> None:
        """Persist D-LinUCB dual matrices and parameters to JSON."""
        data = {
            "name": self.name,
            "n_arms": self.n_arms,
            "context_dim": self.context_dim,
            "gamma": self.gamma,
            "alpha": self.alpha,
            "l2_lambda": self.l2_lambda,
            "delta": self.delta,
            "use_theoretical_beta": self.use_theoretical_beta,
            "decay_all_arms": self.decay_all_arms,
            "total_rounds": self.total_rounds,
            "cumulative_reward": self.cumulative_reward,
            "arm_counts": self.arm_counts.tolist(),
            "effective_pulls": self.effective_pulls.tolist(),
            "V": self.V.tolist(),
            "V_tilde": self.V_tilde.tolist(),
            "b": self.b.tolist(),
            "theta": self.theta.tolist(),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))


class DiscountedLinUCB(DiscountedLinUCBTemplate):
    """
    Concrete Discounted LinUCB (D-LinUCB) policy ready for direct deployment
    in non-stationary smart contract simulations.
    """

    def __init__(
        self,
        n_arms: int,
        context_dim: int,
        gamma: float = 0.85,
        alpha: float = 0.5,
        l2_lambda: float = 1.0,
        delta: float = 0.05,
        sigma_noise: float = 0.5,
        use_theoretical_beta: bool = True,
        decay_all_arms: bool = True,
        seed: Optional[int] = 42,
    ):
        super().__init__(
            n_arms=n_arms,
            context_dim=context_dim,
            gamma=gamma,
            alpha=alpha,
            l2_lambda=l2_lambda,
            delta=delta,
            sigma_noise=sigma_noise,
            use_theoretical_beta=use_theoretical_beta,
            decay_all_arms=decay_all_arms,
            seed=seed,
            name="DiscountedLinUCB",
        )

