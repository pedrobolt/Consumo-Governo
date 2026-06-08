"""
Métodos de desagregação temporal baseados em regressão.

Referências:
  Chow & Lin (1971) – "Best Linear Unbiased Interpolation, Distribution,
                       and Extrapolation of Time Series by Related Series"
  Fernandez (1981) – "A Methodological Note on the Estimation of Time Series"
  Litterman (1983) – "A Random Walk, Markov Model for the Distribution of Time
                      Series"

Resumo dos métodos:
  Chow-Lin   : erros AR(1) estacionários, ρ estimado por MLE
  Fernandez  : erros I(1) — passeio aleatório (ρ → 1)
  Litterman  : erros ARIMA(1,1,0) (AR1 + diferença)
  GLS simples: OLS anual sem estrutura de autocorrelação

Todos satisfazem a restrição de adição temporal: Σ q_t = A_k por construção.
"""

import warnings
import numpy as np
from numpy.linalg import solve, inv
from scipy.optimize import minimize_scalar
from typing import Optional, Tuple
import pandas as pd


# ──────────────────────────────────────────────────────────────────────────────
# Utilitários
# ──────────────────────────────────────────────────────────────────────────────

def _aggregation_matrix(n: int, freq: int = 4) -> np.ndarray:
    m = n // freq
    C = np.zeros((m, n))
    for k in range(m):
        C[k, k * freq:(k + 1) * freq] = 1.0
    return C


def _ar1_cov_matrix(n: int, rho: float, sigma2: float = 1.0) -> np.ndarray:
    """Matriz de covariância AR(1) de dimensão n×n."""
    if abs(rho) >= 1:
        # Tratar como random walk
        return _rw_cov_matrix(n, sigma2)
    cov = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            cov[i, j] = sigma2 / (1 - rho ** 2) * rho ** abs(i - j)
    return cov


def _rw_cov_matrix(n: int, sigma2: float = 1.0, eps: float = 1e-6) -> np.ndarray:
    """
    Matriz de covariância de passeio aleatório (Fernandez).
    V = σ² (D'D + ε I)^{-1}  — regularização para estabilidade numérica.
    """
    D = np.diff(np.eye(n), axis=0)
    DtD = D.T @ D + eps * np.eye(n)
    return sigma2 * np.linalg.inv(DtD)


def _ar1_rw_cov_matrix(n: int, rho: float, sigma2: float = 1.0,
                        eps: float = 1e-6) -> np.ndarray:
    """
    Matriz de covariância para Litterman: ARIMA(1,1,0).

    u_t = ρ u_{t-1} + Δ^{-1}ε_t (integrado AR1).
    Implementação: V = σ² [D' H D]^{-1}  onde H = matriz AR1.
    Regularizado para estabilidade numérica.
    """
    D = np.diff(np.eye(n), axis=0)   # (n-1) × n

    # Matriz AR1 para as diferenças (n-1 × n-1)
    H = np.zeros((n - 1, n - 1))
    for i in range(n - 1):
        for j in range(n - 1):
            H[i, j] = rho ** abs(i - j)
    H /= (1 - rho ** 2 + 1e-10)

    # V = [D' H^{-1} D + eps I]^{-1}
    try:
        H_inv = np.linalg.inv(H + eps * np.eye(n - 1))
        DtHD = D.T @ H_inv @ D + eps * np.eye(n)
        return sigma2 * np.linalg.inv(DtHD)
    except np.linalg.LinAlgError:
        return _rw_cov_matrix(n, sigma2, eps)


# ──────────────────────────────────────────────────────────────────────────────
# Estimador GLS geral
# ──────────────────────────────────────────────────────────────────────────────

