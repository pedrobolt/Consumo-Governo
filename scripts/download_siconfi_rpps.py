"""
Download SICONFI RREO Anexo 4 – Contribuição Imputada (RPPS) for União Federal.

Usage:
    python scripts/download_siconfi_rpps.py --dump-raw

Options:
    --dump-raw   Save data/raw/rpps_raw_sample.json for manual field inspection.

Outputs:
    data/raw/rpps_raw_sample.json      (first bimestre response, for inspection)
    data/raw/siconfi_rpps_bimestral.csv

Columns: ano, bimestre, cod_ibge, uf, valor_bi
Unit:    R$ bilhões

The "contrib. imputada" is approximated as the pension expenditure of the
Regime Próprio de Previdência Social (RPPS) for federal civil servants.
After running with --dump-raw, inspect rpps_raw_sample.json and update
RPPS_KEYWORDS in scripts/build_siconfi_fiscal.py if a better field is found.
"""

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_RAW.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
YEAR_START = 2015
YEAR_END = 2024
BIMESTRES = range(1, 7)
DELAY = 0.25

UNIAO_ID = 1

# Keywords to find contrib_imputada rows — update after inspecting rpps_raw_sample.json
RPPS_KEYWORDS = [
    "Previdência do Regime Estatutário",
    "Regime Estatut",
]

COLUNA_LIQUIDADAS = "DESPESAS LIQUIDADAS NO BIMESTRE"


def fetch_rpps_bimestre(session: requests.Session, year: int, bimestre: int,
                        retries: int = 2):
    params = {
        "an_exercicio": year,
        "nr_periodo": bimestre,
        "co_tipo_demonstrativo": "RREO",
        "no_co_tipo_demonstrativo": "RREO - Anexo 4",
        "id_ente": UNIAO_ID,
    }
    for attempt in range(retries + 1):
        try:
            r = session.get(BASE_URL, params=params, timeout=30)
            r.raise_for_status()
            items = r.json().get("items", [])
            total = 0.0
            for item in items:
                conta = str(item.get("conta", ""))
                coluna = str(item.get("coluna", ""))
                rotulo = str(item.get("rotulo", ""))
                if (any(kw in conta for kw in RPPS_KEYWORDS)
                        and coluna == COLUNA_LIQUIDADAS
                        and "Exceto" in rotulo):
                    v = item.get("valor")
                    if v is not None:
                        total += float(v)
            return total, items
        except Exception as exc:
            if attempt < retries:
                time.sleep(1.0)
            else:
                logger.debug("RPPS year=%d bim=%d: %s", year, bimestre, exc)
    return 0.0, []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump-raw", action="store_true",
                        help="Save first API response to rpps_raw_sample.json")
    args = parser.parse_args()

    session = requests.Session()
    rows = []
    sample_saved = False

    total_calls = (YEAR_END - YEAR_START + 1) * len(BIMESTRES)
    done = 0

    for year in range(YEAR_START, YEAR_END + 1):
        for bim in BIMESTRES:
            val, raw_items = fetch_rpps_bimestre(session, year, bim)

            if args.dump_raw and not sample_saved and raw_items:
                sample_path = DATA_RAW / "rpps_raw_sample.json"
                with open(sample_path, "w", encoding="utf-8") as f:
                    json.dump(raw_items[:100], f, indent=2, ensure_ascii=False)
                logger.info("Raw sample saved to %s (%d items shown)",
                            sample_path, min(100, len(raw_items)))
                sample_saved = True

            if val > 0:
                rows.append({
                    "ano": year,
                    "bimestre": bim,
                    "cod_ibge": UNIAO_ID,
                    "uf": "BR",
                    "valor_bi": round(val / 1e9, 6),
                })

            done += 1
            if done % 10 == 0:
                logger.info("[RPPS] %d/%d requests done", done, total_calls)
            time.sleep(DELAY)

    out_csv = DATA_RAW / "siconfi_rpps_bimestral.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ano", "bimestre", "cod_ibge", "uf", "valor_bi"])
        w.writeheader()
        w.writerows(rows)

    logger.info("Saved %d rows to %s", len(rows), out_csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
