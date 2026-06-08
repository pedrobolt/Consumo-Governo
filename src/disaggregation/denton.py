"""
Implementação dos métodos de Denton para desagregação temporal.

Referências:
  Denton (1971) – "Adjustment of monthly or quarterly series to annual totals:
                   an approach based on quadratic minimization"
  Bloem, Dippelsman & Mæhle (2001) – IMF Quarterly National Accounts Manual
  Cholette (1984) – "Adjusting sub-annual series to yearly benchmarks"

Métodos implementados:
  1. denton_proportional – Minimiza Σ[ (q_t/p_t - q_{t-1}/p_{t-1})^2 ]
  2. denton_additive     – Minimiza Σ[ Δ(q_t - p_t)^2 ]
  3. denton_second_diff_proportional – segunda diferença
  4. pro_rata            – Distribuição proporcional simples (baseline)

Notas de implementação:
  - A inicialização com z0=annual_ratio (proporcional por ano) garante
    estabilidade numérica mesmo para séries longas com forte tendência.
  - A correção de Denton adiciona suavidade cross-year às transições.
  - D'D tem posto n-1 (vetor constante no espaço nulo). Usa pseudo-inversa.
  - A restrição de adição anual é satisfeita exatamente: Cq = a.
"""

import numpy as np
from numpy.linalg import pinv, solve
from typing import Union, Tuple
import warnings


# ──────────────────────────────────────────────────────────────────────────────
# Utilitários internos
# ──────────────────────────────────────────────────────────────────────────────

def _aggregation_matrix(n: int, freq: int = 4) -> np.ndarray:
    """Matriz C de agregação temporal (m x n)."""
    m = n // freq
    C = np.zeros((m, n))
    for k in range(m):
        C[k, k * freq: (k + 1) * freq] = 1.0
    return C


def _diff_matrix(n: int, order: int = 1) -> np.ndarray:
    """Matriz de diferenças de ordem h ((n-h) x n)."""
    D = np.eye(n)
    for _ in range(order):
        D = np.diff(D, axis=0)
    return D


def _DtD_pinv(n: int, order: int = 1, eps: float = 1e-10) -> np.ndarray:
    """
    Pseudo-inversa regularizada de D'D para ordem de diferença dada.
    A regularização eps garante estabilidade numérica para n grande.
    """
    D = _diff_matrix(n, order)
    DtD = D.T @ D
    DtD_reg = DtD + eps * np.eye(n)
    return pinv(DtD_reg)


def _build_stable_z0(p: np.ndarray, a: np.ndarray, freq: int) -> np.ndarray:
    """
    Cria inicialização z0 numericamente estável para Denton proporcional.

    Estratégia:
    - Calcula taxa anual R_k = A_k / Σp_t para cada ano k
    - Interpola linearmente entre os R_k para criar z0 suave
    - z0 é próximo da solução ótima → correção pequena e estável

    Com z0 = linear_interpolation(R_k), a restrição CW@z0 é QUASE satisfeita,
    garantindo que o vetor rhs é pequeno e numericamente controlável.
    """
    n = len(p)
    m = len(a)

    # Taxa anual: quanto o CNT supera o indicador em cada ano
    annual_ratios = np.zeros(m)
    for k in range(m):
        s = slice(k * freq, (k + 1) * freq)
        annual_ratios[k] = a[k] / (p[s].sum() + 1e-12)

    # Posições no tempo dos centros de cada ano
    midpoints = np.arange(freq / 2, n, freq)
    time_idx = np.arange(n)

    # Interpolação linear entre as taxas anuais
    z0 = np.interp(time_idx, midpoints, annual_ratios)

    return z0


def _verify_constraint(q: np.ndarray, C: np.ndarray, a: np.ndarray,
                       tol: float = 0.01) -> None:
    """Verifica que a restrição de adição anual está satisfeita."""
    residual = np.abs(C @ q - a)
    max_rel = (residual / (np.abs(a) + 1e-12)).max()
    if max_rel > tol:
        warnings.warn(
            f"Restrição de adição não satisfeita (erro rel. máx={max_rel:.4%}).")


# ──────────────────────────────────────────────────────────────────────────────
# Método 1: Denton Proporcional (método do paper)
# ──────────────────────────────────────────────────────────────────────────────

