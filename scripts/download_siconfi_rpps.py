#!/usr/bin/env python3
"""
Download SICONFI RREO Anexo 4 — Demonstrativo das Receitas e Despesas Previdenciárias.

Captura as Contribuições Imputadas do Regime Próprio de Previdência Social (RPPS)
da União Federal — componente chave da Série 13 do paper.

Saída: data/raw/siconfi_rpps_bimestral.csv

Nota metodológica:
  A contribuição imputada (CI_Imp) é o custo atuarial que o empregador público
  deveria pagar ao RPPS para cobrir benefícios sem contrapartida de contribuições
  efetivas. No papel, ela representa ~12% do indicador com representatividade
  de quase 100% (Tabela 3 do paper).

Volume: 6 bimestres × 15 anos = 90 requisições (<1 min)

Uso:
    python scripts/download_siconfi_rpps.py
    python scripts/download_siconfi_rpps.py --year-start 2010 --year-end 2024
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import List, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "raw" / "siconfi_rpps_bimestral.csv"

SICONFI_BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"

# União Federal no SICONFI
UNIAO_ID_ENTE = 1

SLEEP = 0.3


def fetch_anexo4(
    session: requests.Session,
    year: int,
    bimestre: int,
) -> Optional[List[dict]]:
    params = {
        "an_exercicio": year,
        "nr_periodo": bimestre,
        "co_tipo_demonstrativo": "RREO",
        "no_co_tipo_demonstrativo": "RREO - Anexo 4",
        "id_ente": UNIAO_ID_ENTE,
    }
    try:
        r = session.get(SICONFI_BASE, params=params, timeout=30)
        if r.status_code == 404:
            return []
        if r.status_code == 429:
            print("  Rate limited — sleeping 10s...")
            time.sleep(10)
            r = session.get(SICONFI_BASE, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("items", [])
    except requests.exceptions.Timeout:
        print(f"  Timeout {year}/bim{bimestre}")
        return None
    except Exception as exc:
        print(f"  Error {year}/bim{bimestre}: {exc}")
        return None


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--year-start", type=int, default=2010)
    p.add_argument("--year-end", type=int, default=2024)
    p.add_argument("--out", default=str(OUT_FILE))
    p.add_argument("--dump-raw", action="store_true",
                   help="Also dump raw JSON to data/raw/rpps_raw_sample.json (first bimestre only)")
    return p.parse_args()


def main():
    args = parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    total = 6 * (args.year_end - args.year_start + 1)
    print(f"SICONFI RREO Anexo 4 — RPPS — União Federal (id_ente={UNIAO_ID_ENTE})")
    print(f"Period: {args.year_start}–{args.year_end}  |  {total} requests")
    print(f"Output: {out}\n")

    session = requests.Session()
    session.headers["Accept"] = "application/json"

    all_rows = []
    first_raw = None

    for year in range(args.year_start, args.year_end + 1):
        for bimestre in range(1, 7):
            items = fetch_anexo4(session, year, bimestre)
            time.sleep(SLEEP)

            if items is None:
                print(f"  {year}/bim{bimestre}: request failed")
                continue

            if first_raw is None and items:
                first_raw = items

            for item in items:
                # Store all fields so the user can identify the right one
                # for contrib_imputada after inspection
                all_rows.append({
                    "ano": year,
                    "bimestre": bimestre,
                    "id_ente": UNIAO_ID_ENTE,
                    "co_conta": item.get("co_conta", ""),
                    "ds_conta": item.get("ds_conta", ""),
                    "co_coluna": item.get("co_coluna", ""),
                    "ds_coluna": item.get("ds_coluna", ""),
                    "vl_resultado": item.get("vl_resultado", ""),
                })

            n = len(items)
            print(f"  {year}/bim{bimestre}: {n} items")

    # Save all rows
    if all_rows:
        fieldnames = ["ano", "bimestre", "id_ente", "co_conta", "ds_conta",
                      "co_coluna", "ds_coluna", "vl_resultado"]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)
        print(f"\nSaved {len(all_rows)} rows to {out}")
    else:
        print("\nNo data returned. Possible causes:")
        print("  - id_ente=1 may not be the correct code for União in SICONFI")
        print("  - Try id_ente=100 or check SICONFI portal for the correct code")
        print("  - Pre-2015 data may not be available via this endpoint (use SISTN)")

    # Dump raw sample for inspection
    if args.dump_raw and first_raw:
        raw_path = ROOT / "data" / "raw" / "rpps_raw_sample.json"
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(first_raw[:10], f, indent=2, ensure_ascii=False)
        print(f"Raw sample saved to {raw_path} — inspect to identify contrib_imputada field")

    # Instructions for next step
    print("""
Next step: inspect the CSV to find the contrib_imputada rows.
  Common account codes for contrib_imputada RPPS:
    - Linhas com "CONTRIBUIÇÕES IMPUTADAS" ou "PATRONAL" em ds_conta
    - co_conta beginning with '1.1' or '1.3' depending on the year

  Once identified, filter in build_siconfi_fiscal.py using ds_conta or co_conta.
""")


if __name__ == "__main__":
    main()
