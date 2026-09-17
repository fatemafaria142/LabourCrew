from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CalibrationResult:
    tau: float
    alpha: float
    n: int
    empirical_risk: float  # R_hat(tau) on the calibration set
    risk_bound: float  # (n/(n+1))*R_hat(tau) + 1/(n+1) -- must be <= alpha
    n_accepted: int  # claims with trust_score >= tau in the calibration set
    tau_grid_exhausted: bool  # True if no tau in the grid controlled risk at alpha


def false_accept_rate(scores: list[float], faithful: list[bool], tau: float) -> tuple[float, int]:
    """R_hat(tau): fraction of calibration claims that are accepted (score >= tau)
    AND unfaithful. Returns (risk, n_accepted)."""
    if not scores:
        return 0.0, 0
    n = len(scores)
    accepted_unfaithful = sum(1 for s, f in zip(scores, faithful) if s >= tau and not f)
    n_accepted = sum(1 for s in scores if s >= tau)
    return accepted_unfaithful / n, n_accepted


def calibrate_tau(
    scores: list[float],
    faithful: list[bool],
    alpha: float,
    tau_grid: list[float] | None = None,
) -> CalibrationResult:
    """Select the smallest tau satisfying the Conformal Risk Control bound at `alpha`.

    `scores` and `faithful` must be aligned, one entry per calibration claim,
    drawn exchangeably with the claims the Trust Gate will see at deployment
    (the gold QA set extended with a per-claim `faithful` label).

    If no tau in the grid controls risk at this alpha (e.g. too few
    calibration examples, or too many unfaithful claims at every score),
    the gate fails closed: tau = +inf, i.e. reject everything, rather than
    silently returning an uncalibrated threshold.
    """
    if len(scores) != len(faithful):
        raise ValueError("scores and faithful must be the same length")
    if not scores:
        raise ValueError("calibration set is empty")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")

    n = len(scores)
    grid = sorted(set(tau_grid) if tau_grid is not None else set(scores) | {0.0, 1.0})

    for tau in grid:
        risk_hat, n_accepted = false_accept_rate(scores, faithful, tau)
        bound = (n / (n + 1)) * risk_hat + 1 / (n + 1)
        if bound <= alpha:
            return CalibrationResult(
                tau=tau,
                alpha=alpha,
                n=n,
                empirical_risk=risk_hat,
                risk_bound=bound,
                n_accepted=n_accepted,
                tau_grid_exhausted=False,
            )

    # No tau in the grid controls risk at this alpha -- fail closed.
    risk_hat, n_accepted = false_accept_rate(scores, faithful, grid[-1] + 1.0)
    return CalibrationResult(
        tau=float("inf"),
        alpha=alpha,
        n=n,
        empirical_risk=risk_hat,
        risk_bound=1.0 / (n + 1),
        n_accepted=n_accepted,
        tau_grid_exhausted=True,
    )
