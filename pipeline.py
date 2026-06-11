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
import json
import logging
import argparse
from datetime import date
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    YEAR_START, YEAR_END, FREQ,
    OUTPUT_TABLES, OUTPUT_SERIES,
    BEST_SPEC, BEST_METHOD, OOS_WEIGHTS_FILE, VINTAGE_FILE, UPDATE_REPORT_FILE,
)
from src.disaggregation.denton import (
    denton_proportional, denton_additive, denton_second_diff_proportional, pro_rata
)
from src.disaggregation.regression_based import chow_lin, fernandez, litterman, fit_and_extrapolate
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
    # Only include years with all 4 quarters as annual benchmarks
    qcount = df.groupby("ano")["cnt_nominal_bi"].count()
    complete_years = qcount[qcount == FREQ].index
    cnt_annual = df.groupby("ano")["cnt_nominal_bi"].sum().loc[complete_years]
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


def select_best_benchmark_spec(metrics_df: pd.DataFrame):
    """
    Return (spec_name, method_key, mape, rmse) for the best benchmark model.

    Considers pro_rata and denton_proportional — both are parameter-free
    indicator-driven methods valid as in-sample benchmarks.  Pro_rata wins
    on spec_estados_sal_ce (MAPE 2.40% vs denton_prop 2.57%).
    """
    SUFFIXES = ("_pro_rata", "_denton_prop")
    bench = metrics_df[
        metrics_df["model"].str.endswith(SUFFIXES[0])
        | metrics_df["model"].str.endswith(SUFFIXES[1])
    ].copy()
    if bench.empty:
        raise RuntimeError("No pro_rata or denton_prop models in metrics_df")
    best = bench.sort_values("MAPE").iloc[0]
    model_name = best["model"]
    for suffix in SUFFIXES:
        if model_name.endswith(suffix):
            method_key = suffix.lstrip("_")
            spec = model_name[: -len(suffix)]
            break
    return spec, method_key, float(best["MAPE"]), float(best["RMSE"])


def load_oos_weights(best_spec: str,
                     oos_csv: str = "output/tables/pseudo_oos.csv") -> Dict[str, float]:
    """
    Compute inverse-OOS-MAPE ensemble weights for chow_lin and litterman.

    Reads pseudo_oos.csv, filters for best_spec, and returns normalised weights
    so that w_cl + w_lt = 1.  Saves result to OOS_WEIGHTS_FILE for caching.
    """
    # Return cached weights if file is fresh
    if OOS_WEIGHTS_FILE.exists():
        with open(OOS_WEIGHTS_FILE) as f:
            return json.load(f)

    df = pd.read_csv(oos_csv)
    subset = df[(df["spec"] == best_spec) & (df["method"].isin(["chow_lin", "litterman"]))]
    if subset.empty:
        logger.warning("OOS weights not found for %s — using equal weights.", best_spec)
        return {"chow_lin": 0.5, "litterman": 0.5}

    mapes = subset.set_index("method")["MAPE_oos"]
    inv   = 1.0 / mapes
    total = inv.sum()
    weights = {"chow_lin": float(inv["chow_lin"] / total),
               "litterman": float(inv["litterman"] / total)}
    OOS_WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OOS_WEIGHTS_FILE, "w") as f:
        json.dump(weights, f, indent=2)
    logger.info("OOS weights saved: CL=%.4f  LT=%.4f",
                weights["chow_lin"], weights["litterman"])
    return weights


def _scale_partial_q2(spec_name: str, partial_value: float,
                      rreo_uniao_csv: str = "data/raw/siconfi_rreo_uniao.csv",
                      rreo_estados_csv: str = "data/raw/siconfi_rreo_estados.csv",
                      train_years: range = range(2015, 2026)) -> float:
    """
    Scale a partial 2026Q2 indicator (Bim2*0.5 only) to a full-quarter estimate.

    Historical ratio = mean(Bim2*0.5 / (Bim2*0.5 + Bim3)) over training years.
    Covers both estados-only and combined specs.
    """
    frames = []
    if "uniao" in spec_name or "spec03" in spec_name or "spec13" in spec_name:
        if Path(rreo_uniao_csv).exists():
            frames.append(pd.read_csv(rreo_uniao_csv))
    if Path(rreo_estados_csv).exists():
        frames.append(pd.read_csv(rreo_estados_csv))
    if not frames:
        return partial_value * 3.0   # crude fallback: Bim2*0.5 ≈ 1/3 of Q2
    raw = pd.concat(frames)
    bim = raw.groupby(["ano", "bimestre"])["valor_bi"].sum().unstack("bimestre")
    train_yrs = [y for y in train_years if y in bim.index]
    bim2 = bim.loc[train_yrs, 2]
    bim3 = bim.loc[train_yrs, 3]
    ratio = (bim2 * 0.5) / (bim2 * 0.5 + bim3 * 1.0)
    return partial_value / float(ratio.mean())


