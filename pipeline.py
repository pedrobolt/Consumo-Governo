"""
Estimação trimestral do consumo nominal do governo — pipeline principal.

Método:
  In-sample (benchmark anual disponível): Denton proporcional
  Nowcast (sem benchmark anual):          Chow-Lin extrapolação

Uso:
  python pipeline.py                 # run completo
  python pipeline.py --full          # re-estima tudo do zero (idempotente)
  python pipeline.py --update        # checa fontes, re-estima se houver novidade
  python pipeline.py --nowcast-only  # atualiza só o nowcast (novo Bim do SICONFI)
  python pipeline.py --check         # verifica novas versões dos dados e sai
"""

import sys
import logging
import argparse
from datetime import date
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    FREQ,
    OUTPUT_TABLES,
    VINTAGE_FILE, UPDATE_REPORT_FILE,
)
from src.disaggregation.denton import denton_proportional, pro_rata
from src.disaggregation.regression_based import fit_and_extrapolate
from src.validation.metrics import compare_models
from src.reporting.charts import plot_series_comparison, plot_pct_errors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Three specs: estados wins, uniao is the paper baseline, combined is the middle ground.
EVAL_SPECS = [
    "spec_estados_sal_ce",          # winner — 27 estados, salários+CE
    "spec03_uniao_estados_sal_ce",  # União+estados composite
    "spec01_uniao_sal_ce",          # União only (paper Serie 1 baseline)
]

# Fixed after --full empirical validation; change here if a new winner emerges.
BEST_SPEC = "spec_estados_sal_ce"


# ── Data loading ──────────────────────────────────────────────────────────────

def _parse_quarter(s: pd.Series) -> pd.DatetimeIndex:
    return pd.to_datetime(s.str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))


def load_cnt_real(path: str = "data/raw/cnt_quarterly.csv") -> Tuple[pd.Series, pd.Series]:
    """
    Returns (cnt_quarterly, cnt_annual).
    cnt_annual excludes years without all 4 quarters (prevents partial-year benchmarks).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found.\nRun: python scripts/download_cnt.py"
        )
    df = pd.read_csv(p)
    df["data"] = _parse_quarter(df["periodo"])
    df["ano"] = df["data"].dt.year
    df = df.sort_values("data").set_index("data")

    cnt_quarterly = df["cnt_nominal_bi"]
    qcount = df.groupby("ano")["cnt_nominal_bi"].count()
    complete_years = qcount[qcount == FREQ].index
    cnt_annual = df.groupby("ano")["cnt_nominal_bi"].sum().loc[complete_years]
    return cnt_quarterly, cnt_annual


def load_fiscal_indicators(path: str = "data/raw/siconfi_fiscal.csv") -> Dict[str, pd.Series]:
    """Returns {spec_name: quarterly pd.Series} filtered to EVAL_SPECS."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found.\nRun: python scripts/build_siconfi_fiscal.py"
        )
    df = pd.read_csv(p)
    df["data"] = _parse_quarter(df["periodo"])
    df = df[df["spec"].isin(EVAL_SPECS)].sort_values("data")

    result = {}
    for spec, grp in df.groupby("spec"):
        s = grp.set_index("data")["valor_bi"]
        s.name = spec
        result[spec] = s
    return result


# ── Disaggregation ────────────────────────────────────────────────────────────

