#!/usr/bin/env python3
"""
Download SICONFI RREO Anexo 1 — Despesas Liquidadas GND 1 (Pessoal e Encargos).

Cobre: União Federal + 27 Estados + (opcionalmente) Municípios.
Saída: data/raw/siconfi_rreo_bimestral.csv

Nota de cobertura:
  - GND 1 no Anexo 1 = Pessoal e Encargos Sociais (salários + contrib. efetivas
    + contrib. imputadas dos estados).
  - Para o paper, somente União tem a separação entre contrib. efetivas e
    contrib. imputadas (RPPS, via Anexo 4 separado). Use download_siconfi_rpps.py
    para Anexo 4.
  - Estados e municípios: GND 1 total usado como proxy de Sal+CE.

Volume de requisições:
  Estados: 27 × 6 bimestres × 15 anos = 2.430 req (~10 min a 0.25s/req)
  União: 1 × 6 × 15 = 90 req
  Municípios: >5.500 × 6 × 15 = >495.000 req (muito lento — usar --entes estados)

Uso:
    python scripts/download_siconfi_rreo.py --entes estados
    python scripts/download_siconfi_rreo.py --entes uniao,estados
    python scripts/download_siconfi_rreo.py --entes uniao,estados,municipios  # lento!
    python scripts/download_siconfi_rreo.py --year-start 2015 --year-end 2024
"""

import argparse
import csv
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT_FILE = ROOT / "data" / "raw" / "siconfi_rreo_bimestral.csv"

SICONFI_BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"

# id_ente codes (IBGE codes)
UNIAO = {"UF": "BR", "id_ente": 1}

ESTADOS: Dict[str, int] = {
    "AC": 12, "AL": 27, "AM": 13, "AP": 16, "BA": 29,
    "CE": 23, "DF": 53, "ES": 32, "GO": 52, "MA": 21,
    "MG": 31, "MS": 50, "MT": 51, "PA": 15, "PB": 25,
    "PE": 26, "PI": 22, "PR": 41, "RJ": 33, "RN": 24,
    "RO": 11, "RR": 14, "RS": 43, "SC": 42, "SE": 28,
    "SP": 35, "TO": 17,
}

# Full list of municipality IBGE codes (7-digit) — placeholder, replace with full list
# Download the full list from: https://servicodados.ibge.gov.br/api/v1/localidades/municipios
MUNICIPIOS_SAMPLE: Dict[str, int] = {
    # Capital cities only — expand to all ~5.570 municipalities as needed
    "Belém":              1501402,
    "Belo Horizonte":     3106200,
    "Campinas":           3509502,
    "Campo Grande":       5002704,
    "Curitiba":           4106902,
    "Fortaleza":          2304400,
    "Goiânia":            5208707,
    "Manaus":             1302603,
    "Porto Alegre":       4314902,
    "Recife":             2611606,
    "Rio de Janeiro":     3304557,
    "Salvador":           2927408,
    "São Paulo":          3550308,
}

SLEEP = 0.25  # seconds between requests — respect SICONFI rate limits


def fetch_rreo_anexo1(
    session: requests.Session,
    id_ente: int,
    year: int,
    bimestre: int,
    timeout: int = 30,
) -> Optional[List[dict]]:
    params = {
        "an_exercicio": year,
        "nr_periodo": bimestre,
        "co_tipo_demonstrativo": "RREO",
        "no_co_tipo_demonstrativo": "RREO - Anexo 1",
        "id_ente": id_ente,
    }
    try:
        r = session.get(SICONFI_BASE, params=params, timeout=timeout)
        if r.status_code == 404:
            return []
        if r.status_code == 429:
            print("  Rate limited — sleeping 5s...")
            time.sleep(5)
            r = session.get(SICONFI_BASE, params=params, timeout=timeout)
        r.raise_for_status()
        return r.json().get("items", [])
    except requests.exceptions.Timeout:
        return None
    except Exception as exc:
        print(f"  Error ente={id_ente} {year}/bim{bimestre}: {exc}")
        return None


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--entes", default="estados",
                   help="Comma-separated: uniao, estados, municipios (default: estados)")
    p.add_argument("--year-start", type=int, default=2010)
    p.add_argument("--year-end", type=int, default=2024)
    p.add_argument("--out", default=str(OUT_FILE))
    p.add_argument("--sleep", type=float, default=SLEEP)
    p.add_argument("--resume", action="store_true",
                   help="Skip already-downloaded (id_ente, year, bimestre) combinations")
    return p.parse_args()


