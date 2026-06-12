"""
Fetch latest SICONFI RREO bimestre for all entes (União + 27 estados + RPPS).

Usage:
    python scripts/fetch_latest_bim.py            # defaults to current year
    python scripts/fetch_latest_bim.py --year 2025
    python scripts/fetch_latest_bim.py --bim 3    # specific bimestre
    python scripts/fetch_latest_bim.py --year 2026 --bim 2

Appends new bimestre rows to:
    data/raw/siconfi_rreo_uniao.csv
    data/raw/siconfi_rreo_estados.csv
    data/raw/siconfi_rpps_bimestral.csv

Then rebuilds siconfi_fiscal.csv and componentes_trimestrais.csv.
"""

import argparse
import logging
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT     = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(ROOT))
from config import TODOS_ESTADOS, ELEMENTOS_SALARIOS, ELEMENTOS_CONTRIB_EFETIVAS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

SICONFI_URL   = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
TIMEOUT       = 30
SLEEP_BETWEEN = 0.4   # seconds between requests to avoid rate limiting


def _fetch_rreo(id_ente: int, year: int, bim: int,
                annex: str = "RREO - Anexo 1") -> list:
    params = dict(
        an_exercicio=year,
        nr_periodo=bim,
        co_tipo_demonstrativo="RREO",
        no_co_tipo_demonstrativo=annex,
        id_ente=id_ente,
    )
    try:
        r = requests.get(SICONFI_URL, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        logger.debug("  id_ente=%d bim=%d: %s", id_ente, bim, exc)
        return []


def _sum_elementos(items: list, elementos: list) -> float:
    total = 0.0
    for row in items:
        cod = str(row.get("cd_elemento_despesa", "")).strip()
        if cod in elementos:
            val = row.get("vl_despesa_liquidada") or row.get("vl_empenhado") or 0.0
            total += float(val)
    return total / 1e9   # R$ billions


def fetch_uniao(year: int, bim: int) -> float:
    items = _fetch_rreo(id_ente=1, year=year, bim=bim)
    return _sum_elementos(items, ELEMENTOS_SALARIOS + ELEMENTOS_CONTRIB_EFETIVAS)


def fetch_estados(year: int, bim: int) -> dict:
    results = {}
    for uf, id_str in TODOS_ESTADOS.items():
        items      = _fetch_rreo(id_ente=int(id_str), year=year, bim=bim)
        results[uf] = _sum_elementos(items, ELEMENTOS_SALARIOS + ELEMENTOS_CONTRIB_EFETIVAS)
        time.sleep(SLEEP_BETWEEN)
    return results


def fetch_rpps(year: int, bim: int) -> float:
    items = _fetch_rreo(id_ente=1, year=year, bim=bim, annex="RREO - Anexo 4")
    return sum(
        float(row.get("vl_despesa", 0) or 0)
        for row in items
        if any(kw in str(row.get("conta_contabil", ""))
               for kw in ("Estatut", "RPPS", "Previdência do Regime"))
    ) / 1e9


def _append_row(path: Path, new_row: dict) -> None:
    cols = list(new_row.keys())
    if path.exists():
        df  = pd.read_csv(path)
        df  = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    else:
        df = pd.DataFrame([new_row])
        path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch latest SICONFI bimestre")
    parser.add_argument("--year", type=int, default=datetime.now().year,
                        help="Fiscal year (default: current year)")
    parser.add_argument("--bim", type=int, choices=range(1, 7), metavar="BIM",
                        help="Bimestre 1-6 (default: auto-detect latest)")
    args = parser.parse_args()

    year = args.year
    bim  = args.bim

    if bim is None:
        for probe_bim in range(6, 0, -1):
            logger.info("Probing year=%d bim=%d ...", year, probe_bim)
            val = fetch_uniao(year, probe_bim)
            if val > 0:
                bim = probe_bim
                logger.info("Latest available: year=%d bim=%d", year, bim)
                break
        if bim is None:
            logger.error("No RREO data found for year=%d", year)
            return 1

    logger.info("Fetching year=%d bim=%d", year, bim)

    logger.info("Fetching União...")
    val_u = fetch_uniao(year, bim)
    _append_row(DATA_RAW / "siconfi_rreo_uniao.csv",
                {"ano": year, "bimestre": bim, "valor_bi": round(val_u, 6)})
    logger.info("  União: %.4f R$ bi", val_u)

    logger.info("Fetching 27 estados (~1 min)...")
    estados_vals = fetch_estados(year, bim)
    path_e = DATA_RAW / "siconfi_rreo_estados.csv"
    for uf, val in estados_vals.items():
        _append_row(path_e, {"ano": year, "bimestre": bim, "uf": uf,
                              "valor_bi": round(val, 6)})
    logger.info("  Estados: %.4f R$ bi (27)", sum(estados_vals.values()))

    logger.info("Fetching RPPS (Anexo 4)...")
    val_r = fetch_rpps(year, bim)
    _append_row(DATA_RAW / "siconfi_rpps_bimestral.csv",
                {"ano": year, "bimestre": bim, "valor_bi": round(val_r, 6)})
    logger.info("  RPPS: %.4f R$ bi", val_r)

    logger.info("Rebuilding siconfi_fiscal.csv and componentes_trimestrais.csv...")
    result = subprocess.run(
        ["python", str(ROOT / "scripts" / "build_siconfi_fiscal.py")],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        logger.error("build_siconfi_fiscal.py failed:\n%s", result.stderr)
        return 1

    logger.info("Done. Run: python pipeline.py --nowcast-only")
    return 0


if __name__ == "__main__":
    sys.exit(main())