def disaggregate_all(indicator_dict: Dict[str, pd.Series],
                     cnt_annual: pd.Series) -> Dict[str, pd.Series]:
    """
    Runs 3 methods × 3 specs = up to 9 estimates.
    Methods: denton_prop (paper's method), pro_rata (baseline), chow_lin (in-sample fit).
    """
    from src.disaggregation.regression_based import chow_lin
    methods = {
        "denton_prop": denton_proportional,
        "pro_rata":    pro_rata,
        "chow_lin":    chow_lin,
    }
    estimates = {}

    for spec_name, indicator in indicator_dict.items():
        common = sorted(set(indicator.index.year.unique()) & set(cnt_annual.index.tolist()))
        if len(common) < 4:
            logger.warning("Spec %s: fewer than 4 common years with CNT — skipped.", spec_name)
            continue
        ind_a = indicator[indicator.index.year.isin(common)]
        if len(ind_a) != len(common) * FREQ:
            logger.warning("Spec %s: %d obs ≠ %d×4 — skipped.", spec_name, len(ind_a), len(common))
            continue
        a_vec = cnt_annual.loc[common].values

        for mname, mfn in methods.items():
            key = f"{spec_name}_{mname}"
            try:
                q = mfn(ind_a.values, a_vec, FREQ)
                estimates[key] = pd.Series(q, index=ind_a.index)
            except Exception as exc:
                logger.debug("Error %s: %s", key, exc)

    logger.info("%d estimates computed.", len(estimates))
    return estimates


# ── Validation ────────────────────────────────────────────────────────────────

def validate_all(estimates: Dict[str, pd.Series],
                 cnt_quarterly: pd.Series) -> pd.DataFrame:
    """Computes metrics for all models; saves metricas_completas.csv and ranking.csv."""
    aligned = {
        name: s.reindex(cnt_quarterly.index).dropna()
        for name, s in estimates.items()
    }
    aligned = {k: v for k, v in aligned.items() if len(v) >= 8}
    if not aligned:
        return pd.DataFrame()

    eval_index = next(iter(aligned.values())).index
    actual = cnt_quarterly.reindex(eval_index).values
    forecasts = {name: s.reindex(eval_index).values for name, s in aligned.items()}

    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    metrics_df = compare_models(actual, forecasts)
    metrics_df.to_csv(OUTPUT_TABLES / "metricas_completas.csv", float_format="%.4f")
    metrics_df.sort_values("MAPE").to_csv(OUTPUT_TABLES / "ranking.csv",
                                          float_format="%.4f", index=False)
    return metrics_df


# ── Nowcast helper ────────────────────────────────────────────────────────────

def _scale_partial_q2(spec_name: str, partial_value: float,
                      rreo_uniao_csv: str   = "data/raw/siconfi_rreo_uniao.csv",
                      rreo_estados_csv: str = "data/raw/siconfi_rreo_estados.csv",
                      train_years: range    = range(2015, 2026)) -> float:
    """
    Scale a partial Q2 indicator (Bim2×0.5 only) to a full-quarter estimate
    using the historical mean ratio Bim2×0.5 / (Bim2×0.5 + Bim3).
    Raises FileNotFoundError if the required raw CSVs are missing.
    """
    frames = []
    if "uniao" in spec_name or "spec03" in spec_name or "spec13" in spec_name:
        p = Path(rreo_uniao_csv)
        if not p.exists():
            raise FileNotFoundError(f"Required for partial Q2 scaling: {p}")
        frames.append(pd.read_csv(p))
    p = Path(rreo_estados_csv)
    if not p.exists():
        raise FileNotFoundError(f"Required for partial Q2 scaling: {p}")
    frames.append(pd.read_csv(p))

    raw = pd.concat(frames)
    bim = raw.groupby(["ano", "bimestre"])["valor_bi"].sum().unstack("bimestre")
    train_yrs = [y for y in train_years if y in bim.index]
    ratio = (bim.loc[train_yrs, 2] * 0.5) / (
        bim.loc[train_yrs, 2] * 0.5 + bim.loc[train_yrs, 3] * 1.0
    )
    return partial_value / float(ratio.mean())


# ── Model selected + outputs ──────────────────────────────────────────────────

