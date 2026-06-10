"""
Refresh detection: compare local cache with latest available data.

Checks:
  1. SIDRA table 1846 — latest CNT quarter available from IBGE API
  2. SICONFI RREO    — latest bimestre available for Uniao

Returns (and prints) a dict:
  {
    "cnt":     {"cached": "2026Q1", "available": "2026Q1", "new": False},
    "siconfi": {"cached": "2026/Bim2", "available": "2026/Bim2", "new": False},
    "any_new": False,
  }

Run before pipeline.py --update.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT     = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"

SIDRA_PERIODS_URL = "https://servicodados.ibge.gov.br/api/v3/agregados/1846/periodos"
SICONFI_RREO_URL  = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
TIMEOUT = 20


# ── CNT via SIDRA ─────────────────────────────────────────────────────────────

def _latest_sidra_period() -> str | None:
    """Return latest period id like '202601' from SIDRA table 1846."""
    try:
        r = requests.get(SIDRA_PERIODS_URL, timeout=TIMEOUT)
        r.raise_for_status()
        periods = r.json()
        if not periods:
            return None
        latest = max(p["id"] for p in periods if str(p.get("id", "")).isdigit())
        return latest
    except Exception as exc:
        print(f"  [WARN] SIDRA query failed: {exc}")
        return None


def _sidra_to_quarter(period_id: str) -> str:
    """Convert SIDRA period id '202601' to '2026Q1'."""
    year  = period_id[:4]
    month = int(period_id[4:])
    q     = (month - 1) // 3 + 1
    return f"{year}Q{q}"


def _cached_cnt_latest() -> str | None:
    path = DATA_RAW / "cnt_quarterly.csv"
    if not path.exists():
        return None
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    return max(r["periodo"] for r in rows)


# ── SICONFI RREO ──────────────────────────────────────────────────────────────

def _latest_siconfi_bimestre(id_ente: int = 1,
                              probe_year: int | None = None) -> tuple[int, int] | None:
    """Find latest (year, bimestre) for given ente by probing descending."""
    if probe_year is None:
        probe_year = datetime.now().year

    for year in [probe_year, probe_year - 1]:
        for bim in range(6, 0, -1):
            params = dict(
                an_exercicio=year,
                nr_periodo=bim,
                co_tipo_demonstrativo="RREO",
                no_co_tipo_demonstrativo="RREO - Anexo 1",
                id_ente=id_ente,
            )
            try:
                r = requests.get(SICONFI_RREO_URL, params=params, timeout=TIMEOUT)
                r.raise_for_status()
                if r.json().get("items"):
                    return year, bim
            except Exception:
                pass
            time.sleep(0.2)
    return None


def _cached_siconfi_latest() -> tuple[int, int] | None:
    path = DATA_RAW / "siconfi_rreo_uniao.csv"
    if not path.exists():
        return None
    import csv
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    return max((int(r["ano"]), int(r["bimestre"])) for r in rows)


# ── Main ──────────────────────────────────────────────────────────────────────

def check_updates(verbose: bool = True) -> dict:
    result = {}

    # CNT
    if verbose:
        print("Checking CNT (SIDRA table 1846)...")
    cached_cnt = _cached_cnt_latest()
    avail_id   = _latest_sidra_period()
    avail_cnt  = _sidra_to_quarter(avail_id) if avail_id else None
    cnt_new    = bool(avail_cnt and cached_cnt and avail_cnt != cached_cnt)
    result["cnt"] = {"cached": cached_cnt, "available": avail_cnt, "new": cnt_new}
    if verbose:
        tag = "NEW DATA AVAILABLE" if cnt_new else "up to date"
        print(f"  CNT cached: {cached_cnt}  |  SIDRA available: {avail_cnt}  [{tag}]")

    # SICONFI (probe Uniao = id 1)
    if verbose:
        print("Checking SICONFI RREO (Uniao)...")
    cached_sic = _cached_siconfi_latest()
    avail_sic  = _latest_siconfi_bimestre(id_ente=1)
    sic_new    = bool(avail_sic and cached_sic and avail_sic != cached_sic)
    cached_str = f"{cached_sic[0]}/Bim{cached_sic[1]}" if cached_sic else "none"
    avail_str  = f"{avail_sic[0]}/Bim{avail_sic[1]}"   if avail_sic  else "unavailable"
    result["siconfi"] = {"cached": cached_str, "available": avail_str, "new": sic_new}
    if verbose:
        tag = "NEW DATA AVAILABLE" if sic_new else "up to date"
        print(f"  SICONFI cached: {cached_str}  |  available: {avail_str}  [{tag}]")

    result["any_new"] = result["cnt"]["new"] or result["siconfi"]["new"]
    if verbose:
        print()
        if result["any_new"]:
            print("=> New data detected. Run: python pipeline.py --update")
        else:
            print("=> All sources up to date.")

    return result


if __name__ == "__main__":
    check_updates(verbose=True)
