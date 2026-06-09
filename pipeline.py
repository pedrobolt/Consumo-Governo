"""
Pipeline principal: Consumo do Governo Nominal Trimestral.

ESTADO ATUAL: Infraestrutura pronta; aguardando dados reais.

Fases (quando dados reais estiverem disponíveis):
  1. Coleta de dados (IBGE CNT + SICONFI/SIGA Brasil)
  2. Construção das séries indicadoras (13 especificações do paper)
  3. Desagregação temporal (Denton proporcional/aditivo, Chow-Lin, Fernandez, Litterman)
  4. Validação (RMSE, MAE, MAPE, correlação, Theil U) contra CNT publicada
  5. Relatórios e gráficos

REQUISITO: dados reais devem estar em data/raw/ antes de executar.
Ver DATA_ACQUISITION.md para instruções de download.
"""

import sys
import logging
from pathlib import Path
from typing import Dict, Tuple

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config import (YEAR_START, YEAR_END, FREQ, OUTPUT_TABLES, OUTPUT_SERIES)
from src.disaggregation.denton import (
    denton_proportional, denton_additive, denton_second_diff_proportional, pro_rata
)
from src.disaggregation.regression_based import chow_lin, fernandez, litterman
from src.validation.metrics import compute_all_metrics, compare_models, deviation_table
from src.reporting.charts import (
    plot_series_comparison, plot_pct_errors, plot_methods_comparison,
    plot_specification_ranking, plot_metrics_heatmap, plot_dashboard
)
from src.reporting.reports import print_deviation_table, export_final_series

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_cnt_real(path: str = "data/raw/cnt_quarterly.csv") -> Tuple[pd.Series, pd.Series]:
    """
    Carrega série CNT trimestral e anual de arquivo CSV real.

    Formato esperado do CSV:
      periodo,cnt_nominal_bi
      2010Q1,163.11
      ...

    Returns
    -------
    cnt_quarterly : pd.Series indexed by pd.Timestamp (início do trimestre)
    cnt_annual    : pd.Series indexed by int year
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Arquivo de dados reais não encontrado: {p}\n"
            "Execute o download conforme DATA_ACQUISITION.md antes de rodar o pipeline."
        )

    df = pd.read_csv(p)
    df["data"] = pd.to_datetime(df["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))
    df["ano"] = df["data"].dt.year
    df = df.sort_values("data").set_index("data")

    cnt_quarterly = df["cnt_nominal_bi"]
    cnt_annual = df.groupby("ano")["cnt_nominal_bi"].sum()
    return cnt_quarterly, cnt_annual


def load_fiscal_indicators(path: str = "data/raw/siconfi_fiscal.csv") -> Dict[str, pd.Series]:
    """
    Carrega indicadores fiscais do SICONFI/SIGA Brasil de arquivo CSV real.

    Formato esperado do CSV:
      periodo,spec,valor_bi
      2010Q1,serie13,65.42
      ...

    Returns
    -------
    dict {spec_name: pd.Series indexed by pd.Timestamp}
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Arquivo de indicadores fiscais não encontrado: {p}\n"
            "Execute o download conforme DATA_ACQUISITION.md antes de rodar o pipeline."
        )

    df = pd.read_csv(p)
    df["data"] = pd.to_datetime(df["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))
    df = df.sort_values("data")

    result = {}
    for spec, grp in df.groupby("spec"):
        s = grp.set_index("data")["valor_bi"]
        s.name = spec
        result[spec] = s

    return result


def disaggregate_all(indicator_dict: Dict[str, pd.Series],
                     cnt_annual: pd.Series) -> Dict[str, pd.Series]:
    """
    Aplica todos os métodos de desagregação a todas as séries indicadoras.
    """
    denton_methods = {
        "denton_prop":    denton_proportional,
        "denton_add":     denton_additive,
        "denton_prop_d2": denton_second_diff_proportional,
    }
    regression_methods = {
        "chow_lin":  chow_lin,
        "fernandez": fernandez,
        "litterman": litterman,
    }

    estimates = {}

    for spec_name, indicator in indicator_dict.items():
        years_ind = sorted(indicator.index.year.unique())
        common = sorted(set(years_ind) & set(cnt_annual.index.tolist()))
        if len(common) < 2:
            logger.warning("Spec %s: menos de 2 anos em comum com CNT — ignorado.", spec_name)
            continue

        ind_a = indicator[indicator.index.year.isin(common)]
        if len(ind_a) != len(common) * FREQ:
            logger.warning("Spec %s: %d obs ≠ %d anos × 4 — ignorado.",
                           spec_name, len(ind_a), len(common))
            continue

        a_vec = cnt_annual.loc[common].values

        for mname, mfn in denton_methods.items():
            key = f"{spec_name}_{mname}"
            try:
                q = mfn(ind_a.values, a_vec, FREQ)
                estimates[key] = pd.Series(q, index=ind_a.index)
            except Exception as exc:
                logger.debug("Erro %s: %s", key, exc)

        key = f"{spec_name}_pro_rata"
        try:
            q = pro_rata(ind_a.values, a_vec, FREQ)
            estimates[key] = pd.Series(q, index=ind_a.index)
        except Exception as exc:
            logger.debug("Erro %s: %s", key, exc)

        for mname, mfn in regression_methods.items():
            key = f"{spec_name}_{mname}"
            try:
                q = mfn(ind_a.values, a_vec, FREQ)
                estimates[key] = pd.Series(q, index=ind_a.index)
            except Exception as exc:
                logger.debug("Erro %s: %s", key, exc)

    logger.info("%d estimativas geradas.", len(estimates))
    return estimates


def validate_all(estimates: Dict[str, pd.Series],
                 cnt_quarterly: pd.Series) -> pd.DataFrame:
    """Calcula métricas para todos os modelos contra CNT publicada real."""
    aligned_series: Dict[str, pd.Series] = {}
    for name, series in estimates.items():
        aligned = series.reindex(cnt_quarterly.index).dropna()
        if len(aligned) < 8:
            continue
        aligned_series[name] = aligned

    if not aligned_series:
        return pd.DataFrame()

    # Use the index of the first series as the common evaluation window
    eval_index = next(iter(aligned_series.values())).index
    actual = cnt_quarterly.reindex(eval_index).values
    forecasts_dict = {name: s.reindex(eval_index).values for name, s in aligned_series.items()}

    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    metrics_df = compare_models(actual, forecasts_dict)
    metrics_df.to_csv(OUTPUT_TABLES / "metricas_completas.csv", float_format="%.4f")
    return metrics_df


def run_pipeline(cnt_csv: str = "data/raw/cnt_quarterly.csv",
                 fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Ponto de entrada principal. Requer arquivos CSV reais em data/raw/.
    Ver DATA_ACQUISITION.md para instruções de download.
    """
    logger.info("Carregando dados reais...")
    cnt_quarterly, cnt_annual = load_cnt_real(cnt_csv)
    indicator_dict = load_fiscal_indicators(fiscal_csv)

    logger.info("CNT: %d trimestres | %d anos", len(cnt_quarterly), len(cnt_annual))
    logger.info("Especificações fiscais: %d", len(indicator_dict))

    logger.info("Desagregando...")
    estimates = disaggregate_all(indicator_dict, cnt_annual)

    logger.info("Validando...")
    metrics_df = validate_all(estimates, cnt_quarterly)

    if not metrics_df.empty:
        best = metrics_df.iloc[0]
        logger.info("Melhor modelo: %s | RMSE=%.4f | MAPE=%.2f%% | Corr=%.4f",
                    best["model"], best.get("RMSE", 0),
                    best.get("MAPE", 0), best.get("Corr", 0))

        best_series = estimates.get(best["model"])
        if best_series is not None:
            plot_series_comparison(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
            plot_pct_errors(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
            plot_specification_ranking(metrics_df.reset_index())
            plot_metrics_heatmap(metrics_df.reset_index().head(20))


if __name__ == '__main__':
    run_pipeline()
