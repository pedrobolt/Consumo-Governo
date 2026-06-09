"""
Download IBGE CNT quarterly government consumption data.

Source: IBGE FTP - Tab_Compl_CNT.zip (Tabelas Completas das CNT)
Target: data/raw/cnt_quarterly.csv
Format: periodo,cnt_nominal_bi  (e.g., 2010Q1,163.11)

Unit: R$ bilhões correntes (input is R$ milhões ÷ 1000)
"""

import csv
import io
import logging
import re
import sys
import zipfile
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
DATA_RAW.mkdir(parents=True, exist_ok=True)

FTP_URL = ("https://ftp.ibge.gov.br/Contas_Nacionais/"
           "Contas_Nacionais_Trimestrais/Tabelas_Completas/Tab_Compl_CNT.zip")
OUT_CSV = DATA_RAW / "cnt_quarterly.csv"
YEAR_START = 2010
YEAR_END = 2024

QUARTER_MAP = {"I": 1, "II": 2, "III": 3, "IV": 4}


def download_and_parse() -> list:
    logger.info("Downloading %s ...", FTP_URL)
    r = requests.get(FTP_URL, timeout=120, stream=True)
    r.raise_for_status()
    raw = b"".join(r.iter_content(8192))
    logger.info("Downloaded %d bytes", len(raw))

    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas not installed. Run: pip install pandas openpyxl xlrd")
        sys.exit(1)

    zf = zipfile.ZipFile(io.BytesIO(raw))
    xls_name = next(n for n in zf.namelist() if n.endswith(".xls") or n.endswith(".xlsx"))
    xls_bytes = zf.read(xls_name)
    logger.info("Parsing %s ...", xls_name)

    df = pd.read_excel(io.BytesIO(xls_bytes), sheet_name="Valores Correntes", header=None)

    # Find the 'Consumo do Governo' column
    gov_col = None
    for col_idx in range(df.shape[1]):
        for row_idx in range(min(5, df.shape[0])):
            cell = str(df.iloc[row_idx, col_idx])
            if "Consumo do Governo" in cell or "consumo do governo" in cell.lower():
                gov_col = col_idx
                break
        if gov_col is not None:
            break

    if gov_col is None:
        logger.error("Could not find 'Consumo do Governo' column in sheet 'Valores Correntes'.")
        sys.exit(1)

    logger.info("'Consumo do Governo' found at column %d", gov_col)

    rows = []
    for i in range(4, df.shape[0]):
        period_raw = str(df.iloc[i, 0])
        val = df.iloc[i, gov_col]

        m = re.match(r"^(\d{4})[.]([IVX]+)$", period_raw.strip())
        if not m:
            continue

        year = int(m.group(1))
        if year < YEAR_START or year > YEAR_END:
            continue

        q = QUARTER_MAP.get(m.group(2))
        if q is None:
            continue

        try:
            v = float(val)
        except (TypeError, ValueError):
            continue

        # Input is R$ milhões → convert to R$ bilhões
        rows.append({"periodo": f"{year}Q{q}", "cnt_nominal_bi": round(v / 1000, 4)})

    rows.sort(key=lambda x: x["periodo"])
    return rows


def main():
    rows = download_and_parse()
    logger.info("Extracted %d quarters (%s to %s)",
                len(rows),
                rows[0]["periodo"] if rows else "?",
                rows[-1]["periodo"] if rows else "?")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "cnt_nominal_bi"])
        w.writeheader()
        w.writerows(rows)

    logger.info("Saved to %s", OUT_CSV)
    return 0


if __name__ == "__main__":
    sys.exit(main())
