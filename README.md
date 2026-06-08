# Consumo do Governo Nominal Trimestral – Brasil (2010-2024)

Replicação, validação, modernização e superação da metodologia do paper:

> Santos et al. (2015) — **"Uma Metodologia Simplificada de Estimação do Consumo do Governo Nominal em Bases Trimestrais"**, Nota Técnica Ipea/Dimac.

---

## Objetivo

Construir a **melhor série possível** de Consumo do Governo Nominal Trimestral para o Brasil entre 2010 e o período mais recente disponível, utilizando dados públicos atuais, demonstrando empiricamente por que a especificação final é superior à metodologia original.

---

## Estrutura do Projeto

```
.
├── run.py                  # Ponto de entrada
├── pipeline.py             # Pipeline principal (6 fases)
├── config.py               # Configurações centrais
├── requirements.txt
├── src/
│   ├── data/
│   │   ├── ibge_api.py         # API IBGE CNT (com fallback)
│   │   ├── siconfi_api.py      # API SICONFI RREO (com fallback)
│   │   └── synthetic.py        # Dados sintéticos calibrados (paper Tabela 2)
│   ├── processing/
│   │   └── indicator.py        # Construção das séries indicadoras (13 specs + ext.)
│   ├── disaggregation/
│   │   ├── denton.py           # Denton proporcional/aditivo (estável para n=60)
│   │   └── regression_based.py # Chow-Lin, Fernandez, Litterman
│   ├── validation/
│   │   └── metrics.py          # RMSE, MAE, MAPE, Theil U, correlação
│   └── reporting/
│       ├── charts.py           # 6 gráficos + dashboard
│       └── reports.py          # Relatórios textuais (6 agentes)
├── data/
│   ├── raw/                # Dados brutos (cache de APIs)
│   ├── processed/
│   └── output/
└── output/
    ├── charts/             # 6 figuras matplotlib
    ├── tables/             # Métricas completas (CSV)
    └── series/             # Série final (CSV)
```

---

## Como Usar

```bash
# Instalação
pip install -r requirements.txt

# Pipeline completo (2010-2024)
python run.py

# Teste rápido (2010-2014)
python run.py --test

# Sem loop de otimização
python run.py --no-loop

# Período personalizado
python run.py --year-start 2010 --year-end 2024
```

---

## Metodologia

### Paper Original (Santos et al., 2015)

**Conceito**: Consumo do Governo ≈ Produção Total das Administrações Públicas
= Remunerações (Salários + Contrib. Efetivas + Contrib. Imputadas) + Consumo Intermediário

**Série selecionada (Série 13 — melhor, MSE=2.778)**:
- União: Despesas Liquidadas [Salários + Contrib. Efetiva + Contrib. Imputada]
- Estados (11, cobertura ~70%): Liquidado [Salários + Contrib. Efetiva]
- Municípios (17, cobertura ~27%): Liquidado [Salários + Contrib. Efetiva]
- Excluídos: Consumo Intermediário, Restos a Pagar

**Método de desagregação**: Denton (1971) proporcional com benchmark anual das CNT.

### Extensões Modernas

| Aspecto | Paper (2015) | Implementação Moderna |
|---------|-------------|----------------------|
| Cobertura estados | 11 (70%) | 27 (100% via SICONFI) |
| Cobertura municípios | 17 (27%) | >90% via SICONFI |
| Frequência fiscal | Bimestral (RREO) | Mensal disponível (SICONFI DCA) |
| Fonte estados | PTs + SISTN | SICONFI (unificado) |
| Benchmark | CNT Ref.2010 | CNT mais recente |

---

## Status

**Aguardando dados reais.** A infraestrutura de desagregação e validação está pronta.
Resultados serão publicados após download dos dados reais conforme `DATA_ACQUISITION.md`.

### Verificação contra o paper (Santos et al. 2015, Tabela 2)

Os valores abaixo constam do paper original e são usados como referência para
verificar a integridade dos dados após download:

| Trimestre | CNT real (R$ bi) | Série 13 estimada (R$ bi) | Desvio |
|-----------|-----------------|--------------------------|--------|
| 2011/3    | 199.00          | 188.30                   | -5.38% |
| 2010/1    | 163.11          | 169.90                   | +4.16% |
| 2014/4    | 324.89          | 325.00                   | +0.03% |

---

## Fontes de Dados

| Variável | Fonte Original | Fonte Moderna | Frequência |
|----------|---------------|---------------|------------|
| Sal.+CE União | SIGA Brasil | SICONFI / Portal Transparência | Mensal |
| CI Imputada União | RREO Anx.4 (SISTN) | SICONFI | Bimestral |
| Sal.+CE Estados | Portais de Transparência | SICONFI (27 estados) | Bimestral |
| Sal.+CE Municípios | RREO (SISTN) | SICONFI | Bimestral |
| Benchmark | CNT IBGE Ref.2010 | CNT IBGE mais recente | Trimestral |

**Nota**: Todos os downloads devem ser realizados fora do container conforme `DATA_ACQUISITION.md`.
Os arquivos resultantes devem ser colocados em `data/raw/` antes de executar o pipeline.

---

## Métodos de Desagregação Testados

| Método | Tipo | Descrição |
|--------|------|-----------|
| `denton_prop` | Denton | Minimiza Σ(Δ(q/p))² — **método do paper** |
| `denton_add` | Denton | Minimiza Σ(Δ(q-p))² |
| `denton_prop_d2` | Denton | Segunda diferença proporcional |
| `pro_rata` | Baseline | Distribuição proporcional simples |
| `chow_lin` | Regressão | GLS com erros AR(1) |
| `fernandez` | Regressão | GLS com erros I(1) (random walk) |
| `litterman` | Regressão | GLS com erros ARIMA(1,1,0) |

---

## Arquitetura Multi-Agente

O pipeline segue a estrutura de 6 agentes especializados definida na missão:

- **Agente 1** (Replication Engineer): Replicação exata do paper, verificação Tabela 2
- **Agente 2** (Data Collector): Mapeamento de fontes modernas (SICONFI, Portal Transparência)
- **Agente 3** (National Accounts Specialist): Mudanças pós-2015 (SISTN→SICONFI, SCN 2010)
- **Agente 4** (Econometric Validator): RMSE, MAE, MAPE, Theil U, correlação para 70 modelos
- **Agente 5** (Research Challenger): Evidências contra cada hipótese do paper
- **Agente 6** (Model Improvement Engineer): Testes de cobertura ampliada + métodos alternativos

---

## Referências

- Santos, C.H. et al. (2015). *Uma Metodologia Simplificada de Estimação do Consumo do Governo Nominal em Bases Trimestrais*. Nota Técnica Ipea.
- Denton, F.T. (1971). *Adjustment of monthly or quarterly series to annual totals*. JASA.
- Bloem, A.M., Dippelsman, R. & Mæhle, N.Ø. (2001). *Quarterly National Accounts Manual*. IMF.
- Chow, G.C. & Lin, A.L. (1971). *Best Linear Unbiased Interpolation, Distribution, and Extrapolation*. ReStat.
- Fernandez, R.B. (1981). *A Methodological Note on the Estimation of Time Series*. ReStat.
- Litterman, R.B. (1983). *A Random Walk, Markov Model for the Distribution of Time Series*. JBES.
