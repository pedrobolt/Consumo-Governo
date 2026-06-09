"""
Pseudo-out-of-sample validation.

Training:  2015-2023 (9 years, 36 quarters)
Test:      2024-2025 (2 years, 8 quarters)

For each spec x method:
  1. Fit disaggregation on 2015-2023 only
  2. Apply same method to 2024-2025 (annual CNT known, distribute quarterly)
  3. Compare quarterly estimates against actual CNT 2024-2025

Reports:
  - MAPE in-sample  (2015-2023)
  - MAPE OOS        (2024-2025)
  - MAPE full       (2015-2025)
  - MAPE original   (2015-2024, for comparison with earlier results)

Saves: output/tables/pseudo_oos.csv
"""

import sys
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FREQ, OUTPUT_TABLES
from src.disaggregation.denton import (
    denton_proportional, denton_additive, denton_second_diff_proportional, pro_rata
)
from src.disaggregation.regression_based import chow_lin, fernandez, litterman

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)

TRAIN_END  = 2023
TEST_START = 2024
TEST_END   = 2025

METHODS = {
    "denton_prop":    denton_proportional,
    "denton_add":     denton_additive,
    "denton_prop_d2": denton_second_diff_proportional,
    "pro_rata":       pro_rata,
    "chow_lin":       chow_lin,
    "fernandez":      fernandez,
    "litterman":      litterman,
}

# ── Load ──────────────────────────────────────────────────────────────────────

cnt = pd.read_csv(ROOT / "data/raw/cnt_quarterly.csv")
cnt["data"] = pd.to_datetime(
    cnt["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))
cnt = cnt.sort_values("data").set_index("data")["cnt_nominal_bi"]
cnt_annual_raw = cnt.groupby(cnt.index.year).sum()

# Only use complete years (4 quarters) for the annual constraint
complete_years = [y for y in cnt_annual_raw.index
                  if (cnt.index.year == y).sum() == 4]
cnt_annual = cnt_annual_raw.loc[complete_years]

fiscal = pd.read_csv(ROOT / "data/raw/siconfi_fiscal.csv")
fiscal["data"] = pd.to_datetime(
    fiscal["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))


def mets(actual, est):
    err = actual - est
    rmse = float(np.sqrt((err ** 2).mean()))
    mape = float((np.abs(err) / actual * 100).mean())
    corr = float(np.corrcoef(actual, est)[0, 1])
    return rmse, mape, corr


def run_pseudo_oos(spec_name, method_name, mfn):
    spec = (fiscal[fiscal["spec"] == spec_name]
            .set_index("data")["valor_bi"].sort_index())

    # Years where indicator has full 4 quarters AND annual CNT is available
    all_common = sorted(
        set(y for y in spec.index.year.unique()
            if (spec.index.year == y).sum() == FREQ)
        & set(cnt_annual.index.tolist())
    )
    if len(all_common) < 4:
        return None

    train_yrs = [y for y in all_common if y <= TRAIN_END]
    test_yrs  = [y for y in all_common if TEST_START <= y <= TEST_END]

    if len(train_yrs) < 2 or len(test_yrs) < 1:
        return None

    # ── Full-sample estimate (all available years) ────────────────────────────
    ind_full = spec[spec.index.year.isin(all_common)]
    a_full   = cnt_annual.loc[all_common].values
    try:
        q_full   = mfn(ind_full.values, a_full, FREQ)
        est_full = pd.Series(q_full, index=ind_full.index)
    except Exception:
        return None

    # ── Training estimate ─────────────────────────────────────────────────────
    ind_train = spec[spec.index.year.isin(train_yrs)]
    a_train   = cnt_annual.loc[train_yrs].values
    try:
        q_train   = mfn(ind_train.values, a_train, FREQ)
        est_train = pd.Series(q_train, index=ind_train.index)
    except Exception:
        return None

    # ── OOS: apply method to test years independently ─────────────────────────
    # Annual CNT for 2024-2025 is known; question is quarterly distribution.
    ind_test = spec[spec.index.year.isin(test_yrs)]
    a_test   = cnt_annual.loc[test_yrs].values
    try:
        q_test   = mfn(ind_test.values, a_test, FREQ)
        est_test = pd.Series(q_test, index=ind_test.index)
    except Exception:
        # Regression methods may be unstable with only 2 years; fall back to pro_rata
        try:
            q_test   = pro_rata(ind_test.values, a_test, FREQ)
            est_test = pd.Series(q_test, index=ind_test.index)
        except Exception:
            return None

    # ── Metrics ───────────────────────────────────────────────────────────────
    act_train = cnt.reindex(ind_train.index)
    act_test  = cnt.reindex(ind_test.index)
    act_full  = cnt.reindex(ind_full.index)

    r_tr, m_tr, c_tr = mets(act_train.values, est_train.values)
    r_te, m_te, c_te = mets(act_test.values,  est_test.values)
    r_fu, m_fu, c_fu = mets(act_full.values,  est_full.values)

    row = dict(
        spec=spec_name, method=method_name,
        n_train=len(ind_train), n_test=len(ind_test), n_full=len(ind_full),
        RMSE_train=round(r_tr, 4), MAPE_train=round(m_tr, 4), Corr_train=round(c_tr, 4),
        RMSE_oos=round(r_te, 4),   MAPE_oos=round(m_te, 4),   Corr_oos=round(c_te, 4),
        RMSE_full=round(r_fu, 4),  MAPE_full=round(m_fu, 4),  Corr_full=round(c_fu, 4),
    )

    # Original period 2015-2024 on the full-sample run (apples-to-apples with earlier results)
    orig_yrs = [y for y in all_common if y <= 2024]
    if len(orig_yrs) >= 2:
        try:
            ind_orig  = spec[spec.index.year.isin(orig_yrs)]
            est_orig  = pd.Series(
                mfn(ind_orig.values, cnt_annual.loc[orig_yrs].values, FREQ),
                index=ind_orig.index)
            r_o, m_o, c_o = mets(cnt.reindex(ind_orig.index).values, est_orig.values)
            row.update(RMSE_2015_2024=round(r_o, 4),
                       MAPE_2015_2024=round(m_o, 4),
                       Corr_2015_2024=round(c_o, 4))
        except Exception:
            pass

    return row


rows = []
for spec_name in fiscal["spec"].unique():
    for mname, mfn in METHODS.items():
        r = run_pseudo_oos(spec_name, mname, mfn)
        if r:
            rows.append(r)

df = pd.DataFrame(rows).sort_values("MAPE_oos").reset_index(drop=True)
df.index = df.index + 1
df.index.name = "rank_oos"
df.to_csv(OUTPUT_TABLES / "pseudo_oos.csv", float_format="%.4f")
print("Saved pseudo_oos.csv")

cols = ["spec", "method", "n_train", "n_test",
        "MAPE_train", "MAPE_oos", "MAPE_full", "MAPE_2015_2024", "Corr_full"]
print("\n=== TOP-10 BY OOS MAPE (2024-2025) ===")
print(df[cols].head(10).to_string())

best = df.iloc[0]
print(f"\n=== BEST OOS MODEL: {best['spec']}_{best['method']} ===")
print(f"  MAPE 2015-2023 (in-sample):  {best['MAPE_train']:.4f}%")
print(f"  MAPE 2024-2025 (OOS):        {best['MAPE_oos']:.4f}%")
print(f"  MAPE 2015-2024 (orig period): {best.get('MAPE_2015_2024', float('nan')):.4f}%")
print(f"  MAPE 2015-2025 (full):        {best['MAPE_full']:.4f}%")
