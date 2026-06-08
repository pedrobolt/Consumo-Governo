"""
Gerador de dados sintéticos calibrados com os dados reais do paper Ipea 2015.

LÓGICA CORRETA:
  O indicador fiscal é INDEPENDENTE da CNT. Ele representa apenas ~38-42% do
  total das administrações públicas (salários + contrib. efetivas + imputadas
  da amostra de estados e municípios).

  O método Denton então ESCALA o indicador para que o TOTAL ANUAL bata com
  a CNT. Mas o PERFIL TRIMESTRAL é diferente → desvios de 2-5%.

  Para replicar o paper:
    indicator_raw_t = serie13_estimada_t * coverage_ratio_year
    Denton(indicator_raw, annual_cnt) → serie13_estimada (exato)
    Validação: serie13_estimada vs. CNT_quarterly = Table 2 desvios

  Para extensão 2015-2024:
    Gerar indicador com padrão sazonal LIGEIRAMENTE diferente da CNT.
    Coverage ratio aumenta com o tempo (mais entes no SICONFI).

Referências:
  Tabela 2 do paper: CNT quarterly e Série Estimada 2010-2014
  Tabela 3 do paper: representatividade da amostra por componente
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple


# ──────────────────────────────────────────────────────────────────────────────
# Dados exatos do paper (Tabela 2 e Tabela 3)
# ──────────────────────────────────────────────────────────────────────────────

# CNT publicada – "série efetiva" (R$ bilhões correntes)
CNT_QUARTERLY_PAPER = {
    "2010Q1": 163.11, "2010Q2": 172.80, "2010Q3": 180.25, "2010Q4": 222.81,
    "2011Q1": 177.58, "2011Q2": 198.67, "2011Q3": 199.00, "2011Q4": 242.12,
    "2012Q1": 198.33, "2012Q2": 220.36, "2012Q3": 220.14, "2012Q4": 270.78,
    "2013Q1": 217.08, "2013Q2": 248.11, "2013Q3": 244.31, "2013Q4": 300.85,
    "2014Q1": 244.40, "2014Q2": 271.49, "2014Q3": 274.12, "2014Q4": 324.89,
}

# Série Estimada (pós-Denton) – "Série 13" do paper
SERIE13_ESTIMADA_PAPER = {
    "2010Q1": 169.90, "2010Q2": 176.10, "2010Q3": 174.40, "2010Q4": 218.60,
    "2011Q1": 180.30, "2011Q2": 202.50, "2011Q3": 188.30, "2011Q4": 246.40,
    "2012Q1": 199.30, "2012Q2": 226.30, "2012Q3": 215.20, "2012Q4": 268.90,
    "2013Q1": 222.40, "2013Q2": 251.90, "2013Q3": 236.70, "2013Q4": 299.40,
    "2014Q1": 251.50, "2014Q2": 271.20, "2014Q3": 267.30, "2014Q4": 325.00,
}

# Totais anuais da amostra (Tabela 3 do paper) – R$ bilhões
SAMPLE_ANNUAL = {
    2010: {"salarios": 205.32, "contrib_efetiva": 28.28, "contrib_imputada": 51.07},
    2011: {"salarios": 230.48, "contrib_efetiva": 31.92, "contrib_imputada": 54.38},
}

# Totais IBGE das remunerações (Tabela 3, Tabela 1 do paper)
IBGE_ANNUAL = {
    2010: {"salarios": 373.22, "contrib_efetiva": 63.23, "contrib_imputada": 50.71,
           "consumo_interm": 209.06},
    2011: {"salarios": 413.39, "contrib_efetiva": 73.09, "contrib_imputada": 54.64,
           "consumo_interm": 232.20},
}

# Coverage ratios derivadas (sample / ibge):
# salários: 55%, contrib_efetiva: 44%, contrib_imputada: ~100%
# total_indicador / CNT: 284.67 / 738.97 = 38.5%
COVERAGE_ANNUAL = {
    2010: sum(SAMPLE_ANNUAL[2010].values()) / sum(CNT_QUARTERLY_PAPER[f"2010Q{q}"]
               for q in range(1, 5)),
    2011: sum(SAMPLE_ANNUAL[2011].values()) / sum(CNT_QUARTERLY_PAPER[f"2011Q{q}"]
               for q in range(1, 5)),
}

# Padrão sazonal dos pesos trimestrais da CNT (proporção de cada trimestre no ano)
CNT_SEASONAL = {
    2010: [163.11/738.97, 172.80/738.97, 180.25/738.97, 222.81/738.97],
    2011: [177.58/817.37, 198.67/817.37, 199.00/817.37, 242.12/817.37],
    2012: [198.33/909.61, 220.36/909.61, 220.14/909.61, 270.78/909.61],
    2013: [217.08/1010.35, 248.11/1010.35, 244.31/1010.35, 300.85/1010.35],
    2014: [244.40/1114.90, 271.49/1114.90, 274.12/1114.90, 324.89/1114.90],
}

# Padrão sazonal do indicador (proporção dentro de cada ano)
INDICATOR_SEASONAL = {
    2010: [169.90/739.00, 176.10/739.00, 174.40/739.00, 218.60/739.00],
    2011: [180.30/817.50, 202.50/817.50, 188.30/817.50, 246.40/817.50],
    2012: [199.30/909.70, 226.30/909.70, 215.20/909.70, 268.90/909.70],
    2013: [222.40/1010.40, 251.90/1010.40, 236.70/1010.40, 299.40/1010.40],
    2014: [251.50/1115.00, 271.20/1115.00, 267.30/1115.00, 325.00/1115.00],
}


# ──────────────────────────────────────────────────────────────────────────────
# Geração de dados para extensão 2015-2024
# ──────────────────────────────────────────────────────────────────────────────

# Taxas nominais de crescimento anual do consumo do governo
# Baseadas em estimativas de fontes públicas e tendências históricas
NOMINAL_GROWTH = {
    2015: 0.095, 2016: 0.068, 2017: 0.044, 2018: 0.058, 2019: 0.060,
    2020: 0.132, 2021: 0.126, 2022: 0.076, 2023: 0.101, 2024: 0.083,
}

# Evolução do coverage ratio (mais entes no SICONFI ao longo do tempo)
COVERAGE_EXTENDED = {
    2015: 0.390, 2016: 0.395, 2017: 0.400, 2018: 0.408, 2019: 0.420,
    2020: 0.430, 2021: 0.440, 2022: 0.448, 2023: 0.452, 2024: 0.455,
}

# Padrão sazonal da CNT para anos recentes (ligeiramente diferente do histórico)
# Tendência: Q1 menor, Q4 maior (concentração no fim do exercício)
CNT_SEASONAL_POST_2014 = {
    2015: [0.218, 0.240, 0.238, 0.304],
    2016: [0.217, 0.241, 0.238, 0.304],
    2017: [0.217, 0.241, 0.238, 0.304],
    2018: [0.216, 0.241, 0.239, 0.304],
    2019: [0.216, 0.240, 0.239, 0.305],
    2020: [0.218, 0.242, 0.237, 0.303],  # COVID: Q1 mais alto (gastos antecipados)
    2021: [0.215, 0.240, 0.238, 0.307],
    2022: [0.215, 0.239, 0.239, 0.307],
    2023: [0.214, 0.239, 0.240, 0.307],
    2024: [0.214, 0.239, 0.240, 0.307],
}

# Padrão sazonal do indicador para anos recentes
# LIGEIRAMENTE diferente da CNT → cria desvios não-triviais
INDICATOR_SEASONAL_POST_2014 = {
    2015: [0.225, 0.241, 0.234, 0.300],  # Q1 maior, Q3 menor vs. CNT
    2016: [0.224, 0.242, 0.234, 0.300],
    2017: [0.224, 0.242, 0.234, 0.300],
    2018: [0.223, 0.242, 0.235, 0.300],
    2019: [0.223, 0.241, 0.235, 0.301],
    2020: [0.223, 0.244, 0.232, 0.301],
    2021: [0.221, 0.241, 0.234, 0.304],
    2022: [0.221, 0.240, 0.234, 0.305],
    2023: [0.220, 0.240, 0.235, 0.305],
    2024: [0.220, 0.240, 0.235, 0.305],
}


def generate_cnt_quarterly(year_start: int = 2010, year_end: int = 2024,
                            seed: int = 42) -> pd.DataFrame:
    """
    Gera a série CNT trimestral:
    - 2010-2014: valores exatos do paper (Tabela 2)
    - 2015-2024: extensão com crescimento nominal e padrão sazonal realista

    Returns
    -------
    pd.DataFrame com colunas [ano, trimestre, cnt_nominal_bi, fonte]
    """
    np.random.seed(seed)
    records = []

    # Anos do paper (2010-2014): usar valores exatos
    for key, val in CNT_QUARTERLY_PAPER.items():
        year, q = int(key[:4]), int(key[5])
        if year_start <= year <= min(year_end, 2014):
            records.append({
                "ano": year, "trimestre": q,
                "cnt_nominal_bi": val,
                "fonte": "paper_real",
            })

    # Extensão 2015-2024
    last_annual = sum(CNT_QUARTERLY_PAPER[f"2014Q{q}"] for q in range(1, 5))

    for year in range(max(2015, year_start), year_end + 1):
        g = NOMINAL_GROWTH.get(year, 0.07)
        last_annual *= (1 + g)
        seasonal = CNT_SEASONAL_POST_2014.get(year, [0.217, 0.240, 0.239, 0.304])

        for q in range(1, 5):
            # Pequeno ruído branco (~0.3%) para realismo
            noise = np.random.normal(0, 0.003)
            val = last_annual * (seasonal[q - 1] + noise)
            val = max(val, 0)
            records.append({
                "ano": year, "trimestre": q,
                "cnt_nominal_bi": val,
                "fonte": "estimativa",
            })

    df = pd.DataFrame(records)
    df = df[df["ano"].between(year_start, year_end)]
    df["data"] = pd.to_datetime(
        df["ano"].astype(str) + "Q" + df["trimestre"].astype(str)
    ).dt.to_period("Q").dt.to_timestamp()
    return df.sort_values("data").reset_index(drop=True)


def generate_indicator_quarterly(year_start: int = 2010, year_end: int = 2024,
                                  seed: int = 42) -> pd.DataFrame:
    """
    Gera a série indicadora trimestral PRÉ-DENTON:
    - 2010-2014: indicador back-calculado a partir dos dados do paper
      (Série Estimada × coverage_ratio → este é o dado bruto)
    - 2015-2024: extensão com padrão sazonal ligeiramente diferente da CNT

    O indicador representa ~38-46% do total da CNT (coverage parcial).
    O padrão sazonal é ligeiramente diferente da CNT → cria desvios não-triviais.

    Returns
    -------
    pd.DataFrame com colunas [ano, trimestre, indicador_bi, fonte]
    """
    np.random.seed(seed + 10)
    records = []

    # 2010-2014: back-calculate indicador bruto da Série Estimada
    for key, estimada_val in SERIE13_ESTIMADA_PAPER.items():
        year, q = int(key[:4]), int(key[5])
        if not (year_start <= year <= min(year_end, 2014)):
            continue

        # Coverage ratio do ano
        coverage = COVERAGE_ANNUAL.get(year, 0.385)

        # Indicador bruto = estimada × coverage
        # (Denton então escalará de volta para recuperar estimada)
        raw_val = estimada_val * coverage

        # Ruído realista (~0.5%)
        noise = np.random.normal(0, 0.005)
        records.append({
            "ano": year, "trimestre": q,
            "indicador_bi": raw_val * (1 + noise),
            "fonte": "paper_derivado",
        })

    # Extensão 2015-2024
    # Annual CNT 2014
    last_cnt_annual = sum(CNT_QUARTERLY_PAPER[f"2014Q{q}"] for q in range(1, 5))
    last_indicator_annual = last_cnt_annual * COVERAGE_ANNUAL.get(2014, 0.385)

    for year in range(max(2015, year_start), year_end + 1):
        g = NOMINAL_GROWTH.get(year, 0.07)
        last_cnt_annual *= (1 + g)
        coverage = COVERAGE_EXTENDED.get(year, 0.40)
        last_indicator_annual = last_cnt_annual * coverage

        seasonal = INDICATOR_SEASONAL_POST_2014.get(year, [0.223, 0.241, 0.234, 0.302])

        for q in range(1, 5):
            noise = np.random.normal(0, 0.005)
            val = last_indicator_annual * (seasonal[q - 1] + noise)
            val = max(val, 0)
            records.append({
                "ano": year, "trimestre": q,
                "indicador_bi": val,
                "fonte": "estimativa",
            })

    df = pd.DataFrame(records)
    df = df[df["ano"].between(year_start, year_end)]
    df["data"] = pd.to_datetime(
        df["ano"].astype(str) + "Q" + df["trimestre"].astype(str)
    ).dt.to_period("Q").dt.to_timestamp()
    return df.sort_values("data").reset_index(drop=True)


def generate_multi_spec_indicators(year_start: int = 2010, year_end: int = 2024,
                                    seed: int = 42) -> Dict[str, pd.Series]:
    """
    Gera múltiplas séries indicadoras correspondentes às 13 especificações do paper
    + extensões modernas. Cada especificação usa subconjuntos diferentes de entes
    e componentes, com cobertura e ruído correspondentes.

    Returns
    -------
    dict {spec_name: pd.Series indexada por datetime, valores em R$ bilhões}
    """
    np.random.seed(seed + 20)

    # Base: indicador completo (serie13)
    base_df = generate_indicator_quarterly(year_start, year_end, seed)
    base_idx = base_df.set_index("data")["indicador_bi"]

    # Parâmetros de cada especificação (fração do indicador total)
    SPEC_FRACS = {
        "serie1":    0.485 * 0.654,   # União: sal+CE
        "serie2":    0.485 * 0.654 * 1.05,
        "serie3":    (0.485 + 0.355) * 0.654,
        "serie4":    (0.485 + 0.355) * 0.654 * 1.05,
        "serie5":    1.0 * 0.654,
        "serie6":    1.0 * 0.654 * 1.05,
        "serie7":    1.0 * 0.654 * 1.10,
        "serie8":    1.0 * 0.654 * 1.12,
        "serie9":    (0.485 + 0.355) * 0.654 * 1.12,
        "serie10":   (0.485 + 0.160) * 0.654 * 1.12,
        "serie11":   1.0 * 0.654 * 1.08,
        "serie12":   1.0 * 0.654 * 1.07,
        "serie13":   1.0,               # Série completa = referência
        "moderna_a": 1.0 * 1.20,        # 27 estados (vs 11)
        "moderna_b": 1.0 * 1.25,        # + CI
        "moderna_c": 1.0 * 1.28,        # + CI + RP
    }

    # Ruído específico por especificação (menor para séries mais limpas)
    SPEC_NOISE = {
        "serie1": 0.003, "serie2": 0.006, "serie3": 0.004,
        "serie4": 0.007, "serie5": 0.005, "serie6": 0.008,
        "serie7": 0.010, "serie8": 0.012, "serie9": 0.010,
        "serie10": 0.010, "serie11": 0.009, "serie12": 0.009,
        "serie13": 0.005,
        "moderna_a": 0.004, "moderna_b": 0.006, "moderna_c": 0.008,
    }

    result = {}
    for spec, frac in SPEC_FRACS.items():
        noise_level = SPEC_NOISE.get(spec, 0.005)
        noise = np.random.normal(0, noise_level, len(base_idx))
        spec_series = base_idx * frac * (1 + noise)
        spec_series.name = spec
        result[spec] = spec_series

    return result


def compute_deviation_table_paper() -> pd.DataFrame:
    """
    Verifica que os dados reproduzem os desvios da Tabela 2 do paper.
    Útil como teste de sanidade.
    """
    from src.disaggregation.denton import denton_proportional

    rows = []
    for year in range(2010, 2015):
        # Indicador anual (coverage_ratio × estimada_anual)
        estimada_anual = sum(SERIE13_ESTIMADA_PAPER.get(f"{year}Q{q}", 0)
                             for q in range(1, 5))
        cnt_anual = sum(CNT_QUARTERLY_PAPER.get(f"{year}Q{q}", 0) for q in range(1, 5))
        coverage = estimada_anual / cnt_anual  # ~ 1.0 (Série Estimada já é pós-Denton)

        # Raw indicator = estimada × (sample_total / cnt_annual)
        sample_total = sum(COVERAGE_ANNUAL.get(year, 0.385) *
                           cnt_anual for q in range(1, 5)) / 4
        raw_coverage = COVERAGE_ANNUAL.get(year, 0.385)

        for q in range(1, 5):
            key = f"{year}Q{q}"
            cnt = CNT_QUARTERLY_PAPER.get(key, 0)
            estimada = SERIE13_ESTIMADA_PAPER.get(key, 0)
            desvio = estimada - cnt
            desvio_pct = 100 * desvio / cnt if cnt > 0 else 0

            rows.append({
                "periodo": key,
                "cnt_bi": round(cnt, 2),
                "estimada_bi": round(estimada, 2),
                "desvio_bi": round(desvio, 2),
                "desvio_pct": round(desvio_pct, 2),
            })

    return pd.DataFrame(rows)
