"""
Fetch the latest SICONFI RREO bimestre for União + 27 estados + RPPS.

Usage:
    python scripts/fetch_latest_bim.py            # auto-detect latest bimestre for current year
    python scripts/fetch_latest_bim.py --year 2025
    python scripts/fetch_latest_bim.py --bim 3    # specific bimestre
    python scripts/fetch_latest_bim.py --year 2026 --bim 2

Appends new rows to (matching historical CSV schema: ano, bimestre, cod_ibge, uf, valor_bi):
    data/raw/siconfi_rreo_uniao.csv
    data/raw/siconfi_rreo_estados.csv
    data/raw/siconfi_rpps_bimestral.csv

Then rebuilds siconfi_fiscal.csv and componentes_trimestrais.csv.
Run python pipeline.py --nowcast-only afterwards to update estimates.
"""

import argparse
import csv
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT     = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(ROOT))

# Reuse extraction logic from historical downloaders to guarantee consistency.
from scripts.download_siconfi_rreo import (
    fetch_rreo_bimestre, TODOS_ESTADOS, BASE_URL, DELAY,
)
from scripts.download_siconfi_rpps import fetch_rpps_bimestre

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SANITY_LOW  = 0.50   # warn if new value < 50 % of same bimestre last year
SANITY_HIGH = 2.00   # warn if new value > 200 % of same bimestre last year


# ── Sanity check ──────────────────────────────────────────────────────────────

def _last_year_total(csv_path: Path, year: int, bim: int) -> float | None:
    """Return sum of valor_bi for (year-1, bim) from an existing CSV, or None."""
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    prev = df[(df["ano"] == year - 1) & (df["bimestre"] == bim)]
    if prev.empty:
        return None
    return float(prev["valor_bi"].sum())


def _sanity_ok(label: str, csv_path: Path, year: int, bim: int,
               new_value_bi: float) -> bool:
    """
    Compare new_value_bi against same bimestre last year.
    Returns False (and logs a WARNING) if ratio is outside [0.5, 2.0].
    """
    ref = _last_year_total(csv_path, year, bim)
    if ref is None or ref == 0:
        return True   # no prior data to compare against
    ratio = new_value_bi / ref
    if ratio < SANITY_LOW or ratio > SANITY_HIGH:
        logger.warning(
            "SANITY FAIL [%s] year=%d bim=%d: new=%.4f R$bi, "
            "last_year=%.4f R$bi, ratio=%.2f — NOT appending. "
            "Check extraction logic or confirm unusual data.",
            label, year, bim, new_value_bi, ref, ratio,
        )
        return False
    return True


# ── CSV append helper ─────────────────────────────────────────────────────────

def _append_rows(path: Path, new_rows: list[dict], fieldnames: list[str]) -> None:
    """Append rows to CSV; create with header if file doesn't exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        df  = pd.read_csv(path)
        new = pd.DataFrame(new_rows)
        df  = pd.concat([df, new], ignore_index=True)
    else:
        df = pd.DataFrame(new_rows, columns=fieldnames)
    df.to_csv(path, index=False)


# ── Per-source fetchers ───────────────────────────────────────────────────────

def fetch_and_append_uniao(session: requests.Session, year: int, bim: int) -> bool:
    """Fetch União Pessoal+CE for one bimestre and append to siconfi_rreo_uniao.csv."""
    raw = fetch_rreo_bimestre(session, id_ente=1, year=year, bimestre=bim)
    val_bi = round(raw / 1e9, 6)
    logger.info("  União: %.4f R$ bi", val_bi)

    path = DATA_RAW / "siconfi_rreo_uniao.csv"
    if not _sanity_ok("uniao", path, year, bim, val_bi):
        return False

    _append_rows(
        path,
        [{"ano": year, "bimestre": bim, "cod_ibge": 1, "uf": "BR", "valor_bi": val_bi}],
        ["ano", "bimestre", "cod_ibge", "uf", "valor_bi"],
    )
    return True


def fetch_and_append_estados(session: requests.Session, year: int, bim: int) -> bool:
    """Fetch all 27 estados and append to siconfi_rreo_estados.csv."""
    path = DATA_RAW / "siconfi_rreo_estados.csv"

    estado_rows = []
    for uf, cod_ibge in TODOS_ESTADOS.items():
        raw    = fetch_rreo_bimestre(session, id_ente=cod_ibge, year=year, bimestre=bim)
        val_bi = round(raw / 1e9, 6)
        estado_rows.append({
            "ano": year, "bimestre": bim,
            "cod_ibge": cod_ibge, "uf": uf,
            "valor_bi": val_bi,
        })
        time.sleep(DELAY)

    total_bi = sum(r["valor_bi"] for r in estado_rows)
    logger.info("  Estados total: %.4f R$ bi (27 estados)", total_bi)

    if not _sanity_ok("estados", path, year, bim, total_bi):
        return False

    _append_rows(
        path, estado_rows,
        ["ano", "bimestre", "cod_ibge", "uf", "valor_bi"],
    )
    return True


def fetch_and_append_rpps(session: requests.Session, year: int, bim: int) -> bool:
    """Fetch RPPS (Anexo 4, contrib. imputada) and append to siconfi_rpps_bimestral.csv."""
    raw, _items = fetch_rpps_bimestre(session, year=year, bimestre=bim)
    val_bi = round(raw / 1e9, 6)
    logger.info("  RPPS: %.4f R$ bi", val_bi)

    path = DATA_RAW / "siconfi_rpps_bimestral.csv"
    if not _sanity_ok("rpps", path, year, bim, val_bi):
        return False

    _append_rows(
        path,
        [{"ano": year, "bimestre": bim, "cod_ibge": 1, "uf": "BR", "valor_bi": val_bi}],
        ["ano", "bimestre", "cod_ibge", "uf", "valor_bi"],
    )
    return True


# ── Auto-detect latest bimestre ───────────────────────────────────────────────

def detect_latest_bim(session: requests.Session, year: int) -> int | None:
    """Probe descending bimestres to find the latest with União data."""
    for bim in range(6, 0, -1):
        logger.info("Probing year=%d bim=%d ...", year, bim)
        raw = fetch_rreo_bimestre(session, id_ente=1, year=year, bimestre=bim)
        if raw > 0:
            logger.info("Latest available: year=%d bim=%d", year, bim)
            return bim
        time.sleep(DELAY)
    return None


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch latest SICONFI bimestre and append to raw CSVs"
    )
    parser.add_argument("--year", type=int, default=datetime.now().year,
                        help="Fiscal year (default: current year)")
    parser.add_argument("--bim", type=int, choices=range(1, 7), metavar="BIM",
                        help="Bimestre 1-6 (default: auto-detect latest)")
    args = parser.parse_args()

    session = requests.Session()
    year    = args.year
    bim     = args.bim

    if bim is None:
        bim = detect_latest_bim(session, year)
        if bim is None:
            logger.error("No RREO data found for year=%d", year)
            return 1

    logger.info("Fetching year=%d bim=%d", year, bim)

    ok_u = fetch_and_append_uniao(session, year, bim)
    ok_e = fetch_and_append_estados(session, year, bim)
    ok_r = fetch_and_append_rpps(session, year, bim)

    if not (ok_u or ok_e):
        logger.error("Both União and estados failed sanity check — aborting rebuild.")
        return 1

    logger.info("Rebuilding siconfi_fiscal.csv and componentes_trimestrais.csv...")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_siconfi_fiscal.py")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        logger.error("build_siconfi_fiscal.py failed:\n%s", result.stderr)
        return 1

    logger.info("Done. Run: python pipeline.py --nowcast-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
