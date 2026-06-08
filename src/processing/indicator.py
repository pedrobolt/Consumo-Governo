"""
Construção da série indicadora.

Replica a lógica do paper (Ipea 2015) e propõe extensões:
  - Série 13 (melhor do paper): União+Est+Mun, Salários+CE+CI_Imp, Liquidado sem RP
  - Série moderna A: mesma lógica, cobertura ampliada (27 estados)
  - Série moderna B: inclui consumo intermediário com dados mais confiáveis
  - Série moderna C: inclui restos a pagar com ponderação por qualidade

As séries são usadas como indicadores no método de Denton.

Translação contábil (paper Tabela p.8):
  GND 1 (Pessoal e Encargos Sociais)
    elemento 319011 → Salários
    elemento 319013 → Contribuições Efetivas
    elemento 319113 → Contrib. Efetivas Intraorçamentárias
    RREO Anexo 4    → Contribuições Imputadas (RPPS)
  GND 3 (Outras Despesas Correntes)
    subconjunto → Consumo Intermediário (qualidade inferior)
"""

import logging
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from config import (YEAR_START, YEAR_END, FREQ,
                    ESTADOS_PAPER, TODOS_ESTADOS,
                    MUNICIPIOS_PAPER)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Parâmetros de representatividade (Tabela 3 do paper)
# ──────────────────────────────────────────────────────────────────────────────
REPR_PAPER = {
    "salarios":       0.5538,   # média 2010-2011
    "contrib_efetiva": 0.4420,
    "contrib_imputada": 0.9962, # quase 100%
}

# Com cobertura ampliada (27 estados + mais municípios)
REPR_EXTENDED = {
    "salarios":       0.8200,
    "contrib_efetiva": 0.7800,
    "contrib_imputada": 0.9980,
}


# ──────────────────────────────────────────────────────────────────────────────
# Função principal: construir série indicadora
# ──────────────────────────────────────────────────────────────────────────────

def build_indicator(df_fiscal: pd.DataFrame,
                    spec: str = "serie13",
                    coverage: str = "paper") -> pd.DataFrame:
    """
    Constrói a série indicadora agregada por trimestre.

    Parameters
    ----------
    df_fiscal : DataFrame com colunas [periodo, ano, trimestre, ente,
                componente, valor_bi]
    spec      : especificação da série
                "serie13"  – réplica exata do paper (melhor)
                "moderna_a" – cobertura ampliada, sem CI/RP
                "moderna_b" – cobertura ampliada, com CI
                "moderna_c" – cobertura ampliada, com CI e RP
    coverage  : "paper" | "all"

    Returns
    -------
    pd.DataFrame com colunas [data, indicador_bi, spec, coverage]
    """
    df = df_fiscal.copy()

    # ── Filtros por especificação ──────────────────────────────────────────
    if spec in ("serie13", "moderna_a"):
        componentes = ["salarios", "contrib_efetiva", "contrib_imputada"]
        include_rp = False
    elif spec == "moderna_b":
        componentes = ["salarios", "contrib_efetiva", "contrib_imputada",
                       "consumo_interm"]
        include_rp = False
    elif spec == "moderna_c":
        componentes = ["salarios", "contrib_efetiva", "contrib_imputada",
                       "consumo_interm"]
        include_rp = True
    else:
        componentes = ["salarios", "contrib_efetiva", "contrib_imputada"]
        include_rp = False

    mask = df["componente"].isin(componentes)
    if not include_rp and "is_rp" in df.columns:
        mask = mask & (~df["is_rp"].fillna(False))
    df = df[mask].copy()

    # ── Filtro de entes ───────────────────────────────────────────────────
    if coverage == "paper" and "ente" in df.columns:
        entes_validos = (list(ESTADOS_PAPER.keys()) +
                         ["uniao", "municipios"])
        df = df[df["ente"].isin(entes_validos) |
                df["ente"].str.startswith("mun_", na=False)]

    # ── Agregação trimestral ──────────────────────────────────────────────
    group_cols = [c for c in ["ano", "trimestre", "periodo"] if c in df.columns]
    agg = (df.groupby(group_cols)["valor_bi"]
             .sum()
             .reset_index()
             .rename(columns={"valor_bi": "indicador_bi"}))

    if "periodo" in agg.columns:
        agg["data"] = pd.to_datetime(
            agg["ano"].astype(str) + "Q" + agg["trimestre"].astype(str)
        ).dt.to_period("Q").dt.to_timestamp()
    else:
        agg["data"] = pd.to_datetime(
            agg["ano"].astype(str) + "Q" + agg["trimestre"].astype(str)
        ).dt.to_period("Q").dt.to_timestamp()

    agg["spec"] = spec
    agg["coverage"] = coverage

    return agg.sort_values("data").reset_index(drop=True)


# ──────────────────────────────────────────────────────────────────────────────
# Construir múltiplas especificações de uma vez
# ──────────────────────────────────────────────────────────────────────────────

