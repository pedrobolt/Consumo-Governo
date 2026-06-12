"""
Configurações centrais do projeto Consumo do Governo Nominal Trimestral.
"""
from pathlib import Path

ROOT = Path(__file__).parent
DATA_RAW       = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
OUTPUT_CHARTS  = ROOT / "output" / "charts"
OUTPUT_TABLES  = ROOT / "output" / "tables"
OUTPUT_SERIES  = ROOT / "output" / "series"

for d in [DATA_RAW, DATA_PROCESSED, OUTPUT_CHARTS, OUTPUT_TABLES, OUTPUT_SERIES]:
    d.mkdir(parents=True, exist_ok=True)

# ── Horizonte temporal ────────────────────────────────────────────────────────
YEAR_START = 2010   # início da série CNT (benchmark anual)
YEAR_END   = 2025   # último ano com CNT completa publicada
FREQ       = 4      # trimestral

# ── Paths de saída fixos ──────────────────────────────────────────────────────
VINTAGE_FILE       = OUTPUT_TABLES / "vintage_history.csv"
UPDATE_REPORT_FILE = ROOT / "output" / "UPDATE_REPORT.md"

# ── Entes da federação ────────────────────────────────────────────────────────
TODOS_ESTADOS = {
    "AC": "12", "AL": "27", "AM": "13", "AP": "16", "BA": "29",
    "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21",
    "MG": "31", "MS": "50", "MT": "51", "PA": "15", "PB": "25",
    "PE": "26", "PI": "22", "PR": "41", "RJ": "33", "RN": "24",
    "RO": "11", "RR": "14", "RS": "43", "SC": "42", "SE": "28",
    "SP": "35", "TO": "17",
}

# ── Elementos de despesa (SICONFI) ────────────────────────────────────────────
ELEMENTOS_SALARIOS         = ["319011", "319012"]
ELEMENTOS_CONTRIB_EFETIVAS = ["319013", "319113"]
# Contribuições imputadas: RREO Anexo 4 (RPPS)
