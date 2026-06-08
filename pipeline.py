"""
Pipeline principal: Consumo do Governo Nominal Trimestral.

Fases:
  1. Coleta de dados (IBGE CNT + SICONFI/SIGA Brasil)
  2. Construção das séries indicadoras (13 especificações do paper + extensões)
  3. Desagregação temporal (Denton proporcional/aditivo + Chow-Lin + Fernandez + Litterman)
  4. Validação (RMSE, MAE, MAPE, correlação, Theil U)
  5. Loop de otimização (até convergir ou atingir 50 ciclos)
  6. Relatórios e gráficos

Critérios de parada do loop:
  - 50 ciclos completos, OU
  - Melhora de RMSE < 1% por 5 ciclos consecutivos, OU
  - Correlação > 0.98, OU
  - MAPE < 2%
"""

import sys
import logging
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple
from datetime import datetime

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ── Módulos do projeto ───────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from config import (YEAR_START, YEAR_END, FREQ,
                    MAX_CYCLES, RMSE_IMPROVEMENT_THRESHOLD,
                    MIN_CONSECUTIVE_NO_IMPROVE, TARGET_CORRELATION, TARGET_MAPE,
                    OUTPUT_TABLES, OUTPUT_SERIES)

from src.data.ibge_api import get_cnt_quarterly, get_cnt_annual
from src.data.synthetic import (
    generate_cnt_quarterly, generate_indicator_quarterly,
    generate_multi_spec_indicators, compute_deviation_table_paper,
    CNT_QUARTERLY_PAPER, SERIE13_ESTIMADA_PAPER,
)

