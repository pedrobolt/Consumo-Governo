"""
Fetch SICONFI RREO 2026 bim1+bim2 for União + all estados.
Appends new rows to existing CSVs (does not re-fetch existing years).
Also fetches RPPS for União.
Reports coverage: how many entes responded per bimestre.
"""
import csv
import logging
import sys
import time
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DATA_RAW = ROOT / "data" / "raw"

BASE_URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"
YEAR = 2026
BIMESTRES = [1, 2]
DELAY = 0.3

TODOS_ESTADOS = {
    "AC": 12, "AL": 27, "AM": 13, "AP": 16, "BA": 29,
    "CE": 23, "DF": 53, "ES": 32, "GO": 52, "MA": 21,
    "MG": 31, "MS": 50, "MT": 51, "PA": 15, "PB": 25,
    "PE": 26, "PI": 22, "PR": 41, "RJ": 33, "RN": 24,
    "RO": 11, "RR": 14, "RS": 43, "SC": 42, "SE": 28,
    "SP": 35, "TO": 17,
}
UNIAO = {"BR": 1}

CONTA_PESSOAL     = "PESSOAL E ENCARGOS SOCIAIS"
COD_CONTA         = "PessoalEEncargosSociais"
COLUNA_LIQ        = "DESPESAS LIQUIDADAS NO BIMESTRE"
COLUNA_LIQ_OLD    = "No Bimestre"
COLUNA_LIQ_OLD_NX = "Bimestre (h)"

RPPS_KEYWORDS = ["Previdência do Regime Estatutário", "Regime Estatut"]


def fetch_rreo(session, id_ente, year, bimestre, anexo="Anexo 1"):
    params = dict(an_exercicio=year, nr_periodo=bimestre,
                  co_tipo_demonstrativo="RREO",
                  no_co_tipo_demonstrativo=f"RREO - {anexo}",
                  id_ente=id_ente)
    try:
        r = session.get(BASE_URL, params=params, timeout=30)
        r.raise_for_status()
        return r.json().get("items", [])
    except Exception as exc:
        logger.debug("ente=%s year=%d bim=%d %s: %s", id_ente, year, bimestre, anexo, exc)
        return []


def pessoal_from_items(items):
    total = 0.0
    for i, item in enumerate(items):
        if (item.get("conta") == CONTA_PESSOAL
                and item.get("cod_conta") == COD_CONTA):
            col = item.get("coluna", "")
            v   = item.get("valor")
            if v is None:
                continue
            if col == COLUNA_LIQ:
                total += float(v)
            elif col == COLUNA_LIQ_OLD:
                nxt = items[i+1].get("coluna","") if i+1 < len(items) else ""
                if COLUNA_LIQ_OLD_NX in nxt:
                    total += float(v)
    return total


def rpps_from_items(items):
    total = 0.0
    for item in items:
        conta  = str(item.get("conta", ""))
        coluna = str(item.get("coluna",""))
        rotulo = str(item.get("rotulo",""))
        if (any(kw in conta for kw in RPPS_KEYWORDS)
                and coluna == COLUNA_LIQ
                and "Exceto" in rotulo):
            v = item.get("valor")
            if v is not None:
                total += float(v)
    return total


def load_existing_keys(path):
    """Return set of (ano, bimestre, cod_ibge) already in CSV."""
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as f:
        return {(int(r["ano"]), int(r["bimestre"]), int(r["cod_ibge"]))
                for r in csv.DictReader(f)}


def append_rows(path, new_rows, fieldnames):
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            w.writeheader()
        w.writerows(new_rows)


# ── RREO Anexo 1 ──────────────────────────────────────────────────────────────
rreo_fields = ["ano", "bimestre", "cod_ibge", "uf", "valor_bi"]

for label, entes, out_csv in [
    ("uniao",   UNIAO,         DATA_RAW / "siconfi_rreo_uniao.csv"),
    ("estados", TODOS_ESTADOS, DATA_RAW / "siconfi_rreo_estados.csv"),
]:
    existing = load_existing_keys(out_csv)
    session  = requests.Session()
    new_rows = []
    coverage = {bim: 0 for bim in BIMESTRES}

    for uf, cod in entes.items():
        for bim in BIMESTRES:
            if (YEAR, bim, cod) in existing:
                coverage[bim] += 1
                continue
            items = fetch_rreo(session, cod, YEAR, bim)
            val   = pessoal_from_items(items)
            if val > 0:
                new_rows.append(dict(ano=YEAR, bimestre=bim,
                                     cod_ibge=cod, uf=uf,
                                     valor_bi=round(val/1e9, 6)))
                coverage[bim] += 1
            time.sleep(DELAY)

    if new_rows:
        append_rows(out_csv, new_rows, rreo_fields)
    logger.info("[%s] 2026 coverage — %s",
                label,
                ", ".join(f"Bim{b}: {coverage[b]}/{len(entes)}" for b in BIMESTRES))

# ── RPPS Anexo 4 ──────────────────────────────────────────────────────────────
rpps_path   = DATA_RAW / "siconfi_rpps_bimestral.csv"
rpps_fields = ["ano", "bimestre", "cod_ibge", "uf", "valor_bi"]
existing_rp = load_existing_keys(rpps_path)
session     = requests.Session()
rpps_rows   = []
rpps_cov    = {bim: 0 for bim in BIMESTRES}

for bim in BIMESTRES:
    if (YEAR, bim, 1) in existing_rp:
        rpps_cov[bim] += 1
        continue
    items = fetch_rreo(session, 1, YEAR, bim, anexo="Anexo 4")
    val   = rpps_from_items(items)
    if val > 0:
        rpps_rows.append(dict(ano=YEAR, bimestre=bim,
                              cod_ibge=1, uf="BR",
                              valor_bi=round(val/1e9, 6)))
        rpps_cov[bim] = 1
    time.sleep(DELAY)

if rpps_rows:
    append_rows(rpps_path, rpps_rows, rpps_fields)
logger.info("[rpps] 2026 coverage — %s",
            ", ".join(f"Bim{b}: {rpps_cov[b]}/1" for b in BIMESTRES))

print("\nDone.")
