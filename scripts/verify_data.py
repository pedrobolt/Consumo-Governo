#!/usr/bin/env python3
"""
Verifica integridade dos arquivos baixados antes de rodar o pipeline.

Checks:
  1. Existência dos arquivos obrigatórios em data/raw/
  2. CNT: formato, completude 2010–2024, verificação vs. paper Tabela 2
  3. SICONFI fiscal: formato, cobertura trimestral, valores plausíveis
  4. Consistência entre os dois arquivos (períodos em comum)

Uso:
    python scripts/verify_data.py
    python scripts/verify_data.py --strict   # exits 1 if any warning found
"""

import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent

CNT_FILE = ROOT / "data" / "raw" / "cnt_quarterly.csv"
FISCAL_FILE = ROOT / "data" / "raw" / "siconfi_fiscal.csv"

# Paper Tabela 2: CNT real (R$ bilhões)
CNT_PAPER: Dict[str, float] = {
    "2010Q1": 163.11, "2010Q2": 172.80, "2010Q3": 180.25, "2010Q4": 222.81,
    "2011Q1": 177.58, "2011Q2": 198.67, "2011Q3": 199.00, "2011Q4": 242.12,
    "2012Q1": 198.33, "2012Q2": 220.36, "2012Q3": 220.14, "2012Q4": 270.78,
    "2013Q1": 217.08, "2013Q2": 248.11, "2013Q3": 244.31, "2013Q4": 300.85,
    "2014Q1": 244.40, "2014Q2": 271.49, "2014Q3": 274.12, "2014Q4": 324.89,
}

# Paper Tabela 2: série estimada (indicador, R$ bilhões)
INDICATOR_PAPER: Dict[str, float] = {
    "2010Q1": 169.90, "2011Q3": 188.30, "2014Q4": 325.00,
}


def warn(msg: str, warnings: List[str]) -> None:
    print(f"  WARNING: {msg}")
    warnings.append(msg)


def ok(msg: str) -> None:
    print(f"  OK: {msg}")


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--cnt-file", default=str(CNT_FILE))
    p.add_argument("--fiscal-file", default=str(FISCAL_FILE))
    p.add_argument("--strict", action="store_true",
                   help="Exit with code 1 if any warnings found")
    p.add_argument("--year-start", type=int, default=2010)
    p.add_argument("--year-end", type=int, default=2024)
    return p.parse_args()


def check_cnt(path: Path, year_start: int, year_end: int, warnings: List[str]) -> Dict[str, float]:
    print(f"\n--- CNT: {path} ---")

    if not path.exists():
        warn(f"File missing: {path}", warnings)
        print("  Run: python scripts/download_cnt.py")
        return {}

    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        warn("File is empty", warnings)
        return {}

    required_cols = {"periodo", "cnt_nominal_bi"}
    actual_cols = set(rows[0].keys())
    if not required_cols.issubset(actual_cols):
        warn(f"Missing columns: {required_cols - actual_cols}", warnings)
        return {}

    ok(f"{len(rows)} rows, columns: {actual_cols}")

    cnt = {}
    for row in rows:
        try:
            cnt[row["periodo"]] = float(row["cnt_nominal_bi"])
        except ValueError:
            warn(f"Non-numeric value for {row['periodo']}: {row['cnt_nominal_bi']}", warnings)

    # Check coverage
    expected = [f"{y}Q{q}" for y in range(year_start, year_end + 1) for q in range(1, 5)]
    missing = [p for p in expected if p not in cnt]
    if missing:
        warn(f"{len(missing)} missing periods: {missing[:8]}{'...' if len(missing) > 8 else ''}", warnings)
    else:
        ok(f"Full coverage {year_start}Q1–{year_end}Q4 ({len(expected)} quarters)")

    # Verify against paper
    print("\n  Verification vs. Santos et al. (2015), Table 2:")
    diffs = []
    for period, expected_val in sorted(CNT_PAPER.items()):
        actual = cnt.get(period)
        if actual is None:
            warn(f"Paper period {period} missing in downloaded data", warnings)
            continue
        diff = abs(actual - expected_val)
        diffs.append(diff)
        status = "OK" if diff < 2.0 else "WARNING"
        print(f"    {period}: got {actual:.2f}  paper {expected_val:.2f}  diff {diff:.2f}  [{status}]")
        if diff >= 2.0:
            warn(f"{period}: large diff vs paper ({diff:.2f} R$ bi) — possible IBGE revision", warnings)

    if diffs:
        print(f"\n  Max diff vs paper: {max(diffs):.2f} R$ bi  |  Avg: {sum(diffs)/len(diffs):.2f}")

    # Plausibility: values should be between 100 and 3000 R$ bi
    out_of_range = [(p, v) for p, v in cnt.items() if not (50 < v < 5000)]
    if out_of_range:
        warn(f"Out-of-range values: {out_of_range[:5]}", warnings)
    else:
        ok(f"All values in plausible range (50–5000 R$ bi)")

    return cnt


