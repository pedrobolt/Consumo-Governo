"""
Desagregação temporal baseada em regressão GLS — Chow-Lin (1971).

Chow & Lin (1971) — "Best Linear Unbiased Interpolation, Distribution,
                     and Extrapolation of Time Series by Related Series"

Model: q_t = β₀ + β₁ p_t + u_t,  u_t = ρ u_{t-1} + ε_t  (AR1 errors)
ρ estimated by MLE on annual aggregates.

All methods satisfy the temporal aggregation constraint: Σ q_t = A_k.
"""

import warnings
import numpy as np
from numpy.linalg import solve, inv
from scipy.optimize import minimize_scalar
from typing import Optional, Tuple


def _aggregation_matrix(n: int, freq: int = 4) -> np.ndarray:
    m = n // freq
    C = np.zeros((m, n))
    for k in range(m):
        C[k, k * freq:(k + 1) * freq] = 1.0
    return C


def _ar1_cov_matrix(n: int, rho: float, sigma2: float = 1.0) -> np.ndarray:
    if abs(rho) >= 1:
        rho = 0.999
    cov = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            cov[i, j] = sigma2 / (1 - rho ** 2) * rho ** abs(i - j)
    return cov


def _mle_rho(X_q: np.ndarray, y_a: np.ndarray,
             C: np.ndarray, freq: int = 4) -> float:
    """Estimate ρ by concentrated MLE; search restricted to [0, 0.999]."""
    n = len(X_q)
    X_a = C @ X_q

    def neg_log_lik(rho):
        try:
            V_q = _ar1_cov_matrix(n, rho)
            V_a = C @ V_q @ C.T
            V_a_inv = inv(V_a)
            M = X_a.T @ V_a_inv @ X_a
            beta = solve(M, X_a.T @ V_a_inv @ y_a)
            resid = y_a - X_a @ beta
            sign, logdet = np.linalg.slogdet(V_a)
            if sign <= 0:
                return 1e10
            return float(0.5 * (logdet + resid @ V_a_inv @ resid))
        except Exception:
            return 1e10

    result = minimize_scalar(neg_log_lik, bounds=(0, 0.999), method="bounded")
    return float(result.x)


def _gls_disaggregate(X_q: np.ndarray, y_a: np.ndarray,
                      V_q: np.ndarray, C: np.ndarray,
                      eps: float = 1e-8) -> np.ndarray:
    """
    GLS temporal disaggregation (core of Chow-Lin).

    Steps:
    1. GLS on annual aggregates: β̂ = (Xa' Va⁻¹ Xa)⁻¹ Xa' Va⁻¹ Ya
    2. Annual residuals: Û_a = Ya − Xa β̂
    3. Distribute residuals: û_q = Vq C' Va⁻¹ Û_a
    4. Result: ŷ_q = Xq β̂ + û_q    (satisfies Σ ŷ_t = Y_k exactly)
    """
    n, m = len(X_q), len(y_a)
    X_a = C @ X_q
    V_a = C @ V_q @ C.T
    V_a_reg = V_a + eps * np.trace(V_a) / m * np.eye(m)

    try:
        V_a_inv = inv(V_a_reg)
    except np.linalg.LinAlgError:
        V_a_inv = np.linalg.pinv(V_a_reg)

    if not np.all(np.isfinite(V_a_inv)):
        V_a_inv = np.eye(m)

    k = X_q.shape[1]
    M = X_a.T @ V_a_inv @ X_a
    M_reg = M + eps * np.trace(M) / k * np.eye(k)

    try:
        beta = solve(M_reg, X_a.T @ V_a_inv @ y_a)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X_a, y_a, rcond=None)[0]

    u_a    = y_a - X_a @ beta
    u_q    = V_q @ C.T @ V_a_inv @ u_a
    result = X_q @ beta + u_q

    if not np.all(np.isfinite(result)):
        warnings.warn("GLS produced non-finite values — falling back to pro_rata.")
        from src.disaggregation.denton import pro_rata
        p = X_q[:, -1] if X_q.ndim > 1 else X_q
        return pro_rata(p, y_a, freq=m)
    return result


def chow_lin(indicator: np.ndarray,
             annual_totals: np.ndarray,
             freq: int = 4,
             rho: Optional[float] = None,
             intercept: bool = True) -> np.ndarray:
    """Chow-Lin (1971) with AR(1) errors; ρ estimated by MLE if not provided."""
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)
    if n != m * freq:
        raise ValueError(f"n={n} ≠ m*freq={m*freq}")

    C   = _aggregation_matrix(n, freq)
    X_q = np.column_stack([np.ones(n), p]) if intercept else p.reshape(-1, 1)

    if rho is None:
        rho = _mle_rho(X_q, a, C, freq)

    return _gls_disaggregate(X_q, a, _ar1_cov_matrix(n, rho), C)


def fit_and_extrapolate(indicator: np.ndarray,
                        annual_totals: np.ndarray,
                        indicator_extrap: np.ndarray,
                        freq: int = 4,
                        method: str = "chow_lin") -> Tuple[np.ndarray, np.ndarray]:
    """
    Fit Chow-Lin on the benchmark period then extrapolate beyond it.

    Annual-constraint residual correction is applied only within the benchmark
    period; extrapolated values are pure regression predictions:
        ŷ_{T+h} = [1, x_{T+h}] @ beta_hat

    Parameters
    ----------
    indicator       : quarterly indicator for benchmark period (n = m*freq,)
    annual_totals   : annual CNT benchmarks (m,)
    indicator_extrap: indicator values to extrapolate (h,)
    freq            : 4 for quarterly
    method          : 'chow_lin' (only supported method)

    Returns
    -------
    fitted : in-sample fitted values (n,)
    extrap : extrapolated values (h,)
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)
    if n != m * freq:
        raise ValueError(f"indicator length {n} != m*freq={m*freq}")
    if method != "chow_lin":
        raise ValueError(f"Only 'chow_lin' is supported; got '{method}'")

    C   = _aggregation_matrix(n, freq)
    X_q = np.column_stack([np.ones(n), p])
    X_a = C @ X_q

    rho = _mle_rho(X_q, a, C, freq)
    V_q = _ar1_cov_matrix(n, rho)

    eps     = 1e-8
    V_a     = C @ V_q @ C.T
    V_a_reg = V_a + eps * np.trace(V_a) / m * np.eye(m)
    try:
        V_inv = inv(V_a_reg)
    except np.linalg.LinAlgError:
        V_inv = np.linalg.pinv(V_a_reg)

    k     = X_q.shape[1]
    M     = X_a.T @ V_inv @ X_a
    M_reg = M + eps * np.trace(M) / k * np.eye(k)
    try:
        beta = solve(M_reg, X_a.T @ V_inv @ a)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X_a, a, rcond=None)[0]

    u_a    = a - X_a @ beta
    u_q    = V_q @ C.T @ V_inv @ u_a
    fitted = X_q @ beta + u_q

    p_ext  = np.asarray(indicator_extrap, dtype=float)
    X_ext  = np.column_stack([np.ones(len(p_ext)), p_ext])
    extrap = X_ext @ beta

    return fitted, extrap
