"""
Métricas de validação para séries trimestrais estimadas.

Métricas implementadas (todas em R$ bilhões, salvo indicação contrária):

  RMSE  – Raiz do Erro Quadrático Médio
  MAE   – Erro Absoluto Médio
  MAPE  – Erro Percentual Absoluto Médio (%)
  MPE   – Erro Percentual Médio (%) – para detectar viés
  MaxAE – Erro Absoluto Máximo
  MaxPE – Erro Percentual Máximo (valor absoluto, %)
  Corr  – Correlação de Pearson
  R²    – Coeficiente de determinação
  TheilU1 – Theil U1 (0=perfeito, 1=naive)
  TheilU2 – Theil U2 (< 1 = melhor que random walk)
  BiasPct – Viés médio percentual

Nota: todas as métricas comparam a série ESTIMADA contra a série CNT publicada.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Union


# ──────────────────────────────────────────────────────────────────────────────
# Funções individuais
# ──────────────────────────────────────────────────────────────────────────────

def rmse(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - forecast) ** 2)))


def mae(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - forecast)))


def mape(actual: np.ndarray, forecast: np.ndarray,
         eps: float = 1e-9) -> float:
    """MAPE em %."""
    return float(100 * np.mean(np.abs((actual - forecast) / (np.abs(actual) + eps))))


def mpe(actual: np.ndarray, forecast: np.ndarray,
        eps: float = 1e-9) -> float:
    """MPE em % (indica viés de sinal)."""
    return float(100 * np.mean((forecast - actual) / (np.abs(actual) + eps)))


def max_abs_error(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.max(np.abs(actual - forecast)))


def max_pct_error(actual: np.ndarray, forecast: np.ndarray,
                  eps: float = 1e-9) -> float:
    """Maior erro percentual absoluto em %."""
    return float(100 * np.max(np.abs((actual - forecast) / (np.abs(actual) + eps))))


def correlation(actual: np.ndarray, forecast: np.ndarray) -> float:
    return float(np.corrcoef(actual, forecast)[0, 1])


def r_squared(actual: np.ndarray, forecast: np.ndarray) -> float:
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    return float(1 - ss_res / ss_tot) if ss_tot > 0 else 0.0


def theil_u1(actual: np.ndarray, forecast: np.ndarray,
             eps: float = 1e-9) -> float:
    """
    Theil U1: √[Σ(f-a)²/n] / (√[Σf²/n] + √[Σa²/n])
    0 = previsão perfeita, 1 = muito ruim.
    """
    rmse_fa = rmse(actual, forecast)
    rmse_f = float(np.sqrt(np.mean(forecast ** 2)))
    rmse_a = float(np.sqrt(np.mean(actual ** 2)))
    return rmse_fa / (rmse_f + rmse_a + eps)


def theil_u2(actual: np.ndarray, forecast: np.ndarray,
             eps: float = 1e-9) -> float:
    """
    Theil U2: √[Σ(Δf-Δa)²] / √[Σ(Δa)²]
    < 1 = melhor que random walk naïve.
    Requer série com ≥ 2 pontos.
    """
    if len(actual) < 2:
        return np.nan
    delta_f = np.diff(forecast)
    delta_a = np.diff(actual)
    num = float(np.sqrt(np.mean((delta_f - delta_a) ** 2)))
    den = float(np.sqrt(np.mean(delta_a ** 2)))
    return num / (den + eps)


def bias_pct(actual: np.ndarray, forecast: np.ndarray,
             eps: float = 1e-9) -> float:
    """Viés médio como % da média da série real."""
    return float(100 * np.mean(forecast - actual) / (np.mean(np.abs(actual)) + eps))


# ──────────────────────────────────────────────────────────────────────────────
# Cálculo completo de todas as métricas
# ──────────────────────────────────────────────────────────────────────────────

def compute_all_metrics(actual: Union[np.ndarray, pd.Series],
                        forecast: Union[np.ndarray, pd.Series],
                        name: str = "modelo") -> Dict[str, float]:
    """
    Calcula todas as métricas de uma vez.

    Parameters
    ----------
    actual   : série real (CNT publicada)
    forecast : série estimada
    name     : identificador do modelo

    Returns
    -------
    dict com todas as métricas + nome do modelo
    """
    a = np.asarray(actual, dtype=float)
    f = np.asarray(forecast, dtype=float)

    # Remover NaNs
    mask = np.isfinite(a) & np.isfinite(f)
    a, f = a[mask], f[mask]

    if len(a) == 0:
        return {"model": name, "n": 0}

    return {
        "model":    name,
        "n":        len(a),
        "RMSE":     round(rmse(a, f), 4),
        "MAE":      round(mae(a, f), 4),
        "MAPE":     round(mape(a, f), 4),
        "MPE":      round(mpe(a, f), 4),
        "MaxAE":    round(max_abs_error(a, f), 4),
        "MaxPE":    round(max_pct_error(a, f), 4),
        "Corr":     round(correlation(a, f), 6),
        "R2":       round(r_squared(a, f), 6),
        "TheilU1":  round(theil_u1(a, f), 6),
        "TheilU2":  round(theil_u2(a, f), 6),
        "BiasPct":  round(bias_pct(a, f), 4),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Comparar múltiplos modelos
# ──────────────────────────────────────────────────────────────────────────────

def compare_models(actual: Union[np.ndarray, pd.Series],
                   forecasts: Dict[str, np.ndarray]) -> pd.DataFrame:
    """
    Compara múltiplos modelos contra a série real.

    Parameters
    ----------
    actual    : série real (n,)
    forecasts : dict {nome_modelo: array (n,)}

    Returns
    -------
    pd.DataFrame ranqueado por RMSE crescente
    """
    rows = []
    for name, fc in forecasts.items():
        rows.append(compute_all_metrics(actual, fc, name=name))

    df = pd.DataFrame(rows)
    if "RMSE" in df.columns:
        df = df.sort_values("RMSE").reset_index(drop=True)
        df.index = df.index + 1  # Ranking começa em 1
        df.index.name = "rank"

    return df


# ──────────────────────────────────────────────────────────────────────────────
# Métricas por sub-período
# ──────────────────────────────────────────────────────────────────────────────

def metrics_by_period(actual: pd.Series,
                      forecast: pd.Series,
                      periods: pd.PeriodIndex = None) -> pd.DataFrame:
    """
    Calcula métricas por ano ou por período definido.

    Parameters
    ----------
    actual, forecast : pd.Series com DatetimeIndex
    periods : se None, agrupa por ano
    """
    df = pd.DataFrame({
        "actual": actual,
        "forecast": forecast,
    }).dropna()

    df["ano"] = df.index.year if hasattr(df.index, 'year') else df.index
    df["erro"] = df["forecast"] - df["actual"]
    df["erro_pct"] = 100 * df["erro"] / df["actual"]

    annual = (df.groupby("ano")
                .apply(lambda g: pd.Series({
                    "RMSE":  rmse(g["actual"].values, g["forecast"].values),
                    "MAPE":  mape(g["actual"].values, g["forecast"].values),
                    "MPE":   mpe(g["actual"].values, g["forecast"].values),
                    "MaxPE": max_pct_error(g["actual"].values, g["forecast"].values),
                }), include_groups=False)
                .reset_index())

    return annual


# ──────────────────────────────────────────────────────────────────────────────
# Tabela de desvios (réplica da Tabela 2 do paper)
# ──────────────────────────────────────────────────────────────────────────────

def deviation_table(actual: pd.Series,
                    forecast: pd.Series,
                    model_name: str = "Estimado") -> pd.DataFrame:
    """
    Tabela trimestral de desvios (réplica da Tabela 2 do paper Ipea 2015).

    Colunas: Trimestre | CNT Real | Série Estimada | Desvio | Desvio %
    """
    df = pd.DataFrame({
        "Contas Nacionais (CNT)": actual,
        model_name: forecast,
    }).dropna()

    df["Desvio (bi)"] = df[model_name] - df["Contas Nacionais (CNT)"]
    df["Desvio (%)"] = 100 * df["Desvio (bi)"] / df["Contas Nacionais (CNT)"]

    for col in ["Contas Nacionais (CNT)", model_name, "Desvio (bi)"]:
        df[col] = df[col].round(2)
    df["Desvio (%)"] = df["Desvio (%)"].round(2)

    # Formatar índice como "AAAA/T"
    if hasattr(df.index, 'year'):
        df.index = [f"{i.year}/{i.quarter}" for i in df.index]

    return df