def build_model_selected(estimates: Dict[str, pd.Series],
                         indicator_dict: Dict[str, pd.Series],
                         cnt_annual: pd.Series,
                         cnt_quarterly: pd.Series) -> None:
    """
    Writes model_selected.csv, desvios_trimestre.csv, and nowcast.csv.

    In-sample rows  (annual CNT benchmark available): denton_proportional
    Nowcast rows    (no annual benchmark yet):         chow_lin extrapolation

    Columns: quarter, method, spec, estimate_R_bi, cnt_R_bi, desvio_pct,
             is_provisional, selection_reason
    """
    bench_key = f"{BEST_SPEC}_denton_prop"
    if bench_key not in estimates:
        logger.error("Key %s not found in estimates. Cannot build model_selected.", bench_key)
        return

    bench_series = estimates[bench_key]
    train_yrs    = sorted(cnt_annual.index.tolist())

    # ── In-sample rows (Denton proportional) ──────────────────────────────────
    rows = []
    for dt, est_val in bench_series.items():
        act = cnt_quarterly.get(dt)
        dev_pct = (
            round((float(est_val) - float(act)) / float(act) * 100, 4)
            if act is not None and not pd.isna(act) else None
        )
        rows.append(dict(
            quarter=f"{dt.year}Q{dt.quarter}",
            method="denton_proportional",
            spec=BEST_SPEC,
            estimate_R_bi=round(float(est_val), 4),
            cnt_R_bi=round(float(act), 4) if act is not None and not pd.isna(act) else None,
            desvio_pct=dev_pct,
            is_provisional=False,
            selection_reason="annual CNT benchmark — Denton proportional (paper method)",
        ))

    # ── Nowcast rows (Chow-Lin extrapolation) ─────────────────────────────────
    spec_all = indicator_dict.get(BEST_SPEC)
    if spec_all is not None:
        nowcast_dates = [dt for dt in spec_all.index if dt.year not in train_yrs]
        if nowcast_dates:
            common_train = sorted(
                set(spec_all.index.year.unique()) & set(cnt_annual.index.tolist())
            )
            ind_train  = spec_all[spec_all.index.year.isin(common_train)]
            ann_train  = cnt_annual.loc[common_train].values
            ind_extrap = spec_all.loc[nowcast_dates].values.copy()

            # Q2 partial indicator: scale up from Bim2-only to full-quarter estimate
            for i, dt in enumerate(nowcast_dates):
                if dt.month == 4:   # April = start of Q2, only Bim2 available
                    try:
                        scaled = _scale_partial_q2(BEST_SPEC, float(ind_extrap[i]))
                        logger.info("Scaled partial Q2 indicator: %.4f → %.4f",
                                    ind_extrap[i], scaled)
                        ind_extrap[i] = scaled
                    except FileNotFoundError as exc:
                        logger.error("Cannot scale Q2: %s", exc)
                        return

            try:
                _, ext = fit_and_extrapolate(ind_train.values, ann_train,
                                             ind_extrap, method="chow_lin")
            except Exception as exc:
                logger.warning("Chow-Lin extrapolation failed: %s", exc)
                ext = np.full(len(nowcast_dates), np.nan)

            for i, dt in enumerate(nowcast_dates):
                est_val  = float(ext[i])
                act      = cnt_quarterly.get(dt)
                dev_pct  = (
                    round((est_val - float(act)) / float(act) * 100, 4)
                    if act is not None and not pd.isna(act) else None
                )
                is_partial = (dt.month == 4)
                rows.append(dict(
                    quarter=f"{dt.year}Q{dt.quarter}",
                    method="chow_lin",
                    spec=BEST_SPEC,
                    estimate_R_bi=round(est_val, 4),
                    cnt_R_bi=round(float(act), 4) if act is not None and not pd.isna(act) else None,
                    desvio_pct=dev_pct,
                    is_provisional=True,
                    selection_reason=(
                        "nowcast — Chow-Lin extrapolation; "
                        + ("partial Q2 (Bim2 only, scaled by historical ratio)"
                           if is_partial else "full indicator available")
                    ),
                ))

    df = pd.DataFrame(rows).sort_values("quarter").reset_index(drop=True)
    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_TABLES / "model_selected.csv", index=False)
    logger.info("model_selected.csv: %d in-sample + %d nowcast rows",
                df["is_provisional"].eq(False).sum(),
                df["is_provisional"].eq(True).sum())

    # desvios_trimestre.csv — in-sample only
    (df[df["is_provisional"] == False][["quarter", "cnt_R_bi", "estimate_R_bi", "desvio_pct"]]
     .to_csv(OUTPUT_TABLES / "desvios_trimestre.csv", index=False))

    # nowcast.csv — provisional rows only
    df[df["is_provisional"] == True].to_csv(OUTPUT_TABLES / "nowcast.csv", index=False)