def denton_proportional(indicator: np.ndarray,
                        annual_totals: np.ndarray,
                        freq: int = 4,
                        diff_order: int = 1) -> np.ndarray:
    """
    Desagregação temporal pelo método Denton Proporcional.

    Minimiza:
        Σ_{t=2}^{n} [ (q_t/p_t - q_{t-1}/p_{t-1})^2 ]

    Sujeito a:
        Σ_{t ∈ k} q_t = A_k  para cada ano k

    Equivalência: minimiza suavidade dos RAZÕES q_t/p_t = z_t
    com restrição ponderada Σ p_t z_t = A_k.

    Implementação numericamente estável:
    - Inicializa z0 com interpolação linear das taxas anuais
    - Aplica correção de Denton para satisfazer restrições exatamente

    Parameters
    ----------
    indicator     : array (n,) — série indicadora trimestral (> 0)
    annual_totals : array (m,) — totais anuais de referência
    freq          : int — períodos por ano (4 = trimestral)
    diff_order    : int — ordem das diferenças (1 = Denton clássico)

    Returns
    -------
    q : array (n,) — estimativa trimestral
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    if n != m * freq:
        raise ValueError(f"n={n} ≠ m×freq={m}×{freq}={m*freq}")
    if np.any(p <= 0):
        raise ValueError("Indicador deve ser positivo para o método proporcional.")

    C = _aggregation_matrix(n, freq)
    CW = C * p[np.newaxis, :]          # Restrição ponderada: Σ p_t z_t = A_k

    # Inicialização estável (interpolação das taxas anuais)
    z0 = _build_stable_z0(p, a, freq)

    S = _DtD_pinv(n, diff_order)       # Pseudo-inversa regularizada de D'D
    A_mat = CW @ S @ CW.T             # m × m (matriz de resolução)
    rhs = a - CW @ z0                 # Pequeno graças à boa inicialização

    # Resolver sistema linear
    try:
        z_star = z0 + S @ CW.T @ solve(A_mat, rhs)
    except np.linalg.LinAlgError:
        # Fallback: pseudo-inversa
        z_star = z0 + S @ CW.T @ pinv(A_mat) @ rhs

    q = p * z_star
    _verify_constraint(q, C, a)
    return q


# ──────────────────────────────────────────────────────────────────────────────
# Método 2: Denton Aditivo (Denton-Cholette)
# ──────────────────────────────────────────────────────────────────────────────

def denton_additive(indicator: np.ndarray,
                    annual_totals: np.ndarray,
                    freq: int = 4,
                    diff_order: int = 1) -> np.ndarray:
    """
    Desagregação temporal pelo método Denton Aditivo.

    Minimiza:
        Σ_{t=2}^{n} [ Δ(q_t - p_t)^2 ]

    Sujeito a:
        Σ_{t ∈ k} q_t = A_k  para cada ano k

    Parameters
    ----------
    indicator     : array (n,) — série indicadora trimestral
    annual_totals : array (m,) — totais anuais de referência
    freq          : int
    diff_order    : int

    Returns
    -------
    q : array (n,) — estimativa trimestral
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    if n != m * freq:
        raise ValueError(f"n={n} ≠ m×freq={m}×{freq}={m*freq}")

    C = _aggregation_matrix(n, freq)
    S = _DtD_pinv(n, diff_order)

    A_mat = C @ S @ C.T
    try:
        correction = S @ C.T @ solve(A_mat, a - C @ p)
    except np.linalg.LinAlgError:
        correction = S @ C.T @ pinv(A_mat) @ (a - C @ p)

    q = p + correction
    _verify_constraint(q, C, a)
    return q


# ──────────────────────────────────────────────────────────────────────────────
# Método 3: Distribuição Pro Rata (baseline)
# ──────────────────────────────────────────────────────────────────────────────

def pro_rata(indicator: np.ndarray,
             annual_totals: np.ndarray,
             freq: int = 4) -> np.ndarray:
    """
    Distribuição proporcional simples (pro rata).

    q_t = p_t * A_k / Σ_{t ∈ k} p_t

    Equivalente ao Denton proporcional sem suavização cross-year.
    Usado como baseline de comparação.
    """
    p = np.asarray(indicator, dtype=float)
    a = np.asarray(annual_totals, dtype=float)
    n, m = len(p), len(a)

    q = np.zeros(n)
    for k in range(m):
        s = slice(k * freq, (k + 1) * freq)
        pk = p[s]
        q[s] = pk / pk.sum() * a[k]

    return q


# ──────────────────────────────────────────────────────────────────────────────
# Método 4: Denton Segunda Diferença
# ──────────────────────────────────────────────────────────────────────────────

def denton_second_diff_proportional(indicator: np.ndarray,
                                    annual_totals: np.ndarray,
                                    freq: int = 4) -> np.ndarray:
    """
    Denton proporcional com segunda diferença (suavidade de ordem 2).
    Mais suave, pode sacrificar algum grau de acompanhamento do indicador.
    """
    return denton_proportional(indicator, annual_totals, freq, diff_order=2)


# ──────────────────────────────────────────────────────────────────────────────
# Interface unificada
# ──────────────────────────────────────────────────────────────────────────────

METHODS = {
    "denton_prop":    lambda p, a, f: denton_proportional(p, a, f, 1),
    "denton_prop_d2": lambda p, a, f: denton_proportional(p, a, f, 2),
    "denton_add":     lambda p, a, f: denton_additive(p, a, f, 1),
    "denton_add_d2":  lambda p, a, f: denton_additive(p, a, f, 2),
    "pro_rata":       lambda p, a, f: pro_rata(p, a, f),
}


def disaggregate(method: str,
                 indicator: np.ndarray,
                 annual_totals: np.ndarray,
                 freq: int = 4) -> np.ndarray:
    """Interface única para todos os métodos Denton."""
    if method not in METHODS:
        raise ValueError(f"Método '{method}' desconhecido. "
                         f"Disponíveis: {list(METHODS.keys())}")
    return METHODS[method](indicator, annual_totals, freq)
