# Estimação Trimestral do Consumo Nominal do Governo

Replicação e extensão de Santos et al. (2015) — Nota Técnica IPEA — para estimação
trimestral do consumo final nominal das administrações públicas. Usa dados do SICONFI
(Tesouro Nacional) como indicador de alta frequência e as CNT anuais do IBGE como
benchmark. O melhor modelo alcança **MAPE ~2,4%** sobre 2015–2025 (Denton proporcional,
despesas de pessoal dos 27 estados).

## Metodologia

| Etapa | Método |
|-------|--------|
| In-sample (benchmark anual disponível) | Denton proporcional — minimiza Σ (q_t/p_t − q_{t-1}/p_{t-1})² |
| Nowcast (sem benchmark anual) | Chow-Lin extrapolação (AR1 GLS) |

Especificação: `spec_estados_sal_ce` — 27 estados, salários + contribuições efetivas
(RREO Anexo 1, elementos 319011/319012/319013/319113).

## Requisitos

```
Python 3.11+
pip install -r requirements.txt
```

## Atualização mensal (3 comandos)

```bash
python scripts/fetch_latest_bim.py   # baixar novo bimestre do SICONFI
python pipeline.py --update          # re-estimar se houver dados novos
cat output/UPDATE_REPORT.md          # ver resultado
```

## Instalação inicial

```bash
python scripts/download_cnt.py
python scripts/download_siconfi_rreo.py
python scripts/build_siconfi_fiscal.py
python pipeline.py --full
```

## Outputs principais

| Arquivo | Conteúdo |
|---------|----------|
| `output/tables/model_selected.csv` | Série estimada (in-sample + nowcast) |
| `output/tables/desvios_trimestre.csv` | CNT vs. estimativa por trimestre |
| `output/tables/nowcast.csv` | Trimestres provisórios (sem benchmark) |
| `output/tables/vintage_history.csv` | Histórico de runs e revisões |
| `output/UPDATE_REPORT.md` | Relatório do último run |

## Limitações

- **Municípios excluídos**: implementação usa apenas 27 estados + União (~70–80% do
  governo consolidado). Municípios têm sazonalidade diferente.
- **Consumo intermediário excluído**: representa ~28% da produção pública, omitido por
  falta de indicador trimestral confiável no SICONFI.
- **Benchmark defasado**: CNT anual publicada com ~9 meses de atraso. Trimestres do ano
  corrente são nowcast sem correção de benchmark — revisões de 2–5% são esperadas.
- **Sem intervalos de incerteza**: removidos por calibração problemática. A incerteza é
  avaliada pelas revisões históricas em `vintage_history.csv`.

## Conversão bimestral → trimestral (Santos et al. 2015)

| Bimestre | Meses | Alocação |
|----------|-------|----------|
| Bim 1 (jan-fev) | Jan, Fev | 100% → Q1 |
| Bim 2 (mar-abr) | Mar, Abr | 50% → Q1 + 50% → Q2 |
| Bim 3 (mai-jun) | Mai, Jun | 100% → Q2 |
| Bim 4 (jul-ago) | Jul, Ago | 100% → Q3 |
| Bim 5 (set-out) | Set, Out | 50% → Q3 + 50% → Q4 |
| Bim 6 (nov-dez) | Nov, Dez | 100% → Q4 |

## Referência

Santos, R. A. et al. (2015). *Uma Metodologia Simplificada de Estimação do Consumo do
Governo Nominal em Bases Trimestrais*. Nota Técnica IPEA.