# ── Vintage tracking ──────────────────────────────────────────────────────────

def append_vintage(model_selected_df: pd.DataFrame,
                   cnt_quarterly: pd.Series) -> None:
    """
    Append-only record of each run's estimates.
    Deduplicates on (run_date, quarter, method) — re-running the same day adds no rows.
    """
    run_date = str(date.today())
    new_rows = []
    for _, row in model_selected_df.iterrows():
        q  = row["quarter"]
        dt = pd.to_datetime(
            q.replace("Q1", "-01-01").replace("Q2", "-04-01")
             .replace("Q3", "-07-01").replace("Q4", "-10-01")
        )
        est        = float(row["estimate_R_bi"])
        act        = cnt_quarterly.get(dt)
        cnt_actual = float(act) if act is not None and not pd.isna(act) else None
        rev_err    = (
            round((est - cnt_actual) / cnt_actual * 100, 4)
            if cnt_actual is not None else None
        )
        new_rows.append(dict(
            run_date=run_date,
            quarter=q,
            estimate_R_bi=round(est, 4),
            method=row["method"],
            spec=row["spec"],
            is_nowcast=bool(row.get("is_provisional", False)),
            cnt_actual=round(cnt_actual, 4) if cnt_actual is not None else None,
            revision_error_pct=rev_err,
        ))

    new_df = pd.DataFrame(new_rows)
    VINTAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if VINTAGE_FILE.exists():
        existing = pd.read_csv(VINTAGE_FILE)
        existing_keys = set(zip(existing["run_date"], existing["quarter"], existing["method"]))
        new_df = new_df[
            ~new_df.apply(
                lambda r: (r["run_date"], r["quarter"], r["method"]) in existing_keys,
                axis=1,
            )
        ]
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df
    combined.to_csv(VINTAGE_FILE, index=False)
    logger.info("Vintage: %d total rows (added %d today)", len(combined), len(new_df))


# ── Update report ─────────────────────────────────────────────────────────────

