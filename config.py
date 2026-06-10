"""
Configurações centrais do projeto Consumo do Governo Nominal Trimestral.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_OUTPUT = ROOT / "data" / "output"
OUTPUT_CHARTS = ROOT / "output" / "charts"
OUTPUT_TABLES = ROOT / "output" / "tables"
OUTPUT_SERIES = ROOT / "output" / "series"
OUTPUT_REPORTS = ROOT / "output" / "reports"

for d in [DATA_RAW, DATA_PROCESSED, DATA_OUTPUT,
          OUTPUT_CHARTS, OUTPUT_TABLES, OUTPUT_SERIES, OUTPUT_REPORTS]:
    d.mkdir(parents=True, exist_ok=True)

# ──────────────────────────────────────────────
# Horizonte temporal
# ──────────────────────────────────────────────
YEAR_START = 2010          # Início da série (paper original)
YEAR_END = 2025            # Ano mais recente com dados completos (CNT FTP vai até 2026Q1)
FREQ = 4                   # Trimestral

# ──────────────────────────────────────────────
# Spec fixa — alterada apenas com pipeline.py --full
# ──────────────────────────────────────────────
BEST_SPEC          = "spec_estados_sal_ce"
OOS_WEIGHTS_FILE   = OUTPUT_TABLES / "oos_weights.json"
VINTAGE_FILE       = OUTPUT_TABLES / "vintage_history.csv"
UPDATE_REPORT_FILE = ROOT / "output" / "UPDATE_REPORT.md"

# ──────────────────────────────────────────────
# APIs
# ──────────────────────────────────────────────
IBGE_API_BASE = "https://servicodados.ibge.gov.br/api/v3"
SICONFI_API_BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"
TRANSPARENCIA_API_BASE = "https://api.portaldatransparencia.gov.br/api-de-dados"
API_TIMEOUT = 30
CACHE_DAYS = 7

# ──────────────────────────────────────────────
# Elementos de despesa (execução orçamentária)
# ──────────────────────────────────────────────
ELEMENTOS_SALARIOS = ["319011", "319012"]
ELEMENTOS_CONTRIB_EFETIVAS = ["319013", "319113"]
# Contribuições imputadas vêm do RREO Anexo 4 (RPPS)

GND_PESSOAL = "1"            # Pessoal e Encargos Sociais
GND_OUTRAS_CORRENTES = "3"   # Outras Despesas Correntes (inclui CI)

# ──────────────────────────────────────────────
# Entes da Federação
# ──────────────────────────────────────────────
# Amostra do paper original
ESTADOS_PAPER = {
    "DF": "53", "AM": "13", "BA": "29", "ES": "32",
    "PE": "26", "PI": "22", "PR": "41", "RJ": "33",
    "RS": "43", "SC": "42", "SP": "35",
}

# Amostra completa (modernização)
TODOS_ESTADOS = {
    "AC": "12", "AL": "27", "AM": "13", "AP": "16", "BA": "29",
    "CE": "23", "DF": "53", "ES": "32", "GO": "52", "MA": "21",
    "MG": "31", "MS": "50", "MT": "51", "PA": "15", "PB": "25",
    "PE": "26", "PI": "22", "PR": "41", "RJ": "33", "RN": "24",
    "RO": "11", "RR": "14", "RS": "43", "SC": "42", "SE": "28",
    "SP": "35", "TO": "17",
}

MUNICIPIOS_PAPER = [
    "1501402",  # Belém-PA
    "3106200",  # Belo Horizonte-MG
    "3509502",  # Campinas-SP
    "5002704",  # Campo Grande-MS
    "4106902",  # Curitiba-PR
    "2304400",  # Fortaleza-CE
    "5208707",  # Goiânia-GO
    "1302603",  # Manaus-AM
    "4314902",  # Porto Alegre-RS
    "2611606",  # Recife-PE
    "3543402",  # Ribeirão Preto-SP
    "3304557",  # Rio de Janeiro-RJ
    "2927408",  # Salvador-BA
    "3548500",  # Santos-SP
    "3549805",  # São Bernardo do Campo-SP
    "3549904",  # São José dos Campos-SP
    "3550308",  # São Paulo-SP
]

# ──────────────────────────────────────────────
# Parâmetros do método Denton
# ──────────────────────────────────────────────
DENTON_DIFF_ORDER = 1    # Ordem das diferenças (1 = primeira diferença)

# ──────────────────────────────────────────────
# Critério de convergência do loop de otimização
# ──────────────────────────────────────────────
MAX_CYCLES = 50
RMSE_IMPROVEMENT_THRESHOLD = 0.01   # 1%
MIN_CONSECUTIVE_NO_IMPROVE = 5
TARGET_CORRELATION = 0.98
TARGET_MAPE = 2.0                    # %

# ──────────────────────────────────────────────
# Nomes das especificações (como no paper)
# ──────────────────────────────────────────────
SPEC_NAMES = {
    1:  "Apenas União: Salários+ContEfetiva (Liquidado)",
    2:  "União: Sal+CE (Liq+RP)",
    3:  "União+Estados: Sal+CE (Liq)",
    4:  "União+Estados: Sal+CE+RP",
    5:  "União+Est+Mun: Sal+CE (Liq)",
    6:  "União+Est+Mun: Sal+CE+RP",
    7:  "União+Est+Mun: Sal+CE+CI (Liq+RP misto)",
    8:  "União+Est+Mun: Sal+CE+CI+RP",
    9:  "Full com CI estados",
    10: "Full com CI municípios",
    11: "Full com CI tudo",
    12: "Full com RP Mun",
    13: "Serie13-paper: União+Est+Mun Sal+CE+CI_Imp (Liq sem RP)",
}