def build_ente_list(entes_arg: str) -> List[Dict]:
    entes = []
    for name in entes_arg.split(","):
        name = name.strip().lower()
        if name == "uniao":
            entes.append({"tier": "uniao", "uf": "BR", "id_ente": 1})
        elif name == "estados":
            for uf, code in ESTADOS.items():
                entes.append({"tier": "estado", "uf": uf, "id_ente": code})
        elif name == "municipios":
            for mun, code in MUNICIPIOS_SAMPLE.items():
                entes.append({"tier": "municipio", "uf": mun, "id_ente": code})
        else:
            print(f"WARNING: unknown ente '{name}' — skipped")
    return entes


def main():
    args = parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    ente_list = build_ente_list(args.entes)
    total = len(ente_list) * 6 * (args.year_end - args.year_start + 1)
    est_min = total * args.sleep / 60

    print(f"SICONFI RREO Anexo 1 — GND 1 (Pessoal e Encargos)")
    print(f"Entes: {args.entes}  |  {len(ente_list)} entities")
    print(f"Period: {args.year_start}–{args.year_end}  |  {total} requests (~{est_min:.0f} min)")
    print(f"Output: {out}\n")

    # Load already-downloaded combos if resuming
    seen: set = set()
    existing_rows: List[dict] = []
    if args.resume and out.exists():
        with open(out, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_rows.append(row)
                key = (int(row["id_ente"]), int(row["ano"]), int(row["bimestre"]))
                seen.add(key)
        print(f"Resume: {len(existing_rows)} existing records, {len(seen)} combos already done.\n")

    rows = list(existing_rows)
    errors: List[tuple] = []
    done = 0
    session = requests.Session()
    session.headers["Accept"] = "application/json"

    fieldnames = ["ano", "bimestre", "id_ente", "uf", "tier", "cd_grupo",
                  "ds_conta", "vl_liquidado_bi"]

    for ente in ente_list:
        for year in range(args.year_start, args.year_end + 1):
            for bimestre in range(1, 7):
                key = (ente["id_ente"], year, bimestre)
                if key in seen:
                    done += 1
                    continue

                items = fetch_rreo_anexo1(session, ente["id_ente"], year, bimestre)
                done += 1
                time.sleep(args.sleep)

                if items is None:
                    errors.append(key)
                elif items:
                    for item in items:
                        gnd = str(item.get("cd_grupo", "")).strip()
                        if gnd not in ("1", "3"):
                            continue
                        vl_raw = item.get("vl_despesa_liquidada", 0)
                        vl = float(vl_raw) if vl_raw is not None else 0.0
                        rows.append({
                            "ano": year,
                            "bimestre": bimestre,
                            "id_ente": ente["id_ente"],
                            "uf": ente["uf"],
                            "tier": ente["tier"],
                            "cd_grupo": gnd,
                            "ds_conta": item.get("ds_conta", ""),
                            "vl_liquidado_bi": round(vl / 1e9, 8),
                        })

                if done % 50 == 0:
                    pct = 100 * done / total
                    print(f"  {done}/{total} ({pct:.0f}%) — {len(rows)} records — "
                          f"{len(errors)} errors")

    print(f"\nFinal: {len(rows)} records, {len(errors)} errors")
    if errors:
        print(f"  Error sample (up to 10): {errors[:10]}")

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"Saved to {out}")

    # Quick sanity check
    by_year: Dict[int, float] = {}
    for r in rows:
        if r["cd_grupo"] == "1":
            y = int(r["ano"])
            by_year[y] = by_year.get(y, 0.0) + float(r["vl_liquidado_bi"])

    if by_year:
        print("\nAnnual GND-1 totals (all entes combined):")
        for y in sorted(by_year)[-6:]:
            print(f"  {y}: R$ {by_year[y]:.2f} bi")


if __name__ == "__main__":
    main()
