"""
Coleta de dados do IBGE – Contas Nacionais Trimestrais e Anuais.

Tabelas SIDRA relevantes:
  1621 – Série encadeada do índice de volume trimestral (base 1995=100)
  2072 – PIB e componentes, valores correntes (R$ milhões)
  5932 – PIB e componentes, valores correntes (versão mais recente)

Endpoint principal:
  https://servicodados.ibge.gov.br/api/v3/agregados/{tabela}/periodos/{periodos}/variaveis/{variavel}

Método de fallback: dados sintéticos calibrados com os valores do paper (Tabela 2)
e crescimento nominal estimado para 2015-2024.
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

from config import (IBGE_API_BASE, API_TIMEOUT, CACHE_DAYS,
                    DATA_RAW, YEAR_START, YEAR_END, FREQ)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Dados reais do paper (Tabela 2) – usados para calibração do fallback
# ──────────────────────────────────────────────────────────────────────────────
# CNT publicada (série efetiva), R$ bilhões correntes
CNT_PAPER = {
    "2010Q1": 163.11, "2010Q2": 172.80, "2010Q3": 180.25, "2010Q4": 222.81,
    "2011Q1": 177.58, "2011Q2": 198.67, "2011Q3": 199.00, "2011Q4": 242.12,
    "2012Q1": 198.33, "2012Q2": 220.36, "2012Q3": 220.14, "2012Q4": 270.78,
    "2013Q1": 217.08, "2013Q2": 248.11, "2013Q3": 244.31, "2013Q4": 300.85,
    "2014Q1": 244.40, "2014Q2": 271.49, "2014Q3": 274.12, "2014Q4": 324.89,
}

# Taxas nominais aproximadas de crescimento anual do consumo do governo
# Fonte: estimativas baseadas em dados históricos do IBGE
NOMINAL_GROWTH_RATES = {
    2015: 0.095,
    2016: 0.068,
    2017: 0.044,
    2018: 0.058,
    2019: 0.060,
    2020: 0.132,   # COVID: expansão fiscal
    2021: 0.126,
    2022: 0.076,
    2023: 0.101,
    2024: 0.083,
}

# Padrão sazonal trimestral típico (pesos dentro do ano, soma=1)
# Q1 historicamente baixo, Q4 alto (fim de exercício)
SEASONAL_WEIGHTS_BY_QUARTER = {1: 0.2170, 2: 0.2410, 3: 0.2380, 4: 0.3040}

_CACHE_FILE = DATA_RAW / "cnt_quarterly_cache.json"


def _load_cache():
    if _CACHE_FILE.exists():
        age = datetime.now() - datetime.fromtimestamp(_CACHE_FILE.stat().st_mtime)
        if age < timedelta(days=CACHE_DAYS):
            with open(_CACHE_FILE) as f:
                return json.load(f)
    return None


def _save_cache(data: dict):
    with open(_CACHE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _fetch_ibge_cnt(year_start: int, year_end: int) -> dict:
    """
    Tenta buscar série de Consumo Final das Administrações Públicas (nominal)
    da API SIDRA do IBGE.

    Tabela 2072, variável 933 (Consumo final das adm. públicas, R$ milhões).
    """
    periods = []
    for y in range(year_start, year_end + 1):
        for q in range(1, 5):
            periods.append(f"{y}0{q}")

    period_str = "|".join(periods)

    # Tabela 2072 – Demanda agregada corrente
    url = (f"{IBGE_API_BASE}/agregados/2072/periodos/{period_str}"
           f"/variaveis/933?localidades=N1[all]")

    try:
        resp = requests.get(url, timeout=API_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()
        result = {}
        for item in raw[0]["resultados"][0]["series"][0]["serie"].items():
            period, value = item
            if value not in ("-", "..."):
                year = int(period[:4])
                quarter = int(period[4])
                key = f"{year}Q{quarter}"
                # IBGE retorna R$ milhões → converter para R$ bilhões
                result[key] = float(value) / 1000
        logger.info("IBGE API: %d trimestres coletados.", len(result))
        return result
    except Exception as exc:
        logger.warning("IBGE API indisponível (%s). Usando fallback sintético.", exc)
        return {}


def _build_synthetic_cnt(year_start: int, year_end: int) -> dict:
    """
    Constrói série sintética calibrada com:
    - Valores reais do paper (2010-2014)
    - Crescimento nominal estimado para 2015 em diante
    - Padrão sazonal histórico
    """
    result = {}

    # Preencher com valores exatos do paper
    result.update(CNT_PAPER)

    # Calcular totais anuais do paper
    annual = {}
    for key, val in CNT_PAPER.items():
        y = int(key[:4])
        annual[y] = annual.get(y, 0) + val

    # Estender para os anos fora do paper
    last_annual = annual[2014]
    for y in range(max(2015, year_start), year_end + 1):
        growth = NOMINAL_GROWTH_RATES.get(y, 0.07)
        last_annual = last_annual * (1 + growth)
        annual[y] = last_annual
        for q, w in SEASONAL_WEIGHTS_BY_QUARTER.items():
            key = f"{y}Q{q}"
            # Adicionar ruído branco pequeno para realismo
            noise = np.random.normal(0, 0.002)
            result[key] = last_annual * (w + noise)

    # Incluir anos antes de 2010 se necessário
    if year_start < 2010:
        first_annual = annual[2010]
        for y in range(year_start, 2010):
            # Crescimento reverso aproximado
            first_annual = first_annual / 1.12
            annual[y] = first_annual
            for q, w in SEASONAL_WEIGHTS_BY_QUARTER.items():
                result[f"{y}Q{q}"] = first_annual * w

    # Filtrar apenas o período solicitado
    filtered = {k: v for k, v in result.items()
                if year_start <= int(k[:4]) <= year_end}

    return dict(sorted(filtered.items()))


def get_cnt_quarterly(year_start: int = YEAR_START,
                      year_end: int = YEAR_END,
                      use_cache: bool = True) -> pd.DataFrame:
    """
    Retorna série trimestral do Consumo Final das Administrações Públicas
    (valores nominais, R$ bilhões correntes).

    Parameters
    ----------
    year_start, year_end : int
    use_cache : bool

    Returns
    -------
    pd.DataFrame com colunas ['periodo', 'ano', 'trimestre', 'cnt_nominal_bi']
    """
    np.random.seed(42)  # Reprodutibilidade do fallback

    cached = _load_cache() if use_cache else None
    if cached:
        logger.info("Cache IBGE CNT carregado.")
        data_dict = cached
    else:
        data_dict = _fetch_ibge_cnt(year_start, year_end)
        if not data_dict:
            logger.info("Usando dados sintéticos calibrados com o paper.")
            data_dict = _build_synthetic_cnt(year_start, year_end)
        if use_cache:
            _save_cache(data_dict)

    records = []
    for key in sorted(data_dict.keys()):
        y, q = int(key[:4]), int(key[5])
        if year_start <= y <= year_end:
            records.append({
                "periodo": key,
                "ano": y,
                "trimestre": q,
                "cnt_nominal_bi": data_dict[key],
            })

    df = pd.DataFrame(records)
    df["data"] = pd.to_datetime(
        df["ano"].astype(str) + "Q" + df["trimestre"].astype(str)
    ).dt.to_period("Q").dt.to_timestamp()

    # Marcar se veio de dado real do paper ou de extensão
    df["fonte"] = df["periodo"].apply(
        lambda p: "paper_real" if p in CNT_PAPER else "estimativa")

    return df.set_index("data").sort_index()


def get_cnt_annual(year_start: int = YEAR_START,
                   year_end: int = YEAR_END) -> pd.DataFrame:
    """Agrega a série trimestral em totais anuais."""
    df = get_cnt_quarterly(year_start, year_end)
    annual = (df.groupby("ano")["cnt_nominal_bi"]
                .sum()
                .reset_index()
                .rename(columns={"cnt_nominal_bi": "cnt_anual_bi"}))
    return annual
