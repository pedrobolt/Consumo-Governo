"""
Verify data/raw/cnt_quarterly.csv and data/raw/siconfi_fiscal.csv.

Cross-checks CNT values against paper (Santos et al. 2015, Table 2):
    2010Q1 ~ 163.11, 2011Q3 ~ 199.00, 2014Q4 ~ 324.89 (tolerance 5%)

Exit 0 if all checks pass, 1 otherwise.
"""

import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"

PAPER_CHECKS = {
    "2010Q1": 163.11,
    "2011Q3": 199.00,
    "2014Q4": 324.89,
}
TOLERANCE = 0.05


def check_cnt() -> bool:
    path = DATA_RAW / "cnt_quarterly.csv"
    if not path.exists():
        logger.error("MISSING: %s", path)
        return False

    df = pd.read_csv(path)
    if not {"periodo", "cnt_nominal_bi"}.issubset(df.columns):
        logger.error("cnt_quarterly.csv missing required columns")
        return False

    nq = len(df)
    logger.info("cnt_quarterly.csv: %d quarters (%s to %s)",
                nq, df["periodo"].min(), df["periodo"].max())

    cnt_map = dict(zip(df["periodo"], df["cnt_nominal_bi"].astype(float)))
    for periodo, ref in PAPER_CHECKS.items():
        if periodo not in cnt_map:
            logger.info("Paper check %s not in data (pre-2015 expected missing).", periodo)
            continue
        val = cnt_map[periodo]
        dev = abs(val - ref) / ref
        flag = "OK" if dev <= TOLERANCE else "WARN>5%"
        logger.info("CNT %s: %.2f (ref=%.2f dev=%.1f%%) %s",
                    periodo, val, ref, dev * 100, flag)

    return True


def check_fiscal() -> bool:
    path = DATA_RAW / "siconfi_fiscal.csv"
    if not path.exists():
        logger.error("MISSING: %s  -- run: python scripts/build_siconfi_fiscal.py", path)
        return False

    df = pd.read_csv(path)
    if not {"periodo", "spec", "valor_bi"}.issubset(df.columns):
        logger.error("siconfi_fiscal.csv missing required columns")
        return False

    specs = sorted(df["spec"].unique())
    periods = sorted(df["periodo"].unique())
    logger.info("siconfi_fiscal.csv: %d rows, %d specs, %d quarters (%s to %s)",
                len(df), len(specs), len(periods),
                periods[0] if periods else "?",
                periods[-1] if periods else "?")
    logger.info("Specs: %s", specs)

    null_rows = df["valor_bi"].isna().sum()
    if null_rows:
        logger.warning("%d NaN values in valor_bi", null_rows)

    spec13 = df[df["spec"].str.contains("spec13")]
    if len(spec13) > 0:
        low = spec13[spec13["valor_bi"] < 50]
        if len(low):
            logger.warning("spec13 has %d quarters below 50 R$ bi", len(low))
        else:
            logger.info("spec13 values all >= 50 R$ bi -- OK")

    return True


def main() -> int:
    logger.info("=== Data Verification ===")
    ok = check_cnt() and check_fiscal()
    if ok:
        logger.info("=== PASSED -- ready for pipeline.py ===")
        return 0
    logger.error("=== FAILED -- fix errors above ===")
    return 1


if __name__ == "__main__":
    sys.exit(main())