def generate_update_report(model_selected_df: pd.DataFrame,
                           cnt_quarterly: pd.Series,
                           data_status: dict | None = None) -> None:
    """Write output/UPDATE_REPORT.md."""
    run_date = str(date.today())
    insamp   = model_selected_df[model_selected_df["is_provisional"] == False]
    nowcast  = model_selected_df[model_selected_df["is_provisional"] == True]

    lines = [
        "# Consumo do Governo — Update Report",
        "",
        f"**Run date:** {run_date}",
        "",
    ]

    if data_status:
        lines += [
            "## Data Status",
            "",
            "| Source | Cached | Available | New? |",
            "|--------|--------|-----------|------|",
            f"| CNT (IBGE/SIDRA) | {data_status.get('cnt',{}).get('cached','?')} "
            f"| {data_status.get('cnt',{}).get('available','?')} "
            f"| {'YES' if data_status.get('cnt',{}).get('new') else 'no'} |",
            f"| SICONFI RREO | {data_status.get('siconfi',{}).get('cached','?')} "
            f"| {data_status.get('siconfi',{}).get('available','?')} "
            f"| {'YES' if data_status.get('siconfi',{}).get('new') else 'no'} |",
            "",
        ]

    if not insamp.empty and insamp["desvio_pct"].notna().any():
        mape_is = insamp["desvio_pct"].abs().mean()
        lines += [
            "## In-Sample Performance (denton_proportional, spec_estados_sal_ce)",
            "",
            f"- Quarters: {len(insamp)}  |  MAPE: {mape_is:.2f}%",
            "",
        ]

    if not nowcast.empty:
        lines += [
            "## Nowcast (Chow-Lin, spec_estados_sal_ce)",
            "",
            "| Quarter | Estimate (R$ bn) | CNT Actual | Error % | Provisional? |",
            "|---------|-----------------|------------|---------|-------------|",
        ]
        for _, row in nowcast.iterrows():
            act_s = f"{row['cnt_R_bi']:.2f}" if pd.notna(row.get("cnt_R_bi")) else "—"
            err_s = f"{row['desvio_pct']:+.2f}%" if pd.notna(row.get("desvio_pct")) else "—"
            prov  = "YES" if row["is_provisional"] else "no"
            lines.append(
                f"| {row['quarter']} | {row['estimate_R_bi']:.2f} | {act_s} | {err_s} | {prov} |"
            )
        lines.append("")

    # Representativeness (if available)
    rep_path = OUTPUT_TABLES / "representatividade.csv"
    if rep_path.exists():
        rep = pd.read_csv(rep_path)
        latest_yr = rep["ano"].max()
        rep_latest = rep[rep["ano"] == latest_yr]
        lines += [f"## Sample Representativeness (latest year: {latest_yr})", ""]
        for _, row in rep_latest.iterrows():
            flag = " WARNING: drop >10pp year-over-year" if row.get("flag_drop", False) else ""
            lines.append(f"- {row['componente']}: {row['representatividade_pct']:.1f}%{flag}")
        lines.append("")

    # Revision history
    if VINTAGE_FILE.exists():
        vint    = pd.read_csv(VINTAGE_FILE)
        revised = vint[vint["revision_error_pct"].notna() & vint["is_nowcast"]].copy()
        if not revised.empty:
            lines += [
                "## Revision History (Nowcast vs Realized CNT)",
                "",
                "| Quarter | Run Date | Nowcast | CNT Actual | Error % |",
                "|---------|----------|---------|------------|---------|",
            ]
            for _, row in revised.sort_values(["quarter", "run_date"]).iterrows():
                lines.append(
                    f"| {row['quarter']} | {row['run_date']} "
                    f"| {row['estimate_R_bi']:.2f} | {row['cnt_actual']:.2f} "
                    f"| {row['revision_error_pct']:+.2f}% |"
                )
            lines.append("")

    # Real growth (if serie_real.csv exists)
    real_path = OUTPUT_TABLES / "serie_real.csv"
    if real_path.exists():
        real_df = pd.read_csv(real_path)
        real_df = real_df[real_df["var_real_yoy_pct"].notna()]
        if not real_df.empty:
            latest_real = real_df.sort_values("quarter").iloc[-1]
            proxy_note  = " (INPC proxy — deflator not yet published)" if latest_real["deflator_is_proxy"] else ""
            lines += [
                "## Real Growth",
                "",
                f"- Latest quarter with YoY estimate: **{latest_real['quarter']}**",
                f"- Real YoY growth: **{latest_real['var_real_yoy_pct']:+.1f}%**{proxy_note}",
                f"- Nominal: R$ {latest_real['nominal_R_bi']:.2f} bn  |  "
                  f"Real (base 2010): R$ {latest_real['real_R_bi_base2010']:.2f} bn",
                "",
            ]

    UPDATE_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    UPDATE_REPORT_FILE.write_text("\n".join(lines), encoding="utf-8")
    logger.info("UPDATE_REPORT.md written.")


# ── Pipeline modes ────────────────────────────────────────────────────────────

