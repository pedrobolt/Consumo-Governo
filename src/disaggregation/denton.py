"""
Métodos de Denton para desagregação temporal.

Referências:
  Denton (1971) — "Adjustment of monthly or quarterly series to annual totals"
  Bloem, Dippelsman & Mæhle (2001) — IMF Quarterly National Accounts Manual

Métodos:
  denton_proportional — Minimiza Σ[ (q_t/p_t - q_{t-1}/p_{t-1})^2 ]  (paper method)
  pro_rata            — Distribuição proporcional simples (baseline)
"""

import warnings
import numpy as np
from numpy.linalg import pinv, solve


def _aggregation_matrix(n: int, freq: int = 4) -> np.ndarray:
    m = n // freq
    C = np.zeros((m, n))
    for k in range(m):
        C[k, k * freq: (k + 1) * freq] = 1.0
    return C


def _diff_matrix(n: int, order: int = 1) -> np.ndarray:
    D = np.eye(n)
    for _ in range(order):
        D = np.diff(D, axis=0)
    return D


def _DtD_pinv(n: int, order: int = 1, eps: float = 1e-10) -> np.ndarray:
    D = _diff_matrix(n, order)
    DtD = D.T @ D + eps * np.eye(n)
    return pinv(DtD)


def _build_stable_z0(p: np.ndarray, a: np.ndarray, freq: int) -> np.ndarray:
    n, m = len(p), len(a)
    annual_ratios = np.zeros(m)
    for k in range(m):
        s = slice(k * freq, (k + 1) * freq)
        annual_ratios[k] = a[k] / (p[s].sum() + 1e-12)
    midpoints = np.arange(freq / 2, n, freq)
    return np.interp(np.arange(n), midpoints, annual_ratios)


def denton_proportional(indicator: np.ndarray,
                        annual_totals: np.ndarray,
                        freq: int = 4,
                        diff_order: int = 1) -> np.ndarray:
    """
    Denton Proporcional — método do paper.

    Minimizes: Σ_{t=2}^{n} [ (q_t/p_t - q_{t-1}/p_{t-1})^2 ]
    Subject to: Σ_{t ∈ k} q_t = A_k  for each year k
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    if n != m * freq:
        raise ValueError(f"n={n} ≠ m×freq={m}×{freq}={m*freq}")
    if np.any(p <= 0):
        raise ValueError("Indicator must be positive for the proportional method.")

    C  = _aggregation_matrix(n, freq)
    CW = C * p[np.newaxis, :]
    z0 = _build_stable_z0(p, a, freq)
    S  = _DtD_pinv(n, diff_order)
    A_mat = CW @ S @ CW.T
    rhs   = a - CW @ z0

    try:
        z_star = z0 + S @ CW.T @ solve(A_mat, rhs)
    except np.linalg.LinAlgError:
        z_star = z0 + S @ CW.T @ pinv(A_mat) @ rhs

    q = p * z_star
    residual = np.abs(C @ q - a)
    if (residual / (np.abs(a) + 1e-12)).max() > 0.01:
        warnings.warn("Annual constraint not satisfied (max rel. error > 1%).")
    return q


def pro_rata(indicator: np.ndarray,
             annual_totals: np.ndarray,
             freq: int = 4) -> np.ndarray:
    """
    Simple proportional distribution: q_t = p_t * A_k / Σ_{t ∈ k} p_t.
    No cross-year smoothing. Used as baseline comparison.
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)
    q = np.zeros(n)
    for k in range(m):
        s = slice(k * freq, (k + 1) * freq)
        q[s] = p[s] / p[s].sum() * a[k]
    return q
