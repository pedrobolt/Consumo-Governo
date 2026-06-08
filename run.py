#!/usr/bin/env python3
"""
Ponto de entrada do projeto Consumo do Governo Nominal Trimestral.

Uso:
  python run.py               # Pipeline completo (2010-2024)
  python run.py --test        # Teste rápido (2010-2014, poucas specs)
  python run.py --year-start 2010 --year-end 2024
  python run.py --no-loop     # Sem loop de otimização
"""

import argparse
import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipeline import run_pipeline
from config import YEAR_START, YEAR_END, MAX_CYCLES
import config as cfg


def parse_args():
    parser = argparse.ArgumentParser(
        description="Consumo do Governo Nominal Trimestral – Pipeline completo")
    parser.add_argument("--year-start", type=int, default=YEAR_START,
                        help=f"Ano inicial (default: {YEAR_START})")
    parser.add_argument("--year-end", type=int, default=YEAR_END,
                        help=f"Ano final (default: {YEAR_END})")
    parser.add_argument("--test", action="store_true",
                        help="Modo teste: 2010-2014, menos iterações")
    parser.add_argument("--no-loop", action="store_true",
                        help="Desabilitar loop de otimização")
    parser.add_argument("--quiet", action="store_true",
                        help="Menos verbosidade")
    return parser.parse_args()


def main():
    args = parse_args()

    # Configurar logging
    level = logging.WARNING if args.quiet else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    # Modo teste
    if args.test:
        args.year_start = 2010
        args.year_end = 2014
        cfg.MAX_CYCLES = 5
        print(">>> MODO TESTE: 2010-2014, 5 ciclos máx.\n")

    if args.no_loop:
        cfg.MAX_CYCLES = 1

    # Executar pipeline
    results = run_pipeline(
        year_start=args.year_start,
        year_end=args.year_end,
        verbose=not args.quiet,
    )

    # Resumo final
    metrics = results["metrics"]
    if not metrics.empty:
        print("\n" + "=" * 60)
        print("RESULTADO FINAL")
        print("=" * 60)
        best = metrics.iloc[0]
        print(f"  Melhor modelo:  {best['model']}")
        print(f"  RMSE:           {best.get('RMSE', 'N/A'):.4f} R$ bi")
        print(f"  MAPE:           {best.get('MAPE', 'N/A'):.2f}%")
        print(f"  Correlação:     {best.get('Corr', 'N/A'):.4f}")
        print(f"  Theil U1:       {best.get('TheilU1', 'N/A'):.4f}")
        print()
        print("  Top 5 modelos por RMSE:")
        for i, (_, row) in enumerate(metrics.head(5).iterrows()):
            print(f"  {i+1}. {row['model']:<50} RMSE={row.get('RMSE', 0):.4f}  "
                  f"MAPE={row.get('MAPE', 0):.2f}%")
        print()

        # Verificar critérios de sucesso
        mape_ok = best.get("MAPE", 100) < cfg.TARGET_MAPE
        corr_ok = best.get("Corr", 0) > cfg.TARGET_CORRELATION
        print(f"  MAPE < {cfg.TARGET_MAPE}%:  {'✓ SIM' if mape_ok else '✗ NÃO'}")
        print(f"  Corr > {cfg.TARGET_CORRELATION}: {'✓ SIM' if corr_ok else '✗ NÃO'}")

    print(f"\n  Outputs em: {Path('output').resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
