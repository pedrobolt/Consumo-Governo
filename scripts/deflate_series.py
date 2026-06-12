"""
Deflate the nominal government consumption series to constant 2010 prices.

Sources:
  In-sample deflator : implicit deflator derived from IBGE Tab_Compl_CNT.zip
                       (same file as download_cnt.py), volume index sheet.
                       implicit_deflator = nominal / volume × (normalised to 2010=100)
  Nowcast proxy      : IPCA monthly variation from IBGE SIDRA table 1737 var 63.
                       Clearly flagged as proxy (IPCA ≠ GDP deflator for govt).

Usage:
    python scripts/deflate_series.py

Reads:
    data/raw/cnt_deflator.csv      (auto-downloaded cache, refreshed if missing)
    output/tables/model_selected.csv

Writes:
    output/tables/serie_real.csv
    Columns: quarter, nominal_R_bi, deflator, real_R_bi_base2010,
             var_real_yoy_pct, deflator_is_proxy

Note on interpretation:
    real_R_bi_base2010 deflates the MODEL ESTIMATE, not the official IBGE series.
    The divergence from IBGE's published real growth equals the model's nominal
    estimation error (MAPE ~2.5% in-sample).
"""

import csv
import io
import logging
import re
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT     = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"
sys.path.insert(0, str(ROOT))
from config import OUTPUT_TABLES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

FTP_URL = (
    "https://ftp.ibge.gov.br/Contas_Nacionais/"
    "Contas_Nacionais_Trimestrais/Tabelas_Completas/Tab_Compl_CNT.zip"
)
SIDRA_IPCA_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/1737"
    "/periodos/{periods}/variaveis/63?localidades=N1[all]"
)
QUARTER_MAP = {"I": 1, "II": 2, "III": 3, "IV": 4}
BASE_YEAR   = 2010
PERIOD_RE   = re.compile(r"^(\d{4})[.]([IVX]+)$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _find_gov_col(df: pd.DataFrame) -> int | None:
    """Return column index whose header contains 'consumo do governo'."""
    for col in range(df.shape[1]):
        for row in range(min(6, df.shape[0])):
            cell = str(df.iloc[row, col]).lower()
            if "consumo do governo" in cell or "governo" in cell:
                return col
    return None


def _parse_cnt_sheet(df: pd.DataFrame) -> dict[str, float]:
    """Extract {period: value} from a CNT Excel sheet (nominal or volume)."""
    gov_col = _find_gov_col(df)
    if gov_col is None:
        return {}
    result = {}
    for i in range(4, df.shape[0]):
        m = PERIOD_RE.match(str(df.iloc[i, 0]).strip())
        if not m:
            continue
        q = QUARTER_MAP.get(m.group(2))
        if q is None:
            continue
        try:
            v = float(df.iloc[i, gov_col])
        except (TypeError, ValueError):
            continue
        result[f"{m.group(1)}Q{q}"] = v
    return result


# ── Deflator from IBGE CNT zip ────────────────────────────────────────────────

def download_deflator(force: bool = False) -> pd.Series:
    """
    Derive implicit deflator for Consumo do Governo from Tab_Compl_CNT.zip.

    implicit_deflator_t = (nominal_t / volume_index_t), normalised so
    the 2010 quarterly average = 100.

    Caches result to data/raw/cnt_deflator.csv.
    """
    deflator_csv = DATA_RAW / "cnt_deflator.csv"
    if deflator_csv.exists() and not force:
        df = pd.read_csv(deflator_csv)
        s  = df.set_index("periodo")["deflator"]
        logger.info("Loaded deflator from cache: %d periods", len(s))
        return s

    logger.info("Downloading Tab_Compl_CNT.zip for deflator...")
    r = requests.get(FTP_URL, timeout=120, stream=True)
    r.raise_for_status()
    raw_bytes = b"".join(r.iter_content(8192))
    logger.info("Downloaded %d bytes", len(raw_bytes))

    zf       = zipfile.ZipFile(io.BytesIO(raw_bytes))
    xls_name = next(n for n in zf.namelist()
                    if n.lower().endswith(".xls") or n.lower().endswith(".xlsx"))
    xls_bytes = zf.read(xls_name)
    xls       = pd.ExcelFile(io.BytesIO(xls_bytes))
    logger.info("Sheets in %s: %s", xls_name, xls.sheet_names)

    nominal_sheet = next(
        (s for s in xls.sheet_names if "corrente" in s.lower()),
        xls.sheet_names[0],
    )
    volume_sheet = next(
        (s for s in xls.sheet_names
         if any(kw in s.lower()
                for kw in ("volume", "índice", "indice", "quantum", "encadeado"))),
        None,
    )

    nominal = _parse_cnt_sheet(xls.parse(nominal_sheet, header=None))
    logger.info("Nominal: %d periods from '%s'", len(nominal), nominal_sheet)

    deflator: dict[str, float] = {}

    if volume_sheet:
        volume = _parse_cnt_sheet(xls.parse(volume_sheet, header=None))
        logger.info("Volume: %d periods from '%s'", len(volume), volume_sheet)
        for period in sorted(set(nominal) & set(volume)):
            n, v = nominal[period], volume[period]
            if v and v > 0:
                deflator[period] = n / v
    else:
        logger.warning("No volume/index sheet found in zip — IPCA proxy will be used.")

    # Normalise: base year average = 100
    if deflator:
        base_vals = [v for k, v in deflator.items() if k.startswith(str(BASE_YEAR))]
        if base_vals:
            base_avg = sum(base_vals) / len(base_vals)
            deflator = {k: round(v / base_avg * 100, 4) for k, v in deflator.items()}
            logger.info("Deflator normalised: base year %d average = 100", BASE_YEAR)

    # Cache
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    with open(deflator_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "deflator"])
        w.writeheader()
        for k in sorted(deflator):
            w.writerow({"periodo": k, "deflator": deflator[k]})
    logger.info("Saved deflator cache -> %s (%d periods)", deflator_csv, len(deflator))

    s = pd.Series(deflator, name="deflator")
    s.index.name = "periodo"
    return s


