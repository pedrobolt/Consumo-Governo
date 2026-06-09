"""
Download SICONFI RREO Anexo 1 – Pessoal e Encargos Sociais.

Usage:
    python scripts/download_siconfi_rreo.py --entes uniao,estados

Outputs:
    data/raw/siconfi_rreo_uniao.csv   (if uniao requested)
    data/raw/siconfi_rreo_estados.csv (if estados requested)

Columns: ano, bimestre, cod_ibge, uf, valor_bi
Unit:    R$ bilhões

Coverage: 2015-2024 (SICONFI holds data from 2015 onward).
~2,430 requests for estados (~10 min with 0.25s delay).
"""

import argparse
import csv
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
YEAR_START = 2015    # SICONFI data starts here
YEAR_END = 2025
BIMESTRES = range(1, 7)
DELAY = 0.25         # seconds between requests

TODOS_ESTADOS = {
    "AC": 12, "AL": 27, "AM": 13, "AP": 16, "BA": 29,
    "CE": 23, "DF": 53, "ES": 32, "GO": 52, "MA": 21,
    "MG": 31, "MS": 50, "MT": 51, "PA": 15, "PB": 25,
    "PE": 26, "PI": 22, "PR": 41, "RJ": 33, "RN": 24,
    "RO": 11, "RR": 14, "RS": 43, "SC": 42, "SE": 28,
    "SP": 35, "TO": 17,
}

UNIAO = {"BR": 1}

CONTA_PESSOAL = "PESSOAL E ENCARGOS SOCIAIS"
COD_CONTA_PRINCIPAL = "PessoalEEncargosSociais"
COLUNA_LIQUIDADAS = "DESPESAS LIQUIDADAS NO BIMESTRE"
# Pre-2018 União uses a different column name. The old format has two "No Bimestre"
# rows per account: the first is empenhado, the second (followed by "Ate o Bimestre (h)")
# is liquidado. We identify it by looking at the successor row.
COLUNA_LIQUIDADAS_OLD = "No Bimestre"
COLUNA_LIQUIDADAS_OLD_NEXT = "Bimestre (h)"


def fetch_rreo_bimestre(session: requests.Session, id_ente: int,
                        year: int, bimestre: int, retries: int = 2) -> float:
    params = {
        "an_exercicio": year,
        "nr_periodo": bimestre,
        "co_tipo_demonstrativo": "RREO",
        "no_co_tipo_demonstrativo": "RREO - Anexo 1",
        "id_ente": id_ente,
    }
    for attempt in range(retries + 1):
        try:
            r = session.get(BASE_URL, params=params, timeout=30)
            r.raise_for_status()
            items = r.json().get("items", [])
            total = 0.0
            for i, item in enumerate(items):
                if (item.get("conta") == CONTA_PESSOAL
                        and item.get("cod_conta") == COD_CONTA_PRINCIPAL):
                    col = item.get("coluna", "")
                    v = item.get("valor")
                    if v is None:
                        continue
                    if col == COLUNA_LIQUIDADAS:
                        total += float(v)
                    elif col == COLUNA_LIQUIDADAS_OLD:
                        # Old format: only take the "No Bimestre" that is immediately
                        # followed by "Ate o Bimestre (h)" (the liquidado pair).
                        next_col = items[i + 1].get("coluna", "") if i + 1 < len(items) else ""
                        if COLUNA_LIQUIDADAS_OLD_NEXT in next_col:
                            total += float(v)
            return total
        except Exception as exc:
            if attempt < retries:
                time.sleep(1.0)
            else:
                logger.debug("ente=%s year=%d bim=%d: %s", id_ente, year, bimestre, exc)
    return 0.0


def collect(entes: dict, label: str) -> list:
    session = requests.Session()
    rows = []
    total_calls = len(entes) * (YEAR_END - YEAR_START + 1) * len(BIMESTRES)
    done = 0

    for uf, cod_ibge in entes.items():
        for year in range(YEAR_START, YEAR_END + 1):
            for bim in BIMESTRES:
                val = fetch_rreo_bimestre(session, cod_ibge, year, bim)
                if val > 0:
                    rows.append({
                        "ano": year,
                        "bimestre": bim,
                        "cod_ibge": cod_ibge,
                        "uf": uf,
                        "valor_bi": round(val / 1e9, 6),
                    })
                done += 1
                if done % 50 == 0:
                    logger.info("[%s] %d/%d requests done", label, done, total_calls)
                time.sleep(DELAY)

    logger.info("[%s] Done. %d rows collected.", label, len(rows))
    return rows


def save(rows: list, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ano", "bimestre", "cod_ibge", "uf", "valor_bi"])
        w.writeheader()
        w.writerows(rows)
    logger.info("Saved %d rows to %s", len(rows), path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entes", default="estados",
                        help="Comma-separated list of: uniao, estados")
    parser.add_argument("--year-start", type=int, default=YEAR_START)
    parser.add_argument("--year-end", type=int, default=YEAR_END)
    args = parser.parse_args()

    requested = {e.strip().lower() for e in args.entes.split(",")}

    if "uniao" in requested:
        rows = collect(UNIAO, "uniao")
        save(rows, DATA_RAW / "siconfi_rreo_uniao.csv")

    if "estados" in requested:
        rows = collect(TODOS_ESTADOS, "estados")
        save(rows, DATA_RAW / "siconfi_rreo_estados.csv")

    if not (requested & {"uniao", "estados"}):
        logger.error("Unknown --entes value. Use: uniao, estados")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
