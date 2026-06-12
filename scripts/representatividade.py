"""
Tabela de Representatividade da Amostra SICONFI vs. CNT.

Computes what fraction of the CNT annual total is explained by each
SICONFI component. Follows Santos et al. (2015) Table 3 structure.

Usage:
    python scripts/representatividade.py

Output:
    output/tables/representatividade.csv
    Columns: ano, componente, amostra_R_bi, referencia_R_bi, representatividade_pct, flag_drop

Denominador: CNT annual total (consumo do governo — nominal, R$ bi).
A drop > 10 pp year-over-year triggers flag_drop=True and a WARNING.
"""

import logging
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import OUTPUT_TABLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def bim_to_annual(path: Path, value_col: str = "valor_bi") -> pd.Series:
    """Aggregate bimestral SICONFI CSV to annual totals (R$ bi)."""
    if not path.exists():
        logger.warning("Missing: %s — component set to 0.", path.name)
        return pd.Series(dtype=float)
    df     = pd.read_csv(path)
    result = {}
    for _, row in df.iterrows():
        year = int(row["ano"])
        val  = float(row[value_col])
        result[year] = result.get(year, 0.0) + val
    return pd.Series(result).sort_index()


def main() -> int:
    uniao   = bim_to_annual(ROOT / "data" / "raw" / "siconfi_rreo_uniao.csv")
    estados = bim_to_annual(ROOT / "data" / "raw" / "siconfi_rreo_estados.csv")
    rpps    = bim_to_annual(ROOT / "data" / "raw" / "siconfi_rpps_bimestral.csv")

    cnt_path = ROOT / "data" / "raw" / "cnt_quarterly.csv"
    if not cnt_path.exists():
        logger.error("Missing cnt_quarterly.csv. Run: python scripts/download_cnt.py")
        return 1
    cnt_q = pd.read_csv(cnt_path)
    cnt_q["data"] = pd.to_datetime(
        cnt_q["periodo"].str.replace(r"(\d{4})Q(\d)", r"\1-Q\2", regex=True)
    )
    cnt_q["ano"] = cnt_q["data"].dt.year
    qcount       = cnt_q.groupby("ano")["cnt_nominal_bi"].count()
    full_years   = qcount[qcount == 4].index
    cnt_annual   = cnt_q.groupby("ano")["cnt_nominal_bi"].sum().loc[full_years]

    components = {
        "salarios_ce_estados": estados,
        "salarios_ce_uniao":   uniao,
        "contrib_imputada":    rpps,
    }

    rows = []
    for componente, serie in components.items():
        common_years = sorted(set(serie.index) & set(cnt_annual.index))
        if not common_years:
            logger.warning("No common years for component '%s'.", componente)
            continue
        for year in common_years:
            amostra = float(serie.loc[year])
            ref     = float(cnt_annual.loc[year])
            pct     = amostra / ref * 100 if ref > 0 else 0.0
            rows.append({
                "ano":                    year,
                "componente":             componente,
                "amostra_R_bi":           round(amostra, 4),
                "referencia_R_bi":        round(ref, 4),
                "representatividade_pct": round(pct, 2),
                "flag_drop":              False,
            })

    df = pd.DataFrame(rows).sort_values(["componente", "ano"]).reset_index(drop=True)

    # Flag drops > 10 pp year-over-year per component
    for comp in df["componente"].unique():
        mask = df["componente"] == comp
        pct  = df.loc[mask, "representatividade_pct"].copy()
        diff = pct.diff()
        for idx in pct.index[diff < -10]:
            df.at[idx, "flag_drop"] = True
            year = df.at[idx, "ano"]
            logger.warning(
                "Component '%s': representativeness dropped >10pp in year %d",
                comp, year
            )

    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    out = OUTPUT_TABLES / "representatividade.csv"
    df.to_csv(out, index=False)
    logger.info("Saved -> %s (%d rows)", out, len(df))

    print("\n  Representatividade da Amostra SICONFI vs. CNT\n")
    print(f"  {'Componente':<30}{'Ano':<8}{'Amostra':>12}{'CNT ref.':>12}{'%':>8}{'Flag':>8}")
    print("  " + "-" * 80)
    for _, row in df.iterrows():
        flag = " WARNING" if row["flag_drop"] else ""
        print(
            f"  {row['componente']:<30}{int(row['ano']):<8}"
            f"{row['amostra_R_bi']:>12.2f}{row['referencia_R_bi']:>12.2f}"
            f"{row['representatividade_pct']:>8.1f}%{flag}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
