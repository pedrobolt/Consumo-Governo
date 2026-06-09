"""
Nowcast 2026Q2 government consumption.

Approach:
  - Benchmark period: 2015-2025 (11 annual CNT totals, 44 quarterly obs)
  - Indicator: spec03_uniao_estados_sal_ce (OOS winner)
  - Methods: Chow-Lin, Litterman
  - 2026Q1 extrapolation: compared against actual CNT (598.99 R$ bn)
  - 2026Q2 extrapolation: provisional — indicator based on Bim2 only (Bim3 not yet published)

Scaling for partial 2026Q2:
  Full Q2 = Bim2*0.5 + Bim3*1.0
  Partial Q2 = Bim2*0.5
  Historical ratio ~0.3136; scaled = partial / ratio

Outputs:
  output/tables/nowcast_2026Q2.csv
  output/charts/cnt_vs_best_estimate.png  (updated with dashed 2026Q2 line)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import FREQ, OUTPUT_TABLES, OUTPUT_CHARTS

ROOT = Path(__file__).resolve().parent.parent

SPEC = "spec03_uniao_estados_sal_ce"
TRAIN_YEARS = list(range(2015, 2026))   # 11 complete years


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse_period(s: pd.Series) -> pd.DatetimeIndex:
    return pd.to_datetime(s.str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True))


def _aggregation_matrix(n: int, freq: int = 4) -> np.ndarray:
    m = n // freq
    C = np.zeros((m, n))
    for k in range(m):
        C[k, k * freq:(k + 1) * freq] = 1.0
    return C


def _ar1_cov(n, rho, sigma2=1.0):
    if abs(rho) >= 1.0:
        return _rw_cov(n, sigma2)
    cov = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            cov[i, j] = sigma2 / (1 - rho**2) * rho**abs(i-j)
    return cov


def _rw_cov(n, sigma2=1.0, eps=1e-6):
    D = np.diff(np.eye(n), axis=0)
    return sigma2 * np.linalg.inv(D.T @ D + eps * np.eye(n))


def _ar1rw_cov(n, rho=0.5, sigma2=1.0, eps=1e-6):
    D = np.diff(np.eye(n), axis=0)
    H = np.zeros((n-1, n-1))
    for i in range(n-1):
        for j in range(n-1):
            H[i, j] = rho**abs(i-j)
    H /= (1 - rho**2 + 1e-10)
    try:
        H_inv = np.linalg.inv(H + eps * np.eye(n-1))
        return sigma2 * np.linalg.inv(D.T @ H_inv @ D + eps * np.eye(n))
    except np.linalg.LinAlgError:
        return _rw_cov(n, sigma2, eps)


def _mle_rho(X_q, y_a, C):
    from scipy.optimize import minimize_scalar
    n = len(X_q)
    X_a = C @ X_q
    def nll(rho):
        try:
            V_q = _ar1_cov(n, rho)
            V_a = C @ V_q @ C.T
            V_inv = np.linalg.inv(V_a + 1e-8*np.eye(len(V_a)))
            M = X_a.T @ V_inv @ X_a
            b = np.linalg.solve(M + 1e-10*np.eye(M.shape[0]), X_a.T @ V_inv @ y_a)
            r = y_a - X_a @ b
            _, ld = np.linalg.slogdet(V_a)
            return float(0.5 * (ld + r @ V_inv @ r))
        except Exception:
            return 1e10
    res = minimize_scalar(nll, bounds=(0, 0.999), method="bounded")
    return float(res.x)


def gls_fit_extrapolate(ind_train, ann_benchmarks, ind_extrap, method="chow_lin"):
    """
    Fit GLS on (ind_train, ann_benchmarks) and extrapolate to ind_extrap.

    Returns: (fitted_train, extrapolated, beta)
    """
    p = np.asarray(ind_train, dtype=float)
    a = np.asarray(ann_benchmarks, dtype=float)
    n, m = len(p), len(a)
    assert n == m * FREQ, f"n={n} != m*freq={m*FREQ}"

    C = _aggregation_matrix(n, FREQ)
    X_q = np.column_stack([np.ones(n), p])
    X_a = C @ X_q

    if method == "chow_lin":
        rho = _mle_rho(X_q, a, C)
        V_q = _ar1_cov(n, rho)
    else:  # litterman
        V_q = _ar1rw_cov(n, rho=0.5)

    eps = 1e-8
    V_a = C @ V_q @ C.T
    V_a_reg = V_a + eps * np.trace(V_a) / m * np.eye(m)
    V_inv = np.linalg.inv(V_a_reg)

    M = X_a.T @ V_inv @ X_a
    beta = np.linalg.solve(M + eps * np.trace(M) / 2 * np.eye(2),
                           X_a.T @ V_inv @ a)

    u_a = a - X_a @ beta
    u_q = V_q @ C.T @ V_inv @ u_a
    fitted = X_q @ beta + u_q

    p_ext = np.asarray(ind_extrap, dtype=float)
    X_ext = np.column_stack([np.ones(len(p_ext)), p_ext])
    extrap = X_ext @ beta

    return fitted, extrap, beta


# ── Load data ─────────────────────────────────────────────────────────────────

cnt_df = pd.read_csv(ROOT / "data/raw/cnt_quarterly.csv")
cnt_df["data"] = _parse_period(cnt_df["periodo"])
cnt_df = cnt_df.sort_values("data").set_index("data")
cnt_q = cnt_df["cnt_nominal_bi"]

qcount = cnt_df.groupby(cnt_df.index.year)["cnt_nominal_bi"].count()
complete_yrs = qcount[qcount == FREQ].index
cnt_annual = cnt_df.groupby(cnt_df.index.year)["cnt_nominal_bi"].sum().loc[complete_yrs]

fiscal = pd.read_csv(ROOT / "data/raw/siconfi_fiscal.csv")
fiscal["data"] = _parse_period(fiscal["periodo"])
spec_all = (fiscal[fiscal["spec"] == SPEC]
            .sort_values("data").set_index("data")["valor_bi"])

# ── Compute scaled 2026Q2 indicator ──────────────────────────────────────────

u_raw = pd.read_csv(ROOT / "data/raw/siconfi_rreo_uniao.csv")
e_raw = pd.read_csv(ROOT / "data/raw/siconfi_rreo_estados.csv")
bim_raw = pd.concat([u_raw, e_raw])
bim_by = bim_raw.groupby(["ano","bimestre"])["valor_bi"].sum().unstack("bimestre")

bim2_hist = bim_by.loc[TRAIN_YEARS, 2]
bim3_hist = bim_by.loc[TRAIN_YEARS, 3]
coverage_ratio = (bim2_hist * 0.5) / (bim2_hist * 0.5 + bim3_hist * 1.0)
avg_ratio = float(coverage_ratio.mean())

partial_q2 = float(spec_all.loc["2026-04-01"])
scaled_q2  = partial_q2 / avg_ratio
q1_ind     = float(spec_all.loc["2026-01-01"])

print(f"Indicator 2026Q1 (full):    {q1_ind:.4f} R$ bn")
print(f"Indicator 2026Q2 (partial): {partial_q2:.4f} R$ bn  [Bim2*0.5 only]")
print(f"Avg historical coverage ratio: {avg_ratio:.4f}")
print(f"Indicator 2026Q2 (scaled):  {scaled_q2:.4f} R$ bn")
print()

# ── Training data ─────────────────────────────────────────────────────────────

ind_train = spec_all[spec_all.index.year.isin(TRAIN_YEARS)]
assert len(ind_train) == len(TRAIN_YEARS) * FREQ
ann_train = cnt_annual.loc[TRAIN_YEARS].values
ind_extrap = np.array([q1_ind, scaled_q2])

cnt_2026q1_actual = float(cnt_q.loc["2026-01-01"])

# ── Fit + extrapolate ─────────────────────────────────────────────────────────

rows = []
results = {}
for method in ["chow_lin", "litterman"]:
    fitted, extrap, beta = gls_fit_extrapolate(
        ind_train.values, ann_train, ind_extrap, method=method)
    results[method] = (fitted, extrap)

    est_q1, est_q2 = extrap[0], extrap[1]
    err_q1 = est_q1 - cnt_2026q1_actual
    pct_q1 = abs(err_q1) / cnt_2026q1_actual * 100

    print(f"=== {method.upper()} ===")
    print(f"  beta = [{beta[0]:.2f}, {beta[1]:.4f}]")
    print(f"  2026Q1 estimate: {est_q1:.2f}  |  actual CNT: {cnt_2026q1_actual:.2f}  |  error: {err_q1:+.2f} ({pct_q1:.2f}%)")
    print(f"  2026Q2 NOWCAST:  {est_q2:.2f} R$ bn  [PROVISIONAL]")
    print()

    for q, est, actual, err, pct, is_prov, cov in [
        ("2026Q1", est_q1, cnt_2026q1_actual, round(err_q1,2), round(pct_q1,2),
         False, "Bim1+Bim2 fully observed (2 of 2 bimesters for Q1)"),
        ("2026Q2", est_q2, None, None, None,
         True, f"Bim2 only (1 of 2 bimesters; Bim3 not yet published; scaled by ratio={avg_ratio:.4f})"),
    ]:
        rows.append(dict(
            quarter=q,
            estimate_R_bi=round(est, 2),
            actual_CNT_R_bi=actual,
            error_R_bi=err,
            pct_error=pct,
            model=method,
            indicator_coverage=cov,
            is_provisional=is_prov,
        ))

# ── Save nowcast table ────────────────────────────────────────────────────────

OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
nowcast_df = pd.DataFrame(rows)
nowcast_df.to_csv(OUTPUT_TABLES / "nowcast_2026Q2.csv", index=False)
print(f"Saved output/tables/nowcast_2026Q2.csv")

# ── Append 2026Q1 to desvios_trimestre.csv ───────────────────────────────────

dev_path = OUTPUT_TABLES / "desvios_trimestre.csv"
if dev_path.exists():
    dev = pd.read_csv(dev_path)
    if "2026Q1" not in dev["periodo"].values:
        est_lit_q1 = results["litterman"][1][0]
        new_row = pd.DataFrame([dict(
            periodo="2026Q1",
            cnt_nominal_bi=round(cnt_2026q1_actual, 4),
            estimate=round(est_lit_q1, 4),
            desvio=round(est_lit_q1 - cnt_2026q1_actual, 4),
            desvio_pct=round((est_lit_q1 - cnt_2026q1_actual) / cnt_2026q1_actual * 100, 4),
        )])
        dev = pd.concat([dev, new_row], ignore_index=True)
        dev.to_csv(dev_path, index=False)
        print("Appended 2026Q1 row to desvios_trimestre.csv")

# ── Chart: cnt_vs_best_estimate.png ──────────────────────────────────────────

fitted_lit = pd.Series(results["litterman"][0], index=ind_train.index)
extrap_lit = results["litterman"][1]
extrap_cl  = results["chow_lin"][1]
extrap_dates = pd.to_datetime(["2026-01-01", "2026-04-01"])

fig, ax = plt.subplots(figsize=(13, 5))

ax.plot(cnt_q.index, cnt_q.values,
        color="#1a1a2e", lw=1.8, label="CNT publicado (IBGE)")

ax.plot(fitted_lit.index, fitted_lit.values,
        color="#e94560", lw=1.4, alpha=0.9,
        label="Litterman spec03 (in-sample, 2015-2025)")

# 2026Q1 actual vs estimate point
ax.scatter([extrap_dates[0]], [extrap_lit[0]],
           color="#e94560", s=60, zorder=5)

# 2026Q2 provisional lines
ax.plot([extrap_dates[0], extrap_dates[1]],
        [extrap_lit[0], extrap_lit[1]],
        color="#e94560", lw=1.5, ls="--", alpha=0.8,
        label=f"Nowcast Litterman 2026Q2: {extrap_lit[1]:.1f} R\$ bn [provisional]")
ax.scatter([extrap_dates[1]], [extrap_lit[1]],
           color="#e94560", s=65, facecolors="none", lw=1.5, zorder=5)

ax.plot([extrap_dates[0], extrap_dates[1]],
        [extrap_cl[0], extrap_cl[1]],
        color="#0f3460", lw=1.3, ls=":", alpha=0.8,
        label=f"Nowcast Chow-Lin 2026Q2: {extrap_cl[1]:.1f} R\$ bn [provisional]")
ax.scatter([extrap_dates[1]], [extrap_cl[1]],
           color="#0f3460", s=50, facecolors="none", lw=1.5, zorder=5)

ax.axvline(pd.Timestamp("2025-10-01"), color="gray", lw=0.8, ls="--", alpha=0.4)

ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
ax.set_xlabel("Trimestre")
ax.set_ylabel("R\$ bilhoes")
ax.set_title("Consumo do Governo Nominal Trimestral — CNT vs Estimativa + Nowcast 2026Q2",
             fontsize=11)
ax.legend(fontsize=8, loc="upper left")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()

OUTPUT_CHARTS.mkdir(parents=True, exist_ok=True)
fig.savefig(OUTPUT_CHARTS / "cnt_vs_best_estimate.png", dpi=150)
plt.close(fig)
print("Updated output/charts/cnt_vs_best_estimate.png")