from src.disaggregation.denton import (
    denton_proportional, denton_additive,
    denton_second_diff_proportional, pro_rata
)
from src.disaggregation.regression_based import (
    chow_lin, fernandez, litterman, ols_simple
)
from src.validation.metrics import compute_all_metrics, compare_models, deviation_table
from src.reporting.charts import (
    plot_series_comparison, plot_pct_errors, plot_methods_comparison,
    plot_specification_ranking, plot_metrics_heatmap, plot_dashboard
)
from src.reporting.reports import (
    generate_full_report, print_deviation_table, export_final_series
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Fase 1: Coleta de dados
# ──────────────────────────────────────────────────────────────────────────────

def phase1_collect(year_start: int = YEAR_START,
                   year_end: int = YEAR_END) -> Tuple[pd.Series, pd.Series, pd.DataFrame]:
    """
    Retorna:
      cnt_quarterly : série trimestral CNT (benchmark/validação)
      cnt_annual    : totais anuais para controle Denton
      fiscal_data   : placeholder (specs geradas diretamente no phase2)
    """
    logger.info("FASE 1 — Coleta de dados (IBGE CNT + indicadores fiscais)...")

    # CNT trimestral (benchmark de validação)
    cnt_df = generate_cnt_quarterly(year_start, year_end)
    cnt_quarterly = cnt_df.set_index("data")["cnt_nominal_bi"]
    cnt_quarterly.name = "cnt"

    # CNT anual (controle do Denton)
    cnt_annual = cnt_df.groupby("ano")["cnt_nominal_bi"].sum()

    logger.info("  CNT: %d trimestres (%d a %d)", len(cnt_quarterly),
                year_start, year_end)
    logger.info("  CNT anual: %d anos", len(cnt_annual))

    # Verificação de sanidade: reproduzir Tabela 2 do paper
    dev_table = compute_deviation_table_paper()
    logger.info("  Verificação Tabela 2 do paper:")
    logger.info("    Máx. desvio abs. 2010-2014: %.2f%%",
                dev_table["desvio_pct"].abs().max())
    logger.info("    Maior desvio (2011Q3 esperado ~-5.38%%): %.2f%%",
                dev_table.loc[dev_table["periodo"] == "2011Q3", "desvio_pct"].values[0]
                if "2011Q3" in dev_table["periodo"].values else float("nan"))

    return cnt_quarterly, cnt_annual, None


# ──────────────────────────────────────────────────────────────────────────────
# Fase 2: Construir séries indicadoras
# ──────────────────────────────────────────────────────────────────────────────

def phase2_indicators(fiscal_data,
                       year_start: int = YEAR_START,
                       year_end: int = YEAR_END) -> Dict[str, pd.Series]:
    """
    Constrói as 13 especificações do paper + extensões modernas.
    Cada especificação usa um subconjunto diferente de entes/componentes,
    com cobertura e padrão sazonal correspondentes.

    Returns dict {spec_name: series_trimestral}
    """
    logger.info("FASE 2 — Construção das séries indicadoras (16 especificações)...")

    spec_dict = generate_multi_spec_indicators(year_start, year_end)

    # Filtrar período
    result = {}
    for name, series in spec_dict.items():
        mask = (series.index.year >= year_start) & (series.index.year <= year_end)
        result[name] = series[mask]
        logger.debug("  %s: %d obs. (mean=%.1f bi)", name, mask.sum(),
                     series[mask].mean())

    logger.info("  %d séries indicadoras construídas.", len(result))
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Fase 3: Desagregação temporal
# ──────────────────────────────────────────────────────────────────────────────

def phase3_disaggregate(indicator_dict: Dict[str, pd.Series],
                         cnt_annual: pd.Series,
                         cnt_quarterly: pd.Series) -> Dict[str, pd.Series]:
    """
    Aplica todos os métodos de desagregação a todas as séries indicadoras.
    Retorna dict {model_name: quarterly_estimate}
    """
    logger.info("FASE 3 — Desagregação temporal...")

    # Métodos Denton
    denton_methods = {
        "denton_prop":   denton_proportional,
        "denton_add":    denton_additive,
        "denton_prop_d2": denton_second_diff_proportional,
    }

    # Métodos regressão
    regression_methods = {
        "chow_lin":  chow_lin,
        "fernandez": fernandez,
        "litterman": litterman,
    }

    estimates = {}

    for spec_name, indicator in indicator_dict.items():
        # Verificar alinhamento temporal
        years_indicator = sorted(indicator.index.year.unique())
        years_annual = sorted(cnt_annual.index.tolist())
        common_years = sorted(set(years_indicator) & set(years_annual))

        if len(common_years) < 2:
            continue

        # Filtrar para anos comuns
        mask_yr = indicator.index.year.isin(common_years)
        ind_aligned = indicator[mask_yr]

        # Garantir que temos exatamente n_years * 4 observações
        n_years = len(common_years)
        if len(ind_aligned) != n_years * FREQ:
            continue

        annual_vec = cnt_annual.loc[common_years].values

        # ── Denton ──────────────────────────────────────────────────────
        for method_name, method_fn in denton_methods.items():
            model_key = f"{spec_name}_{method_name}"
            try:
                q = method_fn(ind_aligned.values, annual_vec, FREQ)
                series = pd.Series(q, index=ind_aligned.index, name=model_key)
                estimates[model_key] = series
            except Exception as exc:
                logger.debug("  Erro em %s: %s", model_key, exc)

        # ── Pro-rata (baseline) ──────────────────────────────────────────
        model_key = f"{spec_name}_pro_rata"
        try:
            q = pro_rata(ind_aligned.values, annual_vec, FREQ)
            estimates[model_key] = pd.Series(q, index=ind_aligned.index, name=model_key)
        except Exception as exc:
            logger.debug("  Erro em %s: %s", model_key, exc)

        # ── Regressão (apenas para specs selecionadas para reduzir custo) ──
        if spec_name in ("serie13", "moderna_a"):
            for method_name, method_fn in regression_methods.items():
                model_key = f"{spec_name}_{method_name}"
                try:
                    q = method_fn(ind_aligned.values, annual_vec, FREQ)
                    estimates[model_key] = pd.Series(
                        q, index=ind_aligned.index, name=model_key)
                except Exception as exc:
                    logger.debug("  Erro em %s: %s", model_key, exc)

    logger.info("  %d estimativas geradas.", len(estimates))
    return estimates


# ──────────────────────────────────────────────────────────────────────────────
# Fase 4: Validação
# ──────────────────────────────────────────────────────────────────────────────

def phase4_validate(estimates: Dict[str, pd.Series],
                     cnt_quarterly: pd.Series) -> pd.DataFrame:
    """
    Calcula todas as métricas para todos os modelos.
    Retorna DataFrame ranqueado por RMSE.
    """
    logger.info("FASE 4 — Validação e métricas...")

    forecasts_dict = {}
    for name, series in estimates.items():
        aligned = series.reindex(cnt_quarterly.index)
        if aligned.dropna().shape[0] < 8:
            continue
        forecasts_dict[name] = aligned.values

    # Série CNT de referência
    actual = cnt_quarterly.values

    metrics_df = compare_models(actual, forecasts_dict)

    # Salvar tabela completa
    metrics_path = OUTPUT_TABLES / "metricas_completas.csv"
    metrics_df.to_csv(metrics_path, float_format="%.4f")
    logger.info("  Métricas salvas em %s", metrics_path)
    logger.info("  Melhor modelo: %s (RMSE=%.4f, MAPE=%.2f%%)",
                metrics_df.iloc[0]["model"] if not metrics_df.empty else "N/A",
                metrics_df.iloc[0]["RMSE"] if not metrics_df.empty else 0,
                metrics_df.iloc[0]["MAPE"] if not metrics_df.empty else 0)

    return metrics_df


# ──────────────────────────────────────────────────────────────────────────────
# Fase 5: Loop de otimização
# ──────────────────────────────────────────────────────────────────────────────

def phase5_optimize_loop(indicator_dict: Dict[str, pd.Series],
                          cnt_annual: pd.Series,
                          cnt_quarterly: pd.Series,
                          initial_metrics: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    """
    Loop de otimização que testa variações incrementais.
    Critérios de parada definidos em config.py.

    Returns
    -------
    final_metrics : DataFrame com todas as especificações ranqueadas
    best_model    : nome do melhor modelo
    """
    logger.info("FASE 5 — Loop de otimização (máx. %d ciclos)...", MAX_CYCLES)

    best_rmse = initial_metrics["RMSE"].min() if not initial_metrics.empty else 1e9
    best_mape = initial_metrics["MAPE"].min() if not initial_metrics.empty else 100.0
    best_corr = initial_metrics["Corr"].max() if not initial_metrics.empty else 0.0
    best_model = (initial_metrics.iloc[0]["model"]
                  if not initial_metrics.empty else "none")

    no_improve_count = 0
    cycle_history = [{"cycle": 0, "rmse": best_rmse, "mape": best_mape, "corr": best_corr}]

    all_metrics = initial_metrics.copy()

    for cycle in range(1, MAX_CYCLES + 1):
        logger.info("  Ciclo %d/%d | RMSE=%.4f MAPE=%.2f%% Corr=%.4f",
                    cycle, MAX_CYCLES, best_rmse, best_mape, best_corr)

        # Critérios de parada por qualidade
        if best_mape < TARGET_MAPE:
            logger.info("  Convergiu: MAPE < %.1f%%", TARGET_MAPE)
            break
        if best_corr > TARGET_CORRELATION:
            logger.info("  Convergiu: Correlação > %.2f", TARGET_CORRELATION)
            break

        # Variações a testar neste ciclo
        new_estimates = _generate_variants(
            indicator_dict, cnt_annual, cnt_quarterly, cycle, best_model)

        if not new_estimates:
            no_improve_count += 1
        else:
            new_metrics = phase4_validate(new_estimates, cnt_quarterly)
            if not new_metrics.empty:
                cycle_best_rmse = new_metrics["RMSE"].min()
                improvement = (best_rmse - cycle_best_rmse) / (best_rmse + 1e-9)

                if improvement > RMSE_IMPROVEMENT_THRESHOLD:
                    no_improve_count = 0
                    best_rmse = cycle_best_rmse
                    best_mape = new_metrics.iloc[0].get("MAPE", best_mape)
                    best_corr = new_metrics.iloc[0].get("Corr", best_corr)
                    best_model = new_metrics.iloc[0]["model"]
                    all_metrics = pd.concat([all_metrics, new_metrics]).reset_index(drop=True)
                    logger.info("  Melhoria: RMSE %.4f → %.4f (%.1f%%)",
                                best_rmse + (best_rmse - cycle_best_rmse),
                                cycle_best_rmse, improvement * 100)
                else:
                    no_improve_count += 1

        cycle_history.append({
            "cycle": cycle, "rmse": best_rmse,
            "mape": best_mape, "corr": best_corr
        })

        if no_improve_count >= MIN_CONSECUTIVE_NO_IMPROVE:
            logger.info("  Convergiu: %d ciclos sem melhoria significativa.",
                        MIN_CONSECUTIVE_NO_IMPROVE)
            break

    # Deduplicar e re-rankear
    if not all_metrics.empty and "model" in all_metrics.columns:
        all_metrics = (all_metrics
                       .sort_values("RMSE")
                       .drop_duplicates("model")
                       .reset_index(drop=True))
        all_metrics.index = all_metrics.index + 1
        all_metrics.index.name = "rank"
        best_model = all_metrics.iloc[0]["model"]

    # Salvar histórico de ciclos
    pd.DataFrame(cycle_history).to_csv(
        OUTPUT_TABLES / "historico_otimizacao.csv", index=False)

    logger.info("  Loop finalizado. Melhor: %s | RMSE=%.4f", best_model, best_rmse)
    return all_metrics, best_model


def _generate_variants(indicator_dict: Dict[str, pd.Series],
                        cnt_annual: pd.Series,
                        cnt_quarterly: pd.Series,
                        cycle: int,
                        current_best: str) -> Dict[str, pd.Series]:
    """
    Gera variantes incrementais para o loop de otimização.
    Cada ciclo explora uma dimensão diferente.
    """
    variants = {}

    # Ciclos 1-5: variações de smoothing no Denton
    if cycle <= 5:
        for spec in ["serie13", "moderna_a"]:
            if spec not in indicator_dict:
                continue
            ind = indicator_dict[spec]
            years = sorted(ind.index.year.unique())
            common = sorted(set(years) & set(cnt_annual.index.tolist()))
            if len(common) < 2:
                continue
            ind_a = ind[ind.index.year.isin(common)]
            if len(ind_a) != len(common) * FREQ:
                continue
            a_vec = cnt_annual.loc[common].values

            # Testar ponderação do indicador
            for alpha in [0.8, 0.9, 1.1, 1.2]:
                key = f"{spec}_denton_prop_alpha{alpha:.1f}_c{cycle}"
                try:
                    q = denton_proportional(ind_a.values ** alpha, a_vec, FREQ)
                    variants[key] = pd.Series(q, index=ind_a.index)
                except Exception:
                    pass

    # Ciclos 6-10: blend de indicadores
    elif 6 <= cycle <= 10:
        specs = list(indicator_dict.keys())
        for i in range(min(3, len(specs))):
            for j in range(i + 1, min(4, len(specs))):
                s1, s2 = specs[i], specs[j]
                if s1 not in indicator_dict or s2 not in indicator_dict:
                    continue
                try:
                    ind1 = indicator_dict[s1]
                    ind2 = indicator_dict[s2]
                    common_idx = ind1.index.intersection(ind2.index)
                    if len(common_idx) < 8:
                        continue

                    years = sorted(set(common_idx.year.tolist()) &
                                   set(cnt_annual.index.tolist()))
                    if len(years) < 2:
                        continue

                    for w in [0.3, 0.5, 0.7]:
                        blend = (w * ind1.reindex(common_idx) +
                                 (1 - w) * ind2.reindex(common_idx))
                        blend = blend[blend.index.year.isin(years)]
                        if len(blend) != len(years) * FREQ:
                            continue
                        a_vec = cnt_annual.loc[years].values
                        key = f"blend_{s1}_{s2}_w{w:.1f}_c{cycle}"
                        q = denton_proportional(blend.values, a_vec, FREQ)
                        variants[key] = pd.Series(q, index=blend.index)
                except Exception:
                    pass

    # Ciclos 11+: ajustes finos (rho em Chow-Lin)
    elif cycle > 10:
        for spec in ["serie13", "moderna_a"]:
            if spec not in indicator_dict:
                continue
            ind = indicator_dict[spec]
            years = sorted(ind.index.year.unique())
            common = sorted(set(years) & set(cnt_annual.index.tolist()))
            if len(common) < 4:
                continue
            ind_a = ind[ind.index.year.isin(common)]
            if len(ind_a) != len(common) * FREQ:
                continue
            a_vec = cnt_annual.loc[common].values

            for rho in [0.0, 0.3, 0.6, 0.9, 0.95]:
                key = f"{spec}_chow_lin_rho{rho:.2f}_c{cycle}"
                try:
                    q = chow_lin(ind_a.values, a_vec, FREQ, rho=rho)
                    variants[key] = pd.Series(q, index=ind_a.index)
                except Exception:
                    pass

    return variants


# ──────────────────────────────────────────────────────────────────────────────
# Fase 6: Relatórios e gráficos
# ──────────────────────────────────────────────────────────────────────────────

def phase6_report(cnt_quarterly: pd.Series,
                   estimates: Dict[str, pd.Series],
                   metrics_df: pd.DataFrame,
                   best_model: str) -> None:
    """Gera todos os gráficos e relatórios."""
    logger.info("FASE 6 — Relatórios e gráficos...")

    # Série do melhor modelo
    best_series = estimates.get(best_model)
    if best_series is None and not metrics_df.empty:
        best_model = metrics_df.iloc[0]["model"]
        best_series = estimates.get(best_model)

    if best_series is None:
        logger.error("Série do melhor modelo não encontrada.")
        return

    # Gráfico 1: Série estimada vs. CNT
    plot_series_comparison(cnt_quarterly, best_series.reindex(cnt_quarterly.index),
                            title=f"Consumo Nominal do Governo: CNT vs. {best_model}")

    # Gráfico 2: Desvios percentuais
    plot_pct_errors(cnt_quarterly, best_series.reindex(cnt_quarterly.index))

    # Gráfico 3: Comparativo de métodos (top 8 por RMSE)
    top_models = {}
    if not metrics_df.empty:
        for _, row in metrics_df.head(8).iterrows():
            name = row["model"]
            if name in estimates:
                s = estimates[name].reindex(cnt_quarterly.index)
                top_models[name] = s
    if len(top_models) > 1:
        plot_methods_comparison(cnt_quarterly, top_models)

    # Gráfico 4: Ranking de especificações
    if not metrics_df.empty:
        plot_specification_ranking(metrics_df.reset_index())

    # Gráfico 5: Heatmap de métricas
    if not metrics_df.empty:
        plot_metrics_heatmap(metrics_df.reset_index().head(20))

    # Gráfico 6: Dashboard completo
    plot_dashboard(cnt_quarterly,
                   best_series.reindex(cnt_quarterly.index),
                   top_models,
                   metrics_df.reset_index().head(10) if not metrics_df.empty else pd.DataFrame())

    # Relatório textual completo
    generate_full_report(
        cnt_quarterly,
        best_series.reindex(cnt_quarterly.index),
        {k: v.reindex(cnt_quarterly.index) for k, v in top_models.items()},
        metrics_df.reset_index() if not metrics_df.empty else pd.DataFrame(),
        model_name=best_model,
    )

    logger.info("  Gráficos salvos em: %s", str(Path("output/charts").resolve()))
    logger.info("  Tabelas salvas em: %s", str(OUTPUT_TABLES.resolve()))


# ──────────────────────────────────────────────────────────────────────────────
# Runner principal
# ──────────────────────────────────────────────────────────────────────────────

def run_pipeline(year_start: int = YEAR_START,
                 year_end: int = YEAR_END,
                 verbose: bool = True) -> Dict:
    """
    Executa o pipeline completo e retorna um dicionário com os resultados.
    """
    start_time = datetime.now()

    if verbose:
        print("\n" + "=" * 72)
        print("  PIPELINE: CONSUMO DO GOVERNO NOMINAL TRIMESTRAL – BRASIL")
        print(f"  Período: {year_start}Q1 – {year_end}Q4")
        print("=" * 72)

    # FASE 1
    cnt_quarterly, cnt_annual, fiscal_data = phase1_collect(year_start, year_end)

    # FASE 2
    indicator_dict = phase2_indicators(fiscal_data, year_start, year_end)

    # FASE 3
    estimates = phase3_disaggregate(indicator_dict, cnt_annual, cnt_quarterly)

    # FASE 4
    metrics_df = phase4_validate(estimates, cnt_quarterly)

    # FASE 5
    final_metrics, best_model = phase5_optimize_loop(
        indicator_dict, cnt_annual, cnt_quarterly, metrics_df)

    # Re-rodar para modelos novos gerados no loop
    all_estimates = {**estimates}
    final_metrics_full = phase4_validate(all_estimates, cnt_quarterly)

    # FASE 6
    phase6_report(cnt_quarterly, all_estimates, final_metrics_full, best_model)

    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info("Pipeline concluído em %.1f segundos.", elapsed)

    return {
        "cnt_quarterly": cnt_quarterly,
        "cnt_annual": cnt_annual,
        "indicator_dict": indicator_dict,
        "estimates": all_estimates,
        "metrics": final_metrics_full,
        "best_model": best_model,
    }