def _gls_disaggregate(X_q: np.ndarray, y_a: np.ndarray,
                      V_q: np.ndarray, C: np.ndarray,
                      eps: float = 1e-8) -> np.ndarray:
    """
    Estimador GLS para desagregação temporal (núcleo dos três métodos).

    Modelo: y_t = X_t β + u_t,  u_t ~ (0, V_q)
    Anual:  Y_k = Σ X_t β + U_k, U ~ (0, V_a)

    Passos:
    1. GLS anual: β̂ = (Xa' Va^{-1} Xa)^{-1} Xa' Va^{-1} Ya
    2. Resíduos anuais: Û_a = Ya - Xa β̂
    3. Distribuição dos resíduos: û_q = Vq C' Va^{-1} Û_a
    4. Estimativa: ŷ_q = Xq β̂ + û_q

    Garante automaticamente: Σ ŷ_t = Y_k ∀ k.
    """
    n, m = len(X_q), len(y_a)
    X_a = C @ X_q
    V_a = C @ V_q @ C.T

    # Regularizar V_a para estabilidade
    V_a_reg = V_a + eps * np.trace(V_a) / m * np.eye(m)

    try:
        V_a_inv = inv(V_a_reg)
    except np.linalg.LinAlgError:
        V_a_inv = np.linalg.pinv(V_a_reg)

    # Verificar valores razoáveis
    if not np.all(np.isfinite(V_a_inv)):
        # Fallback: OLS simples
        V_a_inv = np.eye(m)

    # GLS beta
    M = X_a.T @ V_a_inv @ X_a
    M_reg = M + eps * np.trace(M) / X_q.shape[1] * np.eye(X_q.shape[1])

    try:
        beta = solve(M_reg, X_a.T @ V_a_inv @ y_a)
    except np.linalg.LinAlgError:
        beta = np.linalg.lstsq(X_a, y_a, rcond=None)[0]

    # Resíduos anuais
    u_a = y_a - X_a @ beta

    # Distribuição dos resíduos trimestrais
    u_q = V_q @ C.T @ V_a_inv @ u_a

    # Verificação de sanidade
    result = X_q @ beta + u_q
    if not np.all(np.isfinite(result)):
        warnings.warn("GLS produziu valores não-finitos. Usando Denton aditivo como fallback.")
        from src.disaggregation.denton import denton_additive
        return denton_additive(X_q[:, -1] if X_q.ndim > 1 else X_q, y_a,
                               freq=len(y_a))
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Estimação de ρ por MLE
# ──────────────────────────────────────────────────────────────────────────────

def _mle_rho(X_q: np.ndarray, y_a: np.ndarray,
             C: np.ndarray, freq: int = 4) -> float:
    """
    Estima ρ da estrutura AR(1) por MLE concentrado.
    Busca em [0, 0.999] para garantir estacionaridade.
    """
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
            nll = 0.5 * (logdet + resid @ V_a_inv @ resid)
            return float(nll)
        except Exception:
            return 1e10

    result = minimize_scalar(neg_log_lik, bounds=(0, 0.999), method="bounded")
    return float(result.x)


# ──────────────────────────────────────────────────────────────────────────────
# Método Chow-Lin
# ──────────────────────────────────────────────────────────────────────────────