def run_pipeline(cnt_csv: str = "data/raw/cnt_quarterly.csv",
                 fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """Full pipeline: load data, disaggregate, validate, produce outputs."""
    logger.info("Loading data...")
    cnt_quarterly, cnt_annual = load_cnt_real(cnt_csv)
    indicator_dict = load_fiscal_indicators(fiscal_csv)
    logger.info("CNT: %d quarters | %d benchmark years", len(cnt_quarterly), len(cnt_annual))
    logger.info("Fiscal specs loaded: %d", len(indicator_dict))

    logger.info("Disaggregating...")
    estimates = disaggregate_all(indicator_dict, cnt_annual)

    logger.info("Validating...")
    metrics_df = validate_all(estimates, cnt_quarterly)
    if not metrics_df.empty:
        best = metrics_df.iloc[0]
        logger.info("Best overall: %s | MAPE=%.2f%% | Corr=%.4f",
                    best["model"], best.get("MAPE", 0), best.get("Corr", 0))

    build_model_selected(estimates, indicator_dict, cnt_annual, cnt_quarterly)

    # Charts
    best_key = f"{BEST_SPEC}_denton_prop"
    best_series = estimates.get(best_key)
    if best_series is not None:
        plot_series_comparison(cnt_quarterly, best_series.reindex(cnt_quarterly.index))
        plot_pct_errors(cnt_quarterly, best_series.reindex(cnt_quarterly.index))

    ms = pd.read_csv(OUTPUT_TABLES / "model_selected.csv")
    append_vintage(ms, cnt_quarterly)
    generate_update_report(ms, cnt_quarterly)


def run_nowcast_only(cnt_csv: str = "data/raw/cnt_quarterly.csv",
                     fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Refresh nowcast only — re-extrapolate with Chow-Lin, update model_selected.csv.
    Does not re-run Denton in-sample estimation.
    """
    logger.info("[nowcast-only] Loading data...")
    cnt_quarterly, cnt_annual = load_cnt_real(cnt_csv)
    indicator_dict = load_fiscal_indicators(fiscal_csv)
    estimates = disaggregate_all(indicator_dict, cnt_annual)
    build_model_selected(estimates, indicator_dict, cnt_annual, cnt_quarterly)
    ms = pd.read_csv(OUTPUT_TABLES / "model_selected.csv")
    append_vintage(ms, cnt_quarterly)
    generate_update_report(ms, cnt_quarterly)
    logger.info("[nowcast-only] Done.")


def run_update(cnt_csv: str = "data/raw/cnt_quarterly.csv",
               fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """
    Incremental update: check sources, re-estimate only if new data found.
    """
    from scripts.check_updates import check_updates
    logger.info("[update] Checking for new data...")
    status = check_updates(verbose=True)

    if not status["any_new"]:
        logger.info("[update] No new data. Refreshing vintage and report only.")
        ms_path = OUTPUT_TABLES / "model_selected.csv"
        if ms_path.exists():
            cnt_quarterly, _ = load_cnt_real(cnt_csv)
            ms = pd.read_csv(ms_path)
            append_vintage(ms, cnt_quarterly)
            generate_update_report(ms, cnt_quarterly, data_status=status)
        return

    logger.info("[update] New data detected — running full pipeline...")
    run_pipeline(cnt_csv, fiscal_csv)
    ms_path = OUTPUT_TABLES / "model_selected.csv"
    if ms_path.exists():
        cnt_quarterly, _ = load_cnt_real(cnt_csv)
        ms = pd.read_csv(ms_path)
        generate_update_report(ms, cnt_quarterly, data_status=status)
    logger.info("[update] Done.")


def run_full(cnt_csv: str = "data/raw/cnt_quarterly.csv",
             fiscal_csv: str = "data/raw/siconfi_fiscal.csv") -> None:
    """Full re-estimation from scratch (idempotent)."""
    logger.info("[full] Full re-estimation...")
    run_pipeline(cnt_csv, fiscal_csv)
    logger.info("[full] Done.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Consumo do Governo Nominal Trimestral — pipeline"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--full",         action="store_true",
                       help="Full re-estimation from scratch")
    group.add_argument("--update",       action="store_true",
                       help="Check sources; re-estimate only if new data")
    group.add_argument("--nowcast-only", action="store_true", dest="nowcast_only",
                       help="Refresh Chow-Lin nowcast only (no Denton re-run)")
    group.add_argument("--check",        action="store_true",
                       help="Check for new data and exit (no re-estimation)")
    args = parser.parse_args()

    if args.check:
        from scripts.check_updates import check_updates
        check_updates(verbose=True)
    elif args.full:
        run_full()
    elif args.update:
        run_update()
    elif args.nowcast_only:
        run_nowcast_only()
    else:
        run_pipeline()
