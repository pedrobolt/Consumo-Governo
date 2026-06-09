#!/usr/bin/env python3
"""
Constrói data/raw/siconfi_fiscal.csv a partir dos arquivos brutos baixados.

Lê:
    data/raw/siconfi_rreo_bimestral.csv    (GND 1 e GND 3, por ente)
    data/raw/siconfi_rpps_bimestral.csv    (contribuições imputadas RPPS, União)

Produz:
    data/raw/siconfi_fiscal.csv            (formato: periodo,spec,valor_bi)

O CSV de saída é o input direto de pipeline.py::load_fiscal_indicators().

Conversão bimestral → trimestral (Santos et al. 2015):
  Bim 1 (jan-fev) → 100% Q1
  Bim 2 (mar-abr) → 50% Q1 + 50% Q2
  Bim 3 (mai-jun) → 100% Q2
  Bim 4 (jul-ago) → 100% Q3
  Bim 5 (set-out) → 50% Q3 + 50% Q4
  Bim 6 (nov-dez) → 100% Q4

Especificações produzidas (ver SPEC_CONFIGS em src/processing/indicator.py):
  serie1  : União GND 1
  serie3  : União + Estados GND 1
  serie5  : União + Estados + Municípios GND 1
  serie13 : União + Estados + Municípios GND 1 + RPPS (contrib_imputada)
  moderna_a: idem série 13 (com todos os estados disponíveis)

  Nota: séries com consumo_interm (serie7-12, moderna_b/c) requerem GND 3
  por elemento, disponível separadamente via SICONFI DCA ou FINBRA.

Uso:
    python scripts/build_siconfi_fiscal.py
    python scripts/build_siconfi_fiscal.py --rreo-file data/raw/siconfi_rreo_bimestral.csv
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent

RREO_FILE = ROOT / "data" / "raw" / "siconfi_rreo_bimestral.csv"
RPPS_FILE = ROOT / "data" / "raw" / "siconfi_rpps_bimestral.csv"
OUT_FILE = ROOT / "data" / "raw" / "siconfi_fiscal.csv"

# Correct bimestre → quarter mapping (Santos et al. 2015 methodology)
# Bim 2 and Bim 5 are split equally between adjacent quarters
BIMESTRE_TO_TRIM: Dict[int, Tuple[int, ...]] = {
    1: (1,),       # Jan-Feb  → Q1 entirely
    2: (1, 2),     # Mar-Apr  → ½Q1 + ½Q2
    3: (2,),       # May-Jun  → Q2 entirely
    4: (3,),       # Jul-Aug  → Q3 entirely
    5: (3, 4),     # Sep-Oct  → ½Q3 + ½Q4
    6: (4,),       # Nov-Dec  → Q4 entirely
}

# RPPS account description keywords to identify contrib_imputada rows
RPPS_KEYWORDS = (
    "CONTRIBUI",    # catches "CONTRIBUIÇÕES IMPUTADAS", "CONTRIBUIÇÃO PATRONAL"
    "IMPUTAD",
    "PATRONAL",
)

# Tiers expected in RREO file
TIER_UNIAO = "uniao"
TIER_ESTADO = "estado"
TIER_MUNICIPIO = "municipio"


# ─────────────────────────────────────────────────────────────────────────────
# Loaders
# ─────────────────────────────────────────────────────────────────────────────

def load_rreo(path: Path) -> List[dict]:
    if not path.exists():
        print(f"WARNING: {path} not found — run download_siconfi_rreo.py first")
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_rpps(path: Path) -> List[dict]:
    if not path.exists():
        print(f"WARNING: {path} not found — contrib_imputada will be zero")
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ─────────────────────────────────────────────────────────────────────────────
# Bimestral → Trimestral
# ─────────────────────────────────────────────────────────────────────────────

def bim_to_quarter_rows(rows: List[dict]) -> List[dict]:
    """
    Converts bimestral records to trimestral.
    Split bimestres (2 and 5) contribute 50% to each adjacent quarter.
    """
    out = []
    for row in rows:
        bim = int(row["bimestre"])
        quarters = BIMESTRE_TO_TRIM.get(bim)
        if not quarters:
            continue
        vl = float(row.get("vl_liquidado_bi", 0) or 0)
        share = vl / len(quarters)
        for q in quarters:
            new_row = dict(row)
            new_row["trimestre"] = q
            new_row["vl_quarter_bi"] = share
            out.append(new_row)
    return out


def bim_to_quarter_rpps(rows: List[dict]) -> List[dict]:
    """Same conversion for RPPS rows (uses vl_resultado field)."""
    out = []
    for row in rows:
        bim = int(row["bimestre"])
        quarters = BIMESTRE_TO_TRIM.get(bim)
        if not quarters:
            continue
        vl_str = row.get("vl_resultado", "") or "0"
        try:
            vl = float(vl_str)
        except ValueError:
            continue
        # SICONFI values may be in R$ — inspect raw file to confirm unit
        # Assuming R$ and converting to R$ bilhões
        vl_bi = vl / 1e9
        share = vl_bi / len(quarters)
        for q in quarters:
            new_row = dict(row)
            new_row["trimestre"] = q
            new_row["vl_quarter_bi"] = share
            out.append(new_row)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation helpers
# ─────────────────────────────────────────────────────────────────────────────

def aggregate_by_period(
    quarterly_rows: List[dict],
    tiers: Optional[List[str]] = None,
    gnd: str = "1",
) -> Dict[str, float]:
    """Aggregate vl_quarter_bi by (ano, trimestre) for specified tiers and GND."""
    totals: Dict[str, float] = defaultdict(float)
    for row in quarterly_rows:
        if row.get("cd_grupo") != gnd:
            continue
        if tiers and row.get("tier") not in tiers:
            continue
        period = f"{row['ano']}Q{row['trimestre']}"
        totals[period] += float(row.get("vl_quarter_bi", 0))
    return dict(totals)


def aggregate_rpps(quarterly_rpps: List[dict]) -> Dict[str, float]:
    """Aggregate contrib_imputada from RPPS rows."""
    totals: Dict[str, float] = defaultdict(float)
    for row in quarterly_rpps:
        # Filter to rows that look like contrib_imputada
        ds = (row.get("ds_conta", "") + row.get("ds_coluna", "")).upper()
        if not any(kw in ds for kw in RPPS_KEYWORDS):
            continue
        vl = float(row.get("vl_quarter_bi", 0) or 0)
        if vl == 0:
            continue
        period = f"{row['ano']}Q{row['trimestre']}"
        totals[period] += vl
    return dict(totals)


def merge_periods(*dicts: Dict[str, float]) -> Dict[str, float]:
    """Sum multiple period→value dicts into one."""
    result: Dict[str, float] = defaultdict(float)
    for d in dicts:
        for k, v in d.items():
            result[k] += v
    return dict(result)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--rreo-file", default=str(RREO_FILE))
    p.add_argument("--rpps-file", default=str(RPPS_FILE))
    p.add_argument("--out", default=str(OUT_FILE))
    return p.parse_args()


def main():
    args = parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print("Loading RREO bimestral data...")
    rreo_raw = load_rreo(Path(args.rreo_file))
    print(f"  {len(rreo_raw)} raw rows")

    print("Loading RPPS bimestral data...")
    rpps_raw = load_rpps(Path(args.rpps_file))
    print(f"  {len(rpps_raw)} raw rows")

    if not rreo_raw and not rpps_raw:
        sys.exit("No input data found. Run download scripts first.")

    print("\nConverting bimestral → trimestral...")
    rreo_q = bim_to_quarter_rows(rreo_raw)
    rpps_q = bim_to_quarter_rpps(rpps_raw)

    print("Aggregating by period and spec...")

    # Component series from RREO
    uniao_gnd1 = aggregate_by_period(rreo_q, tiers=[TIER_UNIAO], gnd="1")
    estados_gnd1 = aggregate_by_period(rreo_q, tiers=[TIER_ESTADO], gnd="1")
    municipios_gnd1 = aggregate_by_period(rreo_q, tiers=[TIER_MUNICIPIO], gnd="1")

    # RPPS contrib_imputada (Union only)
    rpps_imputada = aggregate_rpps(rpps_q)

    # Build specs
    specs = {
        "serie1": uniao_gnd1,
        "serie3": merge_periods(uniao_gnd1, estados_gnd1),
        "serie5": merge_periods(uniao_gnd1, estados_gnd1, municipios_gnd1),
        "serie13": merge_periods(uniao_gnd1, estados_gnd1, municipios_gnd1, rpps_imputada),
        "moderna_a": merge_periods(uniao_gnd1, estados_gnd1, municipios_gnd1, rpps_imputada),
    }

    # Collect all periods
    all_periods = set()
    for d in specs.values():
        all_periods.update(d.keys())
    all_periods = sorted(all_periods)

    print(f"\nPeriods covered: {min(all_periods) if all_periods else 'none'} "
          f"— {max(all_periods) if all_periods else 'none'}")
    print(f"Specs: {list(specs.keys())}")

    # Write output
    rows = []
    for spec_name, period_dict in specs.items():
        for period in sorted(period_dict.keys()):
            vl = period_dict[period]
            if vl == 0:
                continue
            rows.append({
                "periodo": period,
                "spec": spec_name,
                "valor_bi": round(vl, 6),
            })

    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "spec", "valor_bi"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nSaved {len(rows)} rows to {out}")

    # Summary by spec
    print("\nRows per spec:")
    for spec_name in specs:
        count = sum(1 for r in rows if r["spec"] == spec_name)
        sample_vals = [r["valor_bi"] for r in rows if r["spec"] == spec_name][:4]
        print(f"  {spec_name:<12}: {count} periods  first 4 values: {sample_vals}")

    if not rpps_imputada:
        print("\nNOTE: RPPS contrib_imputada = 0 (no matching rows in RPPS file).")
        print("  Inspect data/raw/siconfi_rpps_bimestral.csv and adjust RPPS_KEYWORDS in this script.")

    print(f"\nNext step: python pipeline.py")
    print(f"  Expects: data/raw/cnt_quarterly.csv AND {out}")


if __name__ == "__main__":
    main()