# ── IPCA proxy for nowcast quarters ──────────────────────────────────────────

def fetch_ipca_quarterly(year_start: int = 2010, year_end: int = 2030) -> pd.Series:
    """
    Fetch monthly IPCA variation (%) from SIDRA table 1737 var 63 in annual batches
    and aggregate to a quarterly price index with base year average = 100.

    Partial-quarter handling: if only 1–2 months of a quarter have been published,
    the missing months are filled by carrying the last known monthly rate forward
    (geometric mean of all filled months). These entries are included in the returned
    Series; the caller marks them deflator_is_proxy=True.

    IPCA is used as the proxy deflator for nowcast quarters without a published CNT
    deflator. Carry-forward only activates within a quarter that has at least one
    published month — entirely future quarters produce no entry.
    """
    raw_serie: dict[str, str] = {}
    for year in range(year_start, year_end + 1):
        periods = [f"{year}{m:02d}" for m in range(1, 13)]
        url = SIDRA_IPCA_URL.format(periods="|".join(periods))
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            year_data = resp.json()[0]["resultados"][0]["series"][0]["serie"]
            raw_serie.update(year_data)
        except Exception as exc:
            logger.debug("IPCA year %d fetch failed: %s", year, exc)
            continue
        time.sleep(0.3)

    if not raw_serie:
        logger.warning("IPCA fetch returned no data — proxy deflator unavailable.")
        return pd.Series(dtype=float)

    # Step 1: chain-link monthly % changes into a price level
    monthly_level_raw: dict[tuple[int, int], float] = {}
    monthly_pct: dict[tuple[int, int], float] = {}
    level = 100.0
    for period_code in sorted(raw_serie.keys()):
        val = raw_serie[period_code]
        if val in ("-", "...", None, ""):
            continue
        y, m = int(period_code[:4]), int(period_code[4:])
        pct = float(val)
        level *= (1 + pct / 100)
        monthly_level_raw[(y, m)] = level
        monthly_pct[(y, m)] = pct

    # Step 2: normalise so base year average = 100
    base_vals = [v for (y, _), v in monthly_level_raw.items() if y == BASE_YEAR]
    norm = (sum(base_vals) / len(base_vals)) if base_vals else 100.0
    monthly_level = {k: v / norm * 100 for k, v in monthly_level_raw.items()}

    # Step 3: quarterly aggregation with partial-quarter carry-forward
    quarterly: dict[str, float] = {}
    carry_lv: float | None = None
    carry_pct: float = 0.0
    n_partial = 0

    for year in range(year_start, year_end + 1):
        for q, q_months in [(1, [1, 2, 3]), (2, [4, 5, 6]),
                            (3, [7, 8, 9]), (4, [10, 11, 12])]:
            q_levels: list[float] = []
            has_published = False
            is_partial = False

            for month in q_months:
                ym = (year, month)
                if ym in monthly_level:
                    lv = monthly_level[ym]
                    q_levels.append(lv)
                    has_published = True
                    carry_lv = lv
                    carry_pct = monthly_pct.get(ym, carry_pct)
                elif has_published and carry_lv is not None:
                    # Carry forward within a partial quarter
                    carry_lv = carry_lv * (1 + carry_pct / 100)
                    q_levels.append(carry_lv)
                    is_partial = True

            if not q_levels:
                continue

            period_key = f"{year}Q{q}"
            product = 1.0
            for lv in q_levels:
                product *= lv
            quarterly[period_key] = round(product ** (1 / len(q_levels)), 4)
            if is_partial:
                n_partial += 1
                logger.info(
                    "IPCA partial quarter %s: %d/%d months published, carry-forward applied.",
                    period_key, len(q_levels) - is_partial, 3,
                )

    logger.info("IPCA proxy: %d quarters (%d partial)", len(quarterly), n_partial)
    return pd.Series(quarterly, name="ipca_proxy")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    ms_path = OUTPUT_TABLES / "model_selected.csv"
    if not ms_path.exists():
        logger.error("model_selected.csv not found. Run pipeline.py --full first.")
        return 1

    ms = pd.read_csv(ms_path).sort_values("quarter").reset_index(drop=True)

    cnt_deflator = download_deflator()
    have_deflator = set(cnt_deflator.index.tolist())
    all_quarters  = set(ms["quarter"].tolist())
    need_proxy    = all_quarters - have_deflator

    ipca_proxy = pd.Series(dtype=float)
    if need_proxy:
        logger.info(
            "Fetching IPCA proxy for %d nowcast quarters: %s",
            len(need_proxy), sorted(need_proxy),
        )
        ipca_proxy = fetch_ipca_quarterly()

        # Calibrate IPCA proxy to CNT deflator level at the last published CNT quarter.
        # This ensures the real series is continuous across the CNT/proxy boundary and
        # that YoY comparisons are meaningful.  Without calibration, the two deflators
        # are on different absolute scales even though both are indexed to 2010=100.
        if not ipca_proxy.empty:
            common = sorted(set(cnt_deflator.index) & set(ipca_proxy.index))
            if common:
                last_common = common[-1]
                scale = float(cnt_deflator[last_common]) / float(ipca_proxy[last_common])
                ipca_proxy = (ipca_proxy * scale).round(4)
                logger.info(
                    "IPCA proxy calibrated to CNT deflator at %s (scale=%.4f): "
                    "last CNT=%.2f, raw IPCA=%.2f",
                    last_common, scale,
                    cnt_deflator[last_common],
                    ipca_proxy[last_common] / scale,
                )

    rows = []
    for _, row in ms.iterrows():
        q   = row["quarter"]
        nom = float(row["estimate_R_bi"])

        if q in have_deflator:
            defl, is_proxy = float(cnt_deflator[q]), False
        elif q in ipca_proxy.index:
            defl, is_proxy = float(ipca_proxy[q]), True
            logger.info("Using IPCA proxy for %s: deflator=%.4f", q, defl)
        else:
            logger.warning("No deflator available for %s — skipping.", q)
            continue

        real = round(nom / defl * 100, 4) if defl > 0 else None
        rows.append({
            "quarter":            q,
            "nominal_R_bi":       round(nom, 4),
            "deflator":           round(defl, 4),
            "real_R_bi_base2010": real,
            "var_real_yoy_pct":   None,
            "deflator_is_proxy":  is_proxy,
        })

    df = pd.DataFrame(rows).sort_values("quarter").reset_index(drop=True)

    # YoY real growth
    real_s = df.set_index("quarter")["real_R_bi_base2010"]
    for i, row in df.iterrows():
        q    = row["quarter"]
        year = int(q[:4])
        qnum = int(q[5])
        q_lag = f"{year - 1}Q{qnum}"
        r_now = real_s.get(q)
        r_lag = real_s.get(q_lag)
        if r_now is not None and r_lag is not None and r_lag != 0:
            df.at[i, "var_real_yoy_pct"] = round((r_now / r_lag - 1) * 100, 2)

    OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_TABLES / "serie_real.csv"
    df.to_csv(out_path, index=False)
    logger.info("Saved -> %s (%d rows)", out_path, len(df))

    # ── Summary table ─────────────────────────────────────────────────────────
    print(f"\n  Série Real — base {BASE_YEAR} = 100\n")
    hdr = f"  {'Quarter':<10}{'Nominal':>12}{'Deflator':>12}{'Real':>14}{'YoY %':>10}  Proxy?"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for _, r in df.iterrows():
        yoy = f"{r['var_real_yoy_pct']:+.1f}%" if pd.notna(r["var_real_yoy_pct"]) else "  —"
        prx = " yes" if r["deflator_is_proxy"] else ""
        print(
            f"  {r['quarter']:<10}{r['nominal_R_bi']:>12.2f}"
            f"{r['deflator']:>12.2f}{r['real_R_bi_base2010']:>14.2f}"
            f"{yoy:>10}{prx}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