def chow_lin(indicator: np.ndarray,
             annual_totals: np.ndarray,
             freq: int = 4,
             rho: Optional[float] = None,
             intercept: bool = True) -> np.ndarray:
    """
    Chow-Lin (1971) com erros AR(1).

    Modelo: q_t = β₀ + β₁ p_t + u_t,  u_t = ρ u_{t-1} + ε_t

    Parameters
    ----------
    indicator     : série indicadora trimestral (n,)
    annual_totals : totais anuais de controle (m,)
    freq          : frequência (4 = trimestral)
    rho           : coef. AR. Se None, estimado por MLE
    intercept     : incluir intercepto na regressão
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    if n != m * freq:
        raise ValueError(f"n={n} ≠ m*freq={m}*{freq}")

    C = _aggregation_matrix(n, freq)

    # Regressores
    if intercept:
        X_q = np.column_stack([np.ones(n), p])
    else:
        X_q = p.reshape(-1, 1)

    # Estimar ρ se não fornecido
    if rho is None:
        rho = _mle_rho(X_q, a, C, freq)

    V_q = _ar1_cov_matrix(n, rho)
    q = _gls_disaggregate(X_q, a, V_q, C)

    return q


# ──────────────────────────────────────────────────────────────────────────────
# Método Fernandez
# ──────────────────────────────────────────────────────────────────────────────

def fernandez(indicator: np.ndarray,
              annual_totals: np.ndarray,
              freq: int = 4,
              intercept: bool = True) -> np.ndarray:
    """
    Fernandez (1981) com erros I(1) (passeio aleatório).

    Equivale a Chow-Lin com ρ = 1 (limite não estacionário).
    Robusto quando não há indicador adequado.

    Modelo: Δq_t = β₁ Δp_t + Δu_t,  Δu_t ~ i.i.d. N(0, σ²)
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    if n != m * freq:
        raise ValueError(f"n={n} ≠ m*freq={m}*{freq}")

    C = _aggregation_matrix(n, freq)

    if intercept:
        X_q = np.column_stack([np.ones(n), p])
    else:
        X_q = p.reshape(-1, 1)

    V_q = _rw_cov_matrix(n)
    q = _gls_disaggregate(X_q, a, V_q, C)

    return q


# ──────────────────────────────────────────────────────────────────────────────
# Método Litterman
# ──────────────────────────────────────────────────────────────────────────────

def litterman(indicator: np.ndarray,
              annual_totals: np.ndarray,
              freq: int = 4,
              rho: Optional[float] = None,
              intercept: bool = True) -> np.ndarray:
    """
    Litterman (1983) com erros ARIMA(1,1,0).

    Combina tendência de passeio aleatório (Fernandez)
    com autocorrelação de curto prazo (AR1).

    Parameters
    ----------
    rho : coef. AR. Se None, usa 0.5 como default razoável.
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    if n != m * freq:
        raise ValueError(f"n={n} ≠ m*freq={m}*{freq}")

    C = _aggregation_matrix(n, freq)

    if intercept:
        X_q = np.column_stack([np.ones(n), p])
    else:
        X_q = p.reshape(-1, 1)

    if rho is None:
        rho = 0.5  # Default conservador

    V_q = _ar1_rw_cov_matrix(n, rho)
    q = _gls_disaggregate(X_q, a, V_q, C)

    return q


# ──────────────────────────────────────────────────────────────────────────────
# Método OLS simples (referência adicional)
# ──────────────────────────────────────────────────────────────────────────────

def ols_simple(indicator: np.ndarray,
               annual_totals: np.ndarray,
               freq: int = 4) -> np.ndarray:
    """
    OLS simples: regride anual em indicador, distribui residuos uniformemente.
    Sem estrutura de autocorrelação (baseline alternativo).
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    C = _aggregation_matrix(n, freq)
    X_q = np.column_stack([np.ones(n), p])
    X_a = C @ X_q
    V_q = np.eye(n)

    q = _gls_disaggregate(X_q, a, V_q, C)
    return q


# ──────────────────────────────────────────────────────────────────────────────
# Interface unificada
# ──────────────────────────────────────────────────────────────────────────────

REGRESSION_METHODS = {
    "chow_lin":  lambda p, a, f: chow_lin(p, a, f),
    "fernandez": lambda p, a, f: fernandez(p, a, f),
    "litterman": lambda p, a, f: litterman(p, a, f),
    "ols":       lambda p, a, f: ols_simple(p, a, f),
}


def disaggregate_regression(method: str,
                             indicator: np.ndarray,
                             annual_totals: np.ndarray,
                             freq: int = 4) -> np.ndarray:
    """
    Interface unificada para todos os métodos de regressão.
    """
    if method not in REGRESSION_METHODS:
        raise ValueError(f"Método '{method}' não encontrado. "
                         f"Disponíveis: {list(REGRESSION_METHODS.keys())}")
    return REGRESSION_METHODS[method](indicator, annual_totals, freq)
