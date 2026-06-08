#!/usr/bin/env python3
"""
Ponto de entrada do projeto Consumo do Governo Nominal Trimestral.

Requer arquivos de dados reais em data/raw/ — ver DATA_ACQUISITION.md.

Uso:
  python run.py
  python run.py --cnt-csv data/raw/cnt_quarterly.csv --fiscal-csv data/raw/siconfi_fiscal.csv
  python run.py --quiet
"""

import argparse
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import run_pipeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="Consumo do Governo Nominal Trimestral — Pipeline completo")
    parser.add_argument("--cnt-csv", default="data/raw/cnt_quarterly.csv",
                        help="CSV com série CNT trimestral (padrão: data/raw/cnt_quarterly.csv)")
    parser.add_argument("--fiscal-csv", default="data/raw/siconfi_fiscal.csv",
                        help="CSV com indicadores fiscais (padrão: data/raw/siconfi_fiscal.csv)")
    parser.add_argument("--quiet", action="store_true", help="Menos verbosidade")
    return parser.parse_args()


def main():
    args = parse_args()

    level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    run_pipeline(cnt_csv=args.cnt_csv, fiscal_csv=args.fiscal_csv)
    print(f"\n  Outputs em: {Path('output').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