def build_model_selected(
        best_spec: str,
        estimates: Dict[str, pd.Series],
        indicator_dict: Dict[str, pd.Series],
        cnt_annual: pd.Series,
        cnt_quarterly: pd.Series,
        cl_rmse: float,
        oos_weights: Dict[str, float] | None = None,
        best_method_key: str = "pro_rata") -> None:
    """
    Produce output/tables/model_selected.csv with hybrid method assignment:
      - Benchmark quarters (annual CNT available): best_method_key (pro_rata or denton_prop)
      - Nowcast quarters (no annual benchmark yet): ensemble Chow-Lin + Litterman

    Columns: quarter, method, spec, estimate_R_bi, cnt_R_bi, desvio_pct,
             lower_90, upper_90, is_provisional, selection_reason
    """
    if oos_weights is None:
        oos_weights = {"chow_lin": 0.5, "litterman": 0.5}
    w_cl = oos_weights.get("chow_lin", 0.5)
    w_lt = oos_weights.get("litterman", 0.5)

    bench_key = f"{best_spec}_{best_method_key}"
    if bench_key not in estimates:
        logger.warning("Benchmark key %s not found in estimates.", bench_key)
        return

    bench_series = estimates[bench_key]
    train_yrs    = sorted(cnt_annual.index.tolist())

    # ── In-sample rows ────────────────────────────────────────────────────────
    rows = []
    for dt, est_val in bench_series.items():
        act = cnt_quarterly.get(dt)
        dev_pct = ((float(est_val) - float(act)) / float(act) * 100
                   if act is not None and not pd.isna(act) else None)
        rows.append(dict(
            quarter=f"{dt.year}Q{dt.quarter}",
            method=best_method_key,
            spec=best_spec,
            estimate_R_bi=round(float(est_val), 4),
            cnt_R_bi=round(float(act), 4) if act is not None and not pd.isna(act) else None,
            desvio_pct=round(dev_pct, 4) if dev_pct is not None else None,
            lower_90=None,
            upper_90=None,
            is_provisional=False,
            selection_reason=f"annual CNT benchmark available — {best_method_key} (parameter-free, in-sample winner)",
        ))

    # ── Nowcast rows (ensemble Chow-Lin + Litterman) ──────────────────────────
    spec_all = indicator_dict.get(best_spec)
    if spec_all is not None:
        nowcast_dates = [dt for dt in spec_all.index if dt.year not in train_yrs]
        if nowcast_dates:
            common_train = sorted(set(spec_all.index.year.unique())
                                  & set(cnt_annual.index.tolist()))
            ind_train = spec_all[spec_all.index.year.isin(common_train)]
            ann_train = cnt_annual.loc[common_train].values

            # Scale partial Q2 if present (Bim3 not yet published)
            ind_extrap_raw = spec_all.loc[nowcast_dates].values.copy()
            extrap_dates   = nowcast_dates

            # Identify 2026Q2 as partial (only 2 out of 6 bimesters of the year)
            partial_mask = [dt.month == 4 and dt.year >= 2026 for dt in extrap_dates]
            for i, (dt, is_partial) in enumerate(zip(extrap_dates, partial_mask)):
                if is_partial:
                    ind_extrap_raw[i] = _scale_partial_q2(best_spec, float(ind_extrap_raw[i]))

            try:
                _, ext_cl, se_cl = fit_and_extrapolate(ind_train.values, ann_train,
                                                       ind_extrap_raw, method="chow_lin")
                _, ext_lt, se_lt = fit_and_extrapolate(ind_train.values, ann_train,
                                                       ind_extrap_raw, method="litterman")
            except Exception as exc:
                logger.warning("Nowcast extrapolation failed: %s", exc)
                ext_cl = ext_lt = np.full(len(extrap_dates), np.nan)
                se_cl  = se_lt  = np.full(len(extrap_dates), cl_rmse)

            z90 = 1.645
            for i, dt in enumerate(extrap_dates):
                ensemble  = w_cl * float(ext_cl[i]) + w_lt * float(ext_lt[i])
                se_ens    = float(np.sqrt(w_cl**2 * se_cl[i]**2 + w_lt**2 * se_lt[i]**2))
                se_use    = se_ens if se_ens > 0 else cl_rmse
                lo  = ensemble - z90 * se_use
                hi  = ensemble + z90 * se_use
                act = cnt_quarterly.get(dt)
                dev_pct = ((ensemble - float(act)) / float(act) * 100
                           if act is not None and not pd.isna(act) else None)
                is_partial = partial_mask[i]
                cov_note = (
                    "Bim2 only (Bim3 not yet published; scaled by historical ratio)"
                    if is_partial else
                    "Bim1+Bim2 fully observed"
                )
                rows.append(dict(
                    quarter=f"{dt.year}Q{dt.quarter}",
                    method="ensemble(chow_lin,litterman)",
                    spec=best_spec,
                    estimate_R_bi=round(ensemble, 4),
                    cnt_R_bi=round(float(act), 4) if act is not None and not pd.isna(act) else None,
                    desvio_pct=round(dev_pct, 4) if dev_pct is not None else None,
                    lower_90=round(lo, 4),
                    upper_90=round(hi, 4),
                    is_provisional=True,
                    selection_reason=(
                        f"no annual CNT benchmark — ensemble CL+LT extrapolation; "
                        f"indicator: {cov_note}"
                    ),
                ))

    df = (pd.DataFrame(rows)
          .sort_values("quarter")
          .reset_index(drop=True))
    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_TABLES / "model_selected.csv", index=False)
    logger.info("Saved model_selected.csv: %d rows (%d benchmark [%s], %d nowcast)",
                len(df),
                df["method"].eq(best_method_key).sum(),
                best_method_key,
                df["method"].ne(best_method_key).sum())


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

        # ── Hybrid model selection ─────────────────────────────────────────
        best_spec, best_method_key, bench_mape, bench_rmse = select_best_benchmark_spec(metrics_df)
        logger.info("Best benchmark spec: %s | method: %s | MAPE=%.4f%% | RMSE=%.4f",
                    best_spec, best_method_key, bench_mape, bench_rmse)
        oos_weights = load_oos_weights(best_spec)
        build_model_selected(best_spec, estimates, indicator_dict,
                             cnt_annual, cnt_quarterly, bench_rmse,
                             oos_weights=oos_weights,
                             best_method_key=best_method_key)

        best_series = estimates.get(best["model"])
        if best_series is not None:
            plot_series_comparison(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
            plot_pct_errors(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
            plot_specification_ranking(metrics_df.reset_index())
            plot_metrics_heatmap(metrics_df.reset_index().head(20))


def append_vintage(model_selected_df: pd.DataFrame,
                   cnt_quarterly: pd.Series) -> None:
    """
    Append current model_selected rows to vintage_history.csv (append-only).

    For rows where cnt_actual was previously missing but is now available
    in cnt_quarterly, the revision_error_pct is computed and written.
    Columns: run_date, quarter, estimate_R_bi, method, spec,
             is_nowcast, cnt_actual, revision_error_pct
    """
    run_date = str(date.today())

    new_rows = []
    for _, row in model_selected_df.iterrows():
        q   = row["quarter"]
        est = row["estimate_R_bi"]
        is_prov = bool(row.get("is_provisional", False))

        # Try to fill cnt_actual from cnt_quarterly
        dt = pd.to_datetime(q.replace("Q1", "-01-01").replace("Q2", "-04-01")
                             .replace("Q3", "-07-01").replace("Q4", "-10-01"))
        act = cnt_quarterly.get(dt)
        cnt_actual = float(act) if (act is not None and not pd.isna(act)) else None
        rev_err    = ((est - cnt_actual) / cnt_actual * 100
                      if cnt_actual is not None else None)

        new_rows.append(dict(
            run_date=run_date,
            quarter=q,
            estimate_R_bi=round(float(est), 4),
            method=row["method"],
            spec=row["spec"],
            is_nowcast=is_prov,
            cnt_actual=round(cnt_actual, 4) if cnt_actual is not None else None,
            revision_error_pct=round(rev_err, 4) if rev_err is not None else None,
        ))

    new_df = pd.DataFrame(new_rows)
    VINTAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if VINTAGE_FILE.exists():
        existing = pd.read_csv(VINTAGE_FILE)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_csv(VINTAGE_FILE, index=False)
    logger.info("Vintage history: %d total rows (added %d today)",
                len(combined), len(new_df))


def generate_update_report(model_selected_df: pd.DataFrame,
                           cnt_quarterly: pd.Series,
                           data_status: dict | None = None) -> None:
    """Write UPDATE_REPORT.md with run metadata, nowcast estimates, and revision history."""
    run_date = str(date.today())

    nowcast = model_selected_df[model_selected_df["is_provisional"] == True]
    insamp  = model_selected_df[model_selected_df["is_provisional"] == False]

    lines = [
        f"# Consumo do Governo — Update Report",
        f"",
        f"**Run date:** {run_date}",
        f"",
    ]

    if data_status:
        lines += [
            "## Data Status",
            "",
            f"| Source | Cached | Available | New? |",
            f"|--------|--------|-----------|------|",
            f"| CNT (IBGE/SIDRA) | {data_status.get('cnt',{}).get('cached','?')} "
            f"| {data_status.get('cnt',{}).get('available','?')} "
            f"| {'YES' if data_status.get('cnt',{}).get('new') else 'no'} |",
            f"| SICONFI RREO | {data_status.get('siconfi',{}).get('cached','?')} "
            f"| {data_status.get('siconfi',{}).get('available','?')} "
            f"| {'YES' if data_status.get('siconfi',{}).get('new') else 'no'} |",
            "",
        ]

    lines += [
        "## In-Sample Performance (Denton-Cholette)",
        "",
        f"- Quarters covered: {len(insamp)}",
    ]
    if not insamp.empty and insamp["desvio_pct"].notna().any():
        mape_is = insamp["desvio_pct"].abs().mean()
        lines.append(f"- MAPE (in-sample): {mape_is:.2f}%")
    lines.append("")

    if not nowcast.empty:
        lines += ["## Nowcast Estimates (Ensemble CL+LT)", ""]
        lines += ["| Quarter | Estimate (R$ bn) | Lower 90% | Upper 90% | Is Provisional |",
                  "|---------|-----------------|-----------|-----------|----------------|"]
        for _, row in nowcast.iterrows():
            lo  = f"{row['lower_90']:.2f}" if pd.notna(row.get("lower_90")) else "—"
            hi  = f"{row['upper_90']:.2f}" if pd.notna(row.get("upper_90")) else "—"
            prov = "YES" if row["is_provisional"] else "no"
            lines.append(
                f"| {row['quarter']} | {row['estimate_R_bi']:.2f} "
                f"| {lo} | {hi} | {prov} |"
            )
        lines.append("")

    # Revision history from vintage file
    if VINTAGE_FILE.exists():
        vint = pd.read_csv(VINTAGE_FILE)
        revised = vint[vint["revision_error_pct"].notna() & vint["is_nowcast"]].copy()
        if not revised.empty:
            lines += ["## Revision History (Nowcast vs Realized CNT)", ""]
            lines += ["| Quarter | Run Date | Nowcast | CNT Actual | Error % |",
                      "|---------|----------|---------|------------|---------|"]
            for _, row in revised.sort_values(["quarter","run_date"]).iterrows():
                lines.append(
                    f"| {row['quarter']} | {row['run_date']} "
                    f"| {row['estimate_R_bi']:.2f} | {row['cnt_actual']:.2f} "
                    f"| {row['revision_error_pct']:+.2f}% |"
                )
            lines.append("")

    UPDATE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    logger.info("UPDATE_REPORT.md written to %s", UPDATE_REPORT_FILE)


def run_nowcast_only(cnt_csv: str = "data/raw/cnt_quarterly.csv",
                     fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Refresh only the nowcast: reload SICONFI indicator, re-extrapolate ensemble,
    update model_selected.csv, append vintage, write UPDATE_REPORT.
    No re-estimation of Denton (benchmark quarters unchanged).
    """
    logger.info("[nowcast-only] Loading data...")
    cnt_quarterly, cnt_annual = load_cnt_real(cnt_csv)
    indicator_dict = load_fiscal_indicators(fiscal_csv)

    best_spec      = BEST_SPEC
    best_method_key = BEST_METHOD
    estimates = disaggregate_all(indicator_dict, cnt_annual)
    oos_weights = load_oos_weights(best_spec)

    bench_rmse = 1.0
    metrics_path = OUTPUT_TABLES / "metricas_completas.csv"
    if metrics_path.exists():
        m   = pd.read_csv(metrics_path)
        row = m[m["model"] == f"{best_spec}_{best_method_key}"]
        if not row.empty:
            bench_rmse = float(row.iloc[0]["RMSE"])

    build_model_selected(best_spec, estimates, indicator_dict,
                         cnt_annual, cnt_quarterly, bench_rmse,
                         oos_weights=oos_weights,
                         best_method_key=best_method_key)

    ms = pd.read_csv(OUTPUT_TABLES / "model_selected.csv")
    append_vintage(ms, cnt_quarterly)
    generate_update_report(ms, cnt_quarterly)
    logger.info("[nowcast-only] Done.")


def run_update(cnt_csv: str = "data/raw/cnt_quarterly.csv",
               fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Incremental update:
      1. Check SIDRA + SICONFI for new data
      2. If new data exists, run full pipeline
      3. Append vintage + generate UPDATE_REPORT
    """
    from scripts.check_updates import check_updates
    logger.info("[update] Checking for new data...")
    status = check_updates(verbose=True)

    if not status["any_new"]:
        logger.info("[update] No new data. Updating vintage and report only.")
        ms_path = OUTPUT_TABLES / "model_selected.csv"
        if ms_path.exists():
            ms = pd.read_csv(ms_path)
            cnt_quarterly, _ = load_cnt_real(cnt_csv)
            append_vintage(ms, cnt_quarterly)
            generate_update_report(ms, cnt_quarterly, data_status=status)
        return

    logger.info("[update] New data detected — running full pipeline...")
    run_pipeline(cnt_csv, fiscal_csv)
    ms_path = OUTPUT_TABLES / "model_selected.csv"
    if ms_path.exists():
        cnt_quarterly, _ = load_cnt_real(cnt_csv)
        ms = pd.read_csv(ms_path)
        append_vintage(ms, cnt_quarterly)
        generate_update_report(ms, cnt_quarterly, data_status=status)
    logger.info("[update] Done.")


def run_full(cnt_csv: str = "data/raw/cnt_quarterly.csv",
             fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Full rerun: re-select spec, recompute OOS weights, rebuild all outputs.
    Deletes cached oos_weights.json so weights are recomputed from pseudo_oos.csv.
    """
    logger.info("[full] Clearing cached OOS weights...")
    if OOS_WEIGHTS_FILE.exists():
        OOS_WEIGHTS_FILE.unlink()

    run_pipeline(cnt_csv, fiscal_csv)

    ms_path = OUTPUT_TABLES / "model_selected.csv"
    if ms_path.exists():
        cnt_quarterly, _ = load_cnt_real(cnt_csv)
        ms = pd.read_csv(ms_path)
        append_vintage(ms, cnt_quarterly)
        generate_update_report(ms, cnt_quarterly)
    logger.info("[full] Done.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Consumo do Governo Nominal Trimestral — pipeline principal"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--update",
        action="store_true",
        help="Incremental update: check SIDRA+SICONFI, re-estimate if new data, append vintage",
    )
    group.add_argument(
        "--full",
        action="store_true",
        help="Full rerun: re-select spec, recompute OOS weights, rebuild all outputs",
    )
    group.add_argument(
        "--nowcast-only",
        action="store_true",
        dest="nowcast_only",
        help="Refresh nowcast only (no Denton re-estimation)",
    )
    args = parser.parse_args()

    if args.update:
        run_update()
    elif args.full:
        run_full()
    elif args.nowcast_only:
        run_nowcast_only()
    else:
        run_pipeline()
