#!/usr/bin/env python3
"""
Download CNT trimestral do IBGE SIDRA.

Fonte: IBGE SIDRA, Tabela 7321, Variável 11707
Conceito: Consumo Final das Administrações Públicas (R$ milhões correntes)
Saída: data/raw/cnt_quarterly.csv

Uso:
    python scripts/download_cnt.py
    python scripts/download_cnt.py --year-start 2010 --year-end 2024
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "raw" / "cnt_quarterly.csv"

IBGE_API = "https://servicodados.ibge.gov.br/api/v3"
TABLE_ID = 7321
VAR_ID = 11707

# Paper values for verification (Santos et al. 2015, Tabela 2)
PAPER_VALUES = {
    "2010Q1": 163.11, "2010Q2": 172.80, "2010Q3": 180.25, "2010Q4": 222.81,
    "2011Q1": 177.58, "2011Q2": 198.67, "2011Q3": 199.00, "2011Q4": 242.12,
    "2012Q1": 198.33, "2012Q2": 220.36, "2012Q3": 220.14, "2012Q4": 270.78,
    "2013Q1": 217.08, "2013Q2": 248.11, "2013Q3": 244.31, "2013Q4": 300.85,
    "2014Q1": 244.40, "2014Q2": 271.49, "2014Q3": 274.12, "2014Q4": 324.89,
}


def build_url(year_start: int, year_end: int) -> str:
    periods = []
    for y in range(year_start, year_end + 1):
        for q in range(1, 5):
            periods.append(f"{y}0{q}")
    period_str = "|".join(periods)
    return (
        f"{IBGE_API}/agregados/{TABLE_ID}/periodos/{period_str}"
        f"/variaveis/{VAR_ID}?localidades=N1[all]"
    )


def fetch_with_retry(url: str, max_attempts: int = 4) -> dict:
    for attempt in range(max_attempts):
        try:
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            wait = 2 ** attempt
            if attempt < max_attempts - 1:
                print(f"  Attempt {attempt + 1} failed: {exc}. Retrying in {wait}s...")
                time.sleep(wait)
            else:
                sys.exit(f"ERROR: All {max_attempts} attempts failed. Last error: {exc}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--year-start", type=int, default=2010)
    p.add_argument("--year-end", type=int, default=2024)
    p.add_argument("--out", default=str(OUT_FILE))
    return p.parse_args()


def main():
    args = parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    url = build_url(args.year_start, args.year_end)
    print(f"IBGE SIDRA T{TABLE_ID} V{VAR_ID} — {args.year_start}–{args.year_end}")
    print(f"URL: {url[:120]}...")

    data = fetch_with_retry(url)

    try:
        serie = data[0]["resultados"][0]["series"][0]["serie"]
    except (KeyError, IndexError) as e:
        sys.exit(f"Unexpected API response structure: {e}\nResponse: {str(data)[:300]}")

    rows = []
    for period_code, value in sorted(serie.items()):
        if value in ("-", "...", "", None):
            continue
        year = int(period_code[:4])
        quarter = int(period_code[4])
        if args.year_start <= year <= args.year_end:
            rows.append({
                "periodo": f"{year}Q{quarter}",
                "cnt_nominal_bi": round(float(value) / 1000, 4),
            })

    if not rows:
        sys.exit("No data returned. Check API response above.")

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "cnt_nominal_bi"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nSaved {len(rows)} quarters to {out}")

    # Verify against paper values
    print("\nVerification vs. Santos et al. (2015), Table 2:")
    got = {r["periodo"]: r["cnt_nominal_bi"] for r in rows}
    max_diff = 0.0
    ok_count = 0
    for period, expected in sorted(PAPER_VALUES.items()):
        actual = got.get(period)
        if actual is None:
            print(f"  {period}: MISSING")
            continue
        diff = abs(actual - expected)
        max_diff = max(max_diff, diff)
        status = "OK" if diff < 2.0 else "WARNING"
        if diff < 2.0:
            ok_count += 1
        print(f"  {period}: got {actual:.2f}  expected {expected:.2f}  diff {diff:.2f}  [{status}]")

    print(f"\n  {ok_count}/{len(PAPER_VALUES)} within 2 R$ bi of paper values")
    if max_diff > 5.0:
        print(f"  WARNING: max diff = {max_diff:.2f} R$ bi — check IBGE revision or table/variable IDs")


if __name__ == "__main__":
    main()
