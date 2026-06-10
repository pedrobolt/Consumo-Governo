# Estimação Trimestral do Consumo Nominal do Governo

Replicação e extensão da metodologia do IPEA — Santos et al. (2015) — para estimação do
consumo final nominal das administrações públicas em bases trimestrais, atualizada para o
período 2015-2024 com dados do SICONFI (Tesouro Nacional) e CNT/IBGE. O pipeline baixa
automaticamente os dados via API, constrói séries indicadoras de despesas de pessoal por
esfera de governo, aplica seis métodos de desagregação temporal e valida as estimativas
contra a série publicada pelo IBGE. O melhor modelo alcança **MAPE 2,39% e correlação
0,9912** sobre 40 trimestres (2015Q1–2024Q4), usando despesas de pessoal dos 27 estados
como indicador temporal com o método Chow-Lin.

---

## Resultado principal

| Modelo | RMSE (R$ bi) | MAPE | Corr |
|--------|-------------|------|------|
| `spec_estados_sal_ce_litterman` | 12,22 | **2,25%** | 0,9938 |
| `spec_estados_sal_ce_chow_lin`  | 12,26 | 2,35% | 0,9937 |
| `spec_estados_sal_ce_fernandez` | 12,79 | 2,40% | 0,9934 |

Avaliacao sobre 44 trimestres (2015Q1-2025Q4) contra CNT publicada (IBGE FTP).

---

## Nowcast

O nowcast de 2026Q2 e **estimativa provisoria**. O pipeline extrapola alem do
ultimo benchmark anual publicado (2025) usando o relacionamento estimado entre
o indicador fiscal (spec03 Uniao+estados) e o consumo trimestral.

| Trimestre | Litterman (R$ bi) | Chow-Lin (R$ bi) | Status |
|-----------|------------------|-----------------|--------|
| 2026Q1 | 557,30 | 578,80 | Verificado - CNT publicado: **598,99** (erro: -7,0% / -3,4%) |
| **2026Q2** | **615,90** | **641,14** | **PROVISIONAL** - sera benchmarkado quando IBGE publicar |

**Cobertura do indicador para 2026Q2**: apenas Bim2 (mar-abr) disponivel no
SICONFI em 2026-06-09. Bim3 (mai-jun) ainda nao publicado. O valor parcial de
Bim2 foi escalado pelo ratio historico medio Bim2x0,5 / Q2_completo = 0,3136.

Esta estimativa sera automaticamente revisada quando Bim3 2026 for publicado
pelo Tesouro Nacional (previsao: agosto 2026).

Para atualizar o nowcast quando Bim3 for publicado:

```bash
python scripts/fetch_2026_bim.py   # busca Bim3 quando disponivel
python scripts/build_siconfi_fiscal.py
python scripts/nowcast_2026q2.py
```

---

## Estrutura do projeto

```
.
├── pipeline.py                  # Ponto de entrada principal
├── config.py                    # Configurações (anos, caminhos, constantes)
├── requirements.txt
├── scripts/
│   ├── download_cnt.py          # Baixa CNT trimestral do FTP do IBGE
│   ├── download_siconfi_rreo.py # Baixa RREO Anexo 1 (pessoal) via SICONFI API
│   ├── download_siconfi_rpps.py # Baixa RREO Anexo 4 (contrib. imputada)
│   ├── build_siconfi_fiscal.py  # Converte bimestral->trimestral, monta specs
│   ├── verify_data.py           # Verificacoes de integridade dos dados
│   └── make_outputs.py          # Gera tabelas e graficos finais
├── src/
│   ├── disaggregation/
│   │   ├── denton.py            # Denton proporcional/aditivo/2a diferenca + pro-rata
│   │   └── regression_based.py  # Chow-Lin, Fernandez, Litterman
│   ├── validation/
│   │   └── metrics.py           # RMSE, MAE, MAPE, Theil U, correlacao
│   └── reporting/
│       ├── charts.py            # Graficos matplotlib
│       └── reports.py           # Relatorios textuais
├── output/
│   ├── tables/
│   │   ├── ranking_final.csv    # 40 modelos ranqueados por MAPE
│   │   ├── diagnostico_gap.csv  # Metricas por janela temporal
│   │   └── desvios_trimestre.csv
│   └── charts/
│       ├── cnt_vs_best_estimate.png
│       └── desvios_percentuais.png
└── data/
    └── raw/                     # Gerado pelos scripts de download (nao versionado)
```

---

## Como reproduzir

### 1. Dependencias

```bash
pip install -r requirements.txt
```

### 2. Download dos dados

