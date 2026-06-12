# CLAUDE.md — Consumo do Governo Nominal Trimestral

## Project

Replication + extension of Santos et al. (2015) IPEA methodology for estimating
quarterly nominal government consumption in Brazil, using SICONFI RREO data as
high-frequency indicator and IBGE CNT annual totals as benchmark.

## Architecture

Single-method pipeline — no ensemble, no prediction intervals:
- **In-sample** (annual CNT benchmark available): `denton_proportional`
- **Nowcast** (no annual benchmark yet): `chow_lin` extrapolation via `fit_and_extrapolate`

Best spec fixed at `spec_estados_sal_ce` (27 estados, GND1 total — Pessoal e Encargos
Sociais). Note: code extracts GND1 total via `conta == "PESSOAL E ENCARGOS SOCIAIS"`,
not element-level filter. This includes inativos/pensões unlike the paper's original
filter (319011/319012/319013/319113). Empirically validated at MAPE 2.4–2.6%.

## Key files

| File | Purpose |
|------|---------|
| `pipeline.py` | Main entry point — all run modes |
| `config.py` | Paths + constants (no tuning params) |
| `scripts/build_siconfi_fiscal.py` | Build quarterly indicator from raw SICONFI |
| `scripts/fetch_latest_bim.py` | Download new SICONFI bimestre |
| `scripts/download_cnt.py` | Download CNT from IBGE SIDRA |
| `scripts/check_updates.py` | Check if new data is available |
| `scripts/representatividade.py` | Sample representativeness table |
| `src/disaggregation/denton.py` | denton_proportional, pro_rata |
| `src/disaggregation/regression_based.py` | chow_lin, fit_and_extrapolate |
| `src/validation/metrics.py` | RMSE, MAPE, Corr metrics |

## Monthly update workflow

```bash
python scripts/fetch_latest_bim.py          # download new SICONFI bimestre
python pipeline.py --update                 # re-estimate if new data found
```

## Full re-estimation

```bash
python scripts/download_cnt.py              # refresh CNT from IBGE SIDRA
python scripts/download_siconfi_rreo.py     # download full RREO history
python scripts/build_siconfi_fiscal.py      # build quarterly indicator
python pipeline.py --full                   # run complete pipeline
```

## Verification

```bash
python scripts/verify_data.py               # check data quality
python pipeline.py --check                  # check for new data only
```

## Conventions

- Monetary values always in R$ bilhões (billions)
- Period format: `YYYYQq` (e.g. `2025Q4`)
- All outputs are idempotent — re-running overwrites previous results
- `vintage_history.csv` is append-only, deduplicated on (run_date, quarter, method)
- Never modify `vintage_history.csv` manually

## What NOT to do

- Do not add ensemble methods — deliberately single-method architecture
- Do not add prediction intervals — removed due to calibration issues
- Do not add back `fernandez`, `litterman`, `ols_simple` — not needed
- Do not use `pro_rata` as the primary method — `denton_proportional` is the paper's method