def check_fiscal(path: Path, warnings: List[str]) -> Dict[str, Dict[str, float]]:
    print(f"\n--- SICONFI fiscal: {path} ---")

    if not path.exists():
        warn(f"File missing: {path}", warnings)
        print("  Run: python scripts/build_siconfi_fiscal.py")
        return {}

    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        warn("File is empty", warnings)
        return {}

    required_cols = {"periodo", "spec", "valor_bi"}
    actual_cols = set(rows[0].keys())
    if not required_cols.issubset(actual_cols):
        warn(f"Missing columns: {required_cols - actual_cols}", warnings)
        return {}

    ok(f"{len(rows)} rows, columns: {actual_cols}")

    # Build dict: {spec: {period: value}}
    fiscal: Dict[str, Dict[str, float]] = {}
    for row in rows:
        spec = row["spec"]
        period = row["periodo"]
        try:
            val = float(row["valor_bi"])
        except ValueError:
            warn(f"Non-numeric value spec={spec} period={period}", warnings)
            continue
        if spec not in fiscal:
            fiscal[spec] = {}
        fiscal[spec][period] = val

    print(f"\n  Specs present: {sorted(fiscal.keys())}")

    if "serie13" not in fiscal:
        warn("serie13 not present — this is the key spec from the paper", warnings)

    for spec, data in sorted(fiscal.items()):
        periods = sorted(data.keys())
        vals = list(data.values())
        print(f"  {spec:<12}: {len(data)} periods  "
              f"range: {min(periods)}–{max(periods)}  "
              f"values: [{min(vals):.1f}, {max(vals):.1f}] R$ bi")

    # Verify indicator vs. paper for available specs
    if "serie13" in fiscal:
        print("\n  Verification of serie13 vs. Santos et al. (2015), Table 2:")
        for period, expected_val in sorted(INDICATOR_PAPER.items()):
            actual = fiscal["serie13"].get(period)
            if actual is None:
                warn(f"serie13 missing period {period}", warnings)
                continue
            diff = abs(actual - expected_val)
            max_ok_diff = expected_val * 0.15  # 15% tolerance for approximation
            status = "OK" if diff < max_ok_diff else "LARGE_DIFF"
            print(f"    {period}: got {actual:.2f}  paper {expected_val:.2f}  "
                  f"diff {diff:.1f} ({100*diff/expected_val:.1f}%)  [{status}]")
            if diff >= max_ok_diff:
                warn(f"serie13 {period}: diff {diff:.1f} R$ bi vs paper (>{max_ok_diff:.1f})", warnings)

    return fiscal


def check_consistency(cnt: Dict[str, float], fiscal: Dict[str, Dict[str, float]],
                      warnings: List[str]) -> None:
    print("\n--- Consistency check ---")
    if not cnt or not fiscal:
        return

    cnt_periods = set(cnt.keys())
    for spec, data in fiscal.items():
        fiscal_periods = set(data.keys())
        overlap = cnt_periods & fiscal_periods
        cnt_only = cnt_periods - fiscal_periods
        fiscal_only = fiscal_periods - cnt_periods

        print(f"  {spec}: {len(overlap)} periods in common")
        if cnt_only:
            print(f"    CNT-only: {sorted(cnt_only)[:4]}{'...' if len(cnt_only) > 4 else ''}")
        if fiscal_only:
            print(f"    Fiscal-only: {sorted(fiscal_only)[:4]}{'...' if len(fiscal_only) > 4 else ''}")

        if len(overlap) < 20:
            warn(f"{spec}: only {len(overlap)} overlapping periods — pipeline may produce limited results", warnings)
        else:
            ok(f"{spec}: {len(overlap)} overlapping periods — sufficient for pipeline")
        break  # Only check first spec to avoid repetition


def main():
    args = parse_args()
    warnings: List[str] = []

    print("=" * 60)
    print("DATA VERIFICATION — Consumo do Governo Pipeline")
    print("=" * 60)

    cnt = check_cnt(Path(args.cnt_file), args.year_start, args.year_end, warnings)
    fiscal = check_fiscal(Path(args.fiscal_file), warnings)
    check_consistency(cnt, fiscal, warnings)

    print("\n" + "=" * 60)
    if warnings:
        print(f"RESULT: {len(warnings)} WARNING(s) found:")
        for i, w in enumerate(warnings, 1):
            print(f"  {i}. {w}")
        if args.strict:
            sys.exit(1)
    else:
        print("RESULT: All checks passed — data ready for pipeline.py")

    print("=" * 60)


if __name__ == "__main__":
    main()
