"""
Build siconfi_fiscal.csv from raw SICONFI downloads.

Reads:
    data/raw/siconfi_rreo_uniao.csv
    data/raw/siconfi_rreo_estados.csv
    data/raw/siconfi_rpps_bimestral.csv

Writes:
    data/raw/siconfi_fiscal.csv
        Columns: periodo, spec, valor_bi
    data/processed/componentes_trimestrais.csv
        Columns: periodo, componente, valor_bi
        Components: salarios_ce_estados, salarios_ce_uniao, contrib_imputada
        (Pre-aggregation indicator decomposition — NOT benchmarked to TRU)

Bimestral to trimestral conversion (Santos et al. 2015):
    Bim 1 → 100% Q1
    Bim 2 → 50% Q1 + 50% Q2
    Bim 3 → 100% Q2
    Bim 4 → 50% Q2 + 50% Q3
    Bim 5 → 100% Q3
    Bim 6 → 50% Q3 + 50% Q4

RPPS_KEYWORDS: after inspecting data/raw/rpps_raw_sample.json,
update to match the `conta` field for contrib_imputada.
"""

import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"

# Update after inspecting rpps_raw_sample.json
RPPS_KEYWORDS = [
    "Previdência do Regime Estatutário",
    "Regime Estatut",
    "RPPS",
]

BIM_TO_TRIM = {
    1: [(1, 1.0)],           # Jan-Feb -> Q1 fully
    2: [(1, 0.5), (2, 0.5)], # Mar-Apr -> half Q1, half Q2
    3: [(2, 1.0)],           # May-Jun -> Q2 fully
    4: [(3, 1.0)],           # Jul-Aug -> Q3 fully
    5: [(3, 0.5), (4, 0.5)], # Sep-Oct -> half Q3, half Q4
    6: [(4, 1.0)],           # Nov-Dec -> Q4 fully (13th salary period)
}


def load_rreo(path: Path, label: str) -> dict:
    if not path.exists():
        logger.warning("Missing: %s -- %s set to 0.", path.name, label)
        return {}

    df = pd.read_csv(path)
    result = defaultdict(float)
    for _, row in df.iterrows():
        year = int(row["ano"])
        bim = int(row["bimestre"])
        val = float(row["valor_bi"])
        for q, w in BIM_TO_TRIM[bim]:
            result[(year, q)] += val * w

    logger.info("Loaded %s: %d rows -> %d quarterly entries", label, len(df), len(result))
    return dict(result)


def build_specs(uniao: dict, estados: dict, rpps: dict) -> list:
    all_periods = set(uniao.keys()) | set(estados.keys()) | set(rpps.keys())
    if not all_periods:
        logger.error("No quarterly data. Check that input CSVs are non-empty.")
        sys.exit(1)

    rows = []
    for (year, q) in sorted(all_periods):
        periodo = f"{year}Q{q}"
        u = uniao.get((year, q), 0.0)
        e = estados.get((year, q), 0.0)
        r = rpps.get((year, q), 0.0)

        specs = {
            # Matches spec naming expected by pipeline.py
            "spec01_uniao_sal_ce":             u,
            "spec03_uniao_estados_sal_ce":      u + e,
            "spec13_uniao_estados_sal_ce_ci":   u + e + r,
            "spec_uniao_sal_ce_ci":             u + r,
            "spec_estados_sal_ce":              e,
            "spec_rpps_ci_uniao":               r,
        }
        for spec_name, val in specs.items():
            rows.append({
                "periodo": periodo,
                "spec": spec_name,
                "valor_bi": round(val, 6),
            })

    return rows


def build_componentes(uniao: dict, estados: dict, rpps: dict) -> list:
    """Decompose quarterly indicator into raw components (not benchmarked to TRU)."""
    all_periods = sorted(set(uniao.keys()) | set(estados.keys()) | set(rpps.keys()))
    rows = []
    for (year, q) in all_periods:
        periodo = f"{year}Q{q}"
        rows.append({"periodo": periodo, "componente": "salarios_ce_estados",
                     "valor_bi": round(estados.get((year, q), 0.0), 6)})
        rows.append({"periodo": periodo, "componente": "salarios_ce_uniao",
                     "valor_bi": round(uniao.get((year, q), 0.0), 6)})
        rows.append({"periodo": periodo, "componente": "contrib_imputada",
                     "valor_bi": round(rpps.get((year, q), 0.0), 6)})
    return rows


def main() -> int:
    uniao = load_rreo(DATA_RAW / "siconfi_rreo_uniao.csv", "Uniao")
    estados = load_rreo(DATA_RAW / "siconfi_rreo_estados.csv", "Estados")
    rpps = load_rreo(DATA_RAW / "siconfi_rpps_bimestral.csv", "RPPS")

    if not uniao and not estados:
        logger.error(
            "Both RREO CSVs missing.\n"
            "Run: python scripts/download_siconfi_rreo.py --entes uniao,estados"
        )
        return 1

    rows = build_specs(uniao, estados, rpps)
    logger.info("Built %d spec-period rows", len(rows))

    out = DATA_RAW / "siconfi_fiscal.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "spec", "valor_bi"])
        w.writeheader()
        w.writerows(rows)
    logger.info("Saved -> %s", out)

    comp_rows = build_componentes(uniao, estados, rpps)
    comp_dir = ROOT / "data" / "processed"
    comp_dir.mkdir(parents=True, exist_ok=True)
    comp_out = comp_dir / "componentes_trimestrais.csv"
    with open(comp_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "componente", "valor_bi"])
        w.writeheader()
        w.writerows(comp_rows)
    logger.info("Saved componentes -> %s (%d rows)", comp_out, len(comp_rows))

    specs = sorted({r["spec"] for r in rows})
    periods = sorted({r["periodo"] for r in rows})
    logger.info("Specs: %s", specs)
    logger.info("Periods: %s to %s (%d quarters)", periods[0], periods[-1], len(periods))
    return 0


if __name__ == "__main__":
    sys.exit(main())