```bash
# CNT trimestral (IBGE FTP -- ~5 MB)
python scripts/download_cnt.py

# RREO Anexo 1 -- pessoal e encargos (~2 430 requisicoes, ~10 min)
python scripts/download_siconfi_rreo.py --entes uniao,estados

# RREO Anexo 4 -- contribuicao imputada RPPS
python scripts/download_siconfi_rpps.py --dump-raw
```

### 3. Construir indicadores e validar

```bash
python scripts/build_siconfi_fiscal.py
python scripts/verify_data.py
```

### 4. Executar pipeline completo

```bash
python pipeline.py
```

### 5. Gerar tabelas e graficos

```bash
python scripts/make_outputs.py
```

---

## Fontes de dados

| Variavel | Fonte | Endpoint |
|----------|-------|---------|
| Consumo final das administracoes publicas | IBGE CNT | FTP IBGE -- `Tab_Compl_CNT.zip` |
| Pessoal e encargos -- Uniao e estados | SICONFI / Tesouro Nacional | `apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo` |
| Contribuicao imputada RPPS -- Uniao | SICONFI Anexo 4 | mesma API, `no_co_tipo_demonstrativo=RREO - Anexo 4` |

Cobertura: 2015-2024 (SICONFI disponivel a partir de 2015). CNT usada como benchmark anual
desde 2010 para calibrar os metodos de desagregacao.

---

## Metodologia

Baseada em Santos et al. (2015), com as seguintes extensoes:

- **Cobertura ampliada**: todos os 27 estados via SICONFI (paper usava 11 estados)
- **Serie temporal estendida**: 2015-2025 (paper cobre ate 2014)
- **Metodos adicionais**: Chow-Lin, Fernandez e Litterman alem do Denton proporcional
- **Conversao bimestral->trimestral corrigida**: mapeamento calendario correto
  (Bim6=Nov-Dez -> 100% Q4)
- **Gap pre-2018 resolvido**: API SICONFI usa formato de coluna diferente em 2015-2017
  (`"No Bimestre"` em vez de `"DESPESAS LIQUIDADAS NO BIMESTRE"`); script detecta ambos

### Arquitetura hibrida: Denton (in-sample) + ensemble (nowcast)

O pipeline usa metodos distintos dependendo da disponibilidade do benchmark anual:

| Periodo | Metodo | Justificativa |
|---------|--------|---------------|
| 2015Q1-2025Q4 (benchmark disponivel) | **Denton-Cholette proporcional** | Parcimonioso (sem rho), MAPE 2.57% vs 2.65% do Chow-Lin; mais proximo da metodologia IPEA |
| 2026Q1+ (sem benchmark anual) | **Ensemble Chow-Lin + Litterman** | Extrapolam alem do ultimo benchmark; IC 90% = estimativa +/- 1.645 x RMSE |

**Por que nao usar Chow-Lin in-sample?** Dummies de quebra estrutural mostraram que o
parametro rho absorve as quebras (sobe de 0.84 para 0.99 com dummies COVID+fiscal+transicao)
sem reduzir o MAPE. Denton evita esse grau de liberdade espurio.

**Trimestres-problema (|desvio| > 5%):** os maiores erros ocorrem em 2020Q2 (-7.6%,
COVID), 2020Q4 (+7.2%, rebound), e 2016Q3-Q4 (ajuste fiscal). A causa e a divergencia
entre competencia (CNT/IBGE, regime de accrual) e caixa (SICONFI, liquidado) em periodos
de choque fiscal. Denton e Chow-Lin erram quasi-identicamente nestes trimestres
(ex: 2020Q2 Chow-Lin -7.60%, Denton -7.13%), confirmando que o problema esta no
indicador, nao no metodo. Sao uma limitacao estrutural conhecida, nao uma falha de
metodologia.

---

## Referencias

- **Santos, C.H. et al.** (2015). *Uma Metodologia Simplificada de Estimacao do Consumo do
  Governo Nominal em Bases Trimestrais*. Carta de Conjuntura no. 27, IPEA/Dimac.
- Denton, F.T. (1971). Adjustment of monthly or quarterly series to annual totals. *JASA*.
- Chow, G.C. & Lin, A.L. (1971). Best Linear Unbiased Interpolation, Distribution, and
  Extrapolation of Time Series by Related Series. *Review of Economics and Statistics*.
- Fernandez, R.B. (1981). A Methodological Note on the Estimation of Time Series. *ReStat*.
- Litterman, R.B. (1983). A Random Walk, Markov Model for the Distribution of Time Series.
  *Journal of Business & Economic Statistics*.
- Bloem, A.M., Dippelsman, R. & Maehloe, N.O. (2001). *Quarterly National Accounts Manual*. IMF.