SPEC_CONFIGS = {
    "serie1":    {"componentes": ["salarios", "contrib_efetiva"],
                  "entes": ["uniao"], "rp": False, "ci": False},
    "serie2":    {"componentes": ["salarios", "contrib_efetiva"],
                  "entes": ["uniao"], "rp": True, "ci": False},
    "serie3":    {"componentes": ["salarios", "contrib_efetiva"],
                  "entes": ["uniao", "estados"], "rp": False, "ci": False},
    "serie4":    {"componentes": ["salarios", "contrib_efetiva"],
                  "entes": ["uniao", "estados"], "rp": True, "ci": False},
    "serie5":    {"componentes": ["salarios", "contrib_efetiva"],
                  "entes": ["uniao", "estados", "municipios"], "rp": False, "ci": False},
    "serie6":    {"componentes": ["salarios", "contrib_efetiva"],
                  "entes": ["uniao", "estados", "municipios"], "rp": True, "ci": False},
    "serie7":    {"componentes": ["salarios", "contrib_efetiva", "consumo_interm"],
                  "entes": ["uniao", "estados", "municipios"], "rp": True, "ci": False},
    "serie8":    {"componentes": ["salarios", "contrib_efetiva", "consumo_interm"],
                  "entes": ["uniao", "estados", "municipios"], "rp": True, "ci": True},
    "serie9":    {"componentes": ["salarios", "contrib_efetiva", "consumo_interm"],
                  "entes": ["uniao", "estados"], "rp": True, "ci": True},
    "serie10":   {"componentes": ["salarios", "contrib_efetiva", "consumo_interm"],
                  "entes": ["uniao", "municipios"], "rp": True, "ci": True},
    "serie11":   {"componentes": ["salarios", "contrib_efetiva", "consumo_interm"],
                  "entes": ["uniao", "estados", "municipios"], "rp": False, "ci": True},
    "serie12":   {"componentes": ["salarios", "contrib_efetiva", "consumo_interm"],
                  "entes": ["uniao", "estados", "municipios"], "rp": True, "ci": False},
    "serie13":   {"componentes": ["salarios", "contrib_efetiva", "contrib_imputada"],
                  "entes": ["uniao", "estados", "municipios"], "rp": False, "ci": False},
    # Extensões modernas
    "moderna_a": {"componentes": ["salarios", "contrib_efetiva", "contrib_imputada"],
                  "entes": "all", "rp": False, "ci": False},
    "moderna_b": {"componentes": ["salarios", "contrib_efetiva", "contrib_imputada",
                                   "consumo_interm"],
                  "entes": "all", "rp": False, "ci": True},
    "moderna_c": {"componentes": ["salarios", "contrib_efetiva", "contrib_imputada",
                                   "consumo_interm"],
                  "entes": "all", "rp": True, "ci": True},
}


def build_all_indicators(df_fiscal: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    Constrói todas as especificações de séries indicadoras.

    Returns
    -------
    dict {spec_name: pd.Series indexada por data, com valor do indicador}
    """
    result = {}

    for spec_name, config in SPEC_CONFIGS.items():
        df = df_fiscal.copy()

        # Filtrar componentes
        mask_comp = df["componente"].isin(config["componentes"])
        if not config.get("rp", False) and "is_rp" in df.columns:
            mask_comp = mask_comp & (~df["is_rp"].fillna(False))
        df = df[mask_comp]

        # Filtrar entes
        entes = config["entes"]
        if entes != "all" and "ente" in df.columns:
            df = df[df["ente"].isin(entes)]

        # Agregar
        group_cols = [c for c in ["ano", "trimestre"] if c in df.columns]
        if not group_cols:
            continue

        agg = df.groupby(group_cols)["valor_bi"].sum().reset_index()
        agg["data"] = pd.to_datetime(
            agg["ano"].astype(str) + "Q" + agg["trimestre"].astype(str)
        ).dt.to_period("Q").dt.to_timestamp()
        agg = agg.set_index("data")["valor_bi"].sort_index()
        agg.name = spec_name
        result[spec_name] = agg

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Diagnóstico de representatividade
# ──────────────────────────────────────────────────────────────────────────────

def representativeness_table(df_fiscal: pd.DataFrame,
                              cnt_annual: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula a representatividade da amostra por componente (Tabela 3 do paper).
    """
    df = df_fiscal.copy()
    rows = []

    for comp in ["salarios", "contrib_efetiva", "contrib_imputada"]:
        mask = df["componente"] == comp
        annual_amostra = (df[mask]
                          .groupby("ano")["valor_bi"]
                          .sum()
                          .reset_index()
                          .rename(columns={"valor_bi": "amostra_bi"}))

        if cnt_annual is not None and "cnt_anual_bi" in cnt_annual.columns:
            merged = annual_amostra.merge(cnt_annual[["ano", "cnt_anual_bi"]], on="ano")
            merged["repr_pct"] = 100 * merged["amostra_bi"] / merged["cnt_anual_bi"]
            rows.append({
                "componente": comp,
                "representatividade_media": merged["repr_pct"].mean().round(2),
                "repr_min": merged["repr_pct"].min().round(2),
                "repr_max": merged["repr_pct"].max().round(2),
            })

    return pd.DataFrame(rows)
