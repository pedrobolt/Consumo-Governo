# Real Data Acquisition Plan
## Consumo do Governo Nominal Trimestral — Brasil (2010–2024)

**Status:** This environment has a network allowlist that blocks all Brazilian government
domains. Every URL below must be downloaded on a machine with unrestricted internet access
and the resulting files placed in `data/raw/` before running `pipeline.py`.

---

## Network Environment Note

This container returns `403 Host not in allowlist` for all Brazilian government domains:
- `servicodados.ibge.gov.br`
- `apidatalake.tesouro.gov.br`
- `siconfi.tesouro.gov.br`
- `api.portaldatransparencia.gov.br`
- `www12.senado.leg.br`
- `ftp.ibge.gov.br`

GitHub (`github.com`) and PyPI (`pypi.org`) are reachable.
**All data downloads must be performed outside this container.**

---

## Variables Required to Replicate Santos et al. (2015)

### Variable 1: Consumo Final das Administrações Públicas — CNT trimestral (benchmark)

| Attribute | Value |
|-----------|-------|
| **Role** | Benchmark / dependent variable for validation |
| **Concept** | Consumo Final das Administrações Públicas, valores correntes (R$ milhões) |
| **Source** | IBGE — Contas Nacionais Trimestrais (CNT) |
| **Series ID** | SIDRA Tabela 2072, Variável 933 (referência 2010) |
| **Preferred** | SIDRA Tabela 7321, Variável 11707 (SCN 2010, mais recente disponível) |
| **Frequency** | Trimestral |
| **Coverage** | 2010Q1 – presente |
| **Unit** | R$ milhões correntes (converter para R$ bilhões: ÷ 1000) |
| **Authentication** | Nenhuma |
| **Download method — API** | `GET https://servicodados.ibge.gov.br/api/v3/agregados/7321/periodos/{periodos}/variaveis/11707?localidades=N1[all]` onde `periodos` = `20101\|20102\|20103\|20104\|20111\|...` |
| **Download method — bulk** | IBGE disponibiliza arquivos Excel em: `https://www.ibge.gov.br/estatisticas/economicas/contas-nacionais/9300-contas-nacionais-trimestrais.html` → "Tabelas completas" → "Valores correntes" |
| **File format** | JSON (API) ou XLSX (bulk) |
| **Target file** | `data/raw/cnt_quarterly.csv` |
| **Expected CSV format** | `periodo,cnt_nominal_bi` (ex: `2010Q1,163.11`) |
| **Paper values (Table 2, 2010–2014)** | Usados para verificação: ver `src/data/ibge_api.py::CNT_PAPER` |

#### Download script (executar fora do container):

```python
# save as: scripts/download_cnt.py
import requests, json, csv, sys

periods = []
for y in range(2010, 2025):
    for q in range(1, 5):
        periods.append(f"{y}0{q}")
period_str = "|".join(periods)

url = (f"https://servicodados.ibge.gov.br/api/v3/agregados/7321"
       f"/periodos/{period_str}/variaveis/11707?localidades=N1[all]")

r = requests.get(url, timeout=60)
r.raise_for_status()
data = r.json()[0]["resultados"][0]["series"][0]["serie"]

rows = []
for period_code, value in sorted(data.items()):
    if value in ("-", "..."):
        continue
    year = int(period_code[:4])
    quarter = int(period_code[4])
    rows.append({"periodo": f"{year}Q{quarter}",
                 "cnt_nominal_bi": float(value) / 1000})

with open("data/raw/cnt_quarterly.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["periodo", "cnt_nominal_bi"])
    w.writeheader()
    w.writerows(rows)

print(f"Saved {len(rows)} quarters to data/raw/cnt_quarterly.csv")
```

---

### Variable 2: Salários e Contribuições Efetivas — União Federal

| Attribute | Value |
|-----------|-------|
| **Role** | Componente principal do indicador fiscal |
| **Concept** | Despesas liquidadas: Pessoal e Encargos Sociais (GND 1), elementos 319011 (salários), 319013/319113 (contrib. efetivas) |
| **Source** | Portal da Transparência / SIGA Brasil |
| **Primary source** | SIGA Brasil (Senado Federal) — `https://www12.senado.leg.br/orcamento/sigabrasil` |
| **Alternative source** | Portal da Transparência — `https://portaldatransparencia.gov.br/download-de-dados/despesas` |
| **Frequency** | Mensal (agregar para trimestral) |
| **Coverage** | Janeiro 2010 – presente, Poder Executivo Federal |
| **Authentication** | Portal Transparência: chave de API gratuita em `https://portaldatransparencia.gov.br/api-de-dados/cadastrar-email` |
| **Download method — Portal Transparência** | Arquivos CSV mensais em `https://portaldatransparencia.gov.br/download-de-dados/despesas/{AAAAMM}` |
| **Download method — SIGA Brasil** | Interface web com filtros por UO, GND, elemento de despesa; exportação CSV/XLSX |
| **File format** | CSV (Portal Transparência), XLSX/CSV (SIGA Brasil) |
| **Filters required** | Esfera: Federal; GND: 1 (Pessoal); Elemento: 319011, 319013, 319113; Modalidade de aplicação: liquidado |
| **Target file** | `data/raw/uniao_pessoal_mensal.csv` |
| **Expected CSV format** | `ano,mes,elemento,valor_bi` |

#### Download — Portal da Transparência (bulk CSV):

```bash
# Baixar despesas mensais 2010-2024 (executar fora do container)
for YEAR in $(seq 2010 2024); do
  for MONTH in 01 02 03 04 05 06 07 08 09 10 11 12; do
    URL="https://portaldatransparencia.gov.br/download-de-dados/despesas/${YEAR}${MONTH}"
    wget -nc -P data/raw/portal_transparencia/ "$URL"
  done
done
# Filtrar colunas: Função=04 (Administração), GND=1, Elemento=319011|319013|319113
```

---

### Variable 3: Contribuições Imputadas (RPPS) — União Federal

| Attribute | Value |
|-----------|-------|
| **Role** | Componente do indicador (paper: "contrib. imputadas") |
| **Concept** | RREO Anexo 4 — Demonstrativo das Receitas e Despesas Previdenciárias — RPPS |
| **Source** | SICONFI — Tesouro Nacional |
| **Frequency** | Bimestral (6 bimestres/ano) |
| **Coverage** | 2015–presente via SICONFI; pré-2015 via SISTN (arquivos históricos STN) |
| **Authentication** | Nenhuma (acesso público) |
| **Download method — API** | `GET https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio={ANO}&nr_periodo={BIM}&co_tipo_demonstrativo=RREO&no_co_tipo_demonstrativo=RREO+-+Anexo+4&id_ente={IBGE_CODE}` |
| **Download method — arquivo** | Portal SICONFI: `https://siconfi.tesouro.gov.br/siconfi/pages/public/declaracao/declaracao_list.jsf` → filtrar por ano, ente, tipo RREO, Anexo 4 → exportar CSV |
| **File format** | JSON (API), CSV/XLSX (portal) |
| **Target file** | `data/raw/siconfi_rpps_bimestral.csv` |
| **Expected CSV format** | `ano,bimestre,id_ente,uf,valor_bi` |

---

### Variable 4: Salários e Contribuições Efetivas — 27 Estados

| Attribute | Value |
|-----------|-------|
| **Role** | Componente do indicador — esfera estadual |
| **Concept** | RREO Anexo 1 — Demonstrativo da Execução Orçamentária — GND 1 (Pessoal e Encargos) |
| **Source** | SICONFI — Tesouro Nacional |
| **Frequency** | Bimestral |
| **Coverage** | 27 UFs, 2015–presente; 2010–2014 disponível parcialmente |
| **Authentication** | Nenhuma |
| **Download method — API** | `GET https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo?an_exercicio={ANO}&nr_periodo={1..6}&co_tipo_demonstrativo=RREO&no_co_tipo_demonstrativo=RREO+-+Anexo+1&id_ente={IBGE_CODE_ESTADO}` |
| **Download method — arquivo (recomendado)** | SICONFI → Consultas → RREO → selecionar todos os estados, ano, bimestre → exportar; **OU** usar API em loop por estado/ano/bimestre |
| **IBGE codes** | AC=12, AL=27, AM=13, AP=16, BA=29, CE=23, DF=53, ES=32, GO=52, MA=21, MG=31, MS=50, MT=51, PA=15, PB=25, PE=26, PI=22, PR=41, RJ=33, RN=24, RO=11, RR=14, RS=43, SC=42, SE=28, SP=35, TO=17 |
| **File format** | JSON (API), CSV (portal) |
| **Target file** | `data/raw/siconfi_estados_bimestral.csv` |
| **Expected CSV format** | `ano,bimestre,id_ente,uf,cd_grupo,vl_liquidado_bi` |

#### Download script (estados via API — executar fora do container):

```python
# save as: scripts/download_siconfi_estados.py
import requests, csv, time

ESTADOS = {
    "AC":12,"AL":27,"AM":13,"AP":16,"BA":29,"CE":23,"DF":53,"ES":32,
    "GO":52,"MA":21,"MG":31,"MS":50,"MT":51,"PA":15,"PB":25,"PE":26,
    "PI":22,"PR":41,"RJ":33,"RN":24,"RO":11,"RR":14,"RS":43,"SC":42,
    "SE":28,"SP":35,"TO":17
}
BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"

rows = []
for year in range(2010, 2025):
    for bim in range(1, 7):
        for uf, code in ESTADOS.items():
            url = (f"{BASE}?an_exercicio={year}&nr_periodo={bim}"
                   f"&co_tipo_demonstrativo=RREO"
                   f"&no_co_tipo_demonstrativo=RREO+-+Anexo+1"
                   f"&id_ente={code}")
            try:
                r = requests.get(url, timeout=30)
                if r.status_code == 200:
                    for item in r.json().get("items", []):
                        gnd = str(item.get("cd_grupo", ""))
                        if gnd == "1":
                            vl = float(item.get("vl_despesa_liquidada", 0) or 0)
                            rows.append({
                                "ano": year, "bimestre": bim,
                                "id_ente": code, "uf": uf,
                                "cd_grupo": gnd,
                                "vl_liquidado_bi": vl / 1e9
                            })
                time.sleep(0.2)  # respeitar rate limit
            except Exception as e:
                print(f"Erro {uf} {year} bim{bim}: {e}")

with open("data/raw/siconfi_estados_bimestral.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["ano","bimestre","id_ente","uf","cd_grupo","vl_liquidado_bi"])
    w.writeheader()
    w.writerows(rows)
print(f"Saved {len(rows)} records")
```

---

### Variable 5: Salários e Contribuições Efetivas — Municípios

| Attribute | Value |
|-----------|-------|
| **Role** | Componente do indicador — esfera municipal |
| **Concept** | RREO Anexo 1 — GND 1 (Pessoal e Encargos) |
| **Source** | SICONFI — Tesouro Nacional |
| **Frequency** | Bimestral |
| **Coverage** | >5.000 municípios, cobertura ~90% pós-2019; ~60% em 2010–2014 |
| **Authentication** | Nenhuma |
| **Download method — API** | Idêntico ao estados, mas `id_ente` = código IBGE do município (7 dígitos) |
| **Download method — arquivo (recomendado)** | SICONFI → Consultas → RREO → filtrar por UF → exportar todos municípios da UF de uma vez |
| **Alternative** | FINBRA (Finanças do Brasil) — STN disponibiliza dados anuais consolidados: `https://siconfi.tesouro.gov.br/siconfi/pages/public/finbra/finbra_list.jsf` |
| **File format** | JSON (API), CSV (FINBRA) |
| **Note** | Paper original usou apenas 17 municípios (cobertura ~27%). Com SICONFI completo, cobertura >90% é possível. |
| **Target file** | `data/raw/siconfi_municipios_bimestral.csv` |

---

### Variable 6: Dados pré-2015 (SISTN — legado)

| Attribute | Value |
|-----------|-------|
| **Role** | Cobertura 2010–2014 para estados e municípios |
| **Concept** | RREO histórico do SISTN (predecesssor do SICONFI) |
| **Source** | STN — arquivos históricos |
| **Frequency** | Bimestral |
| **Coverage** | 2002–2014 |
| **Authentication** | Nenhuma |
| **Download method** | Arquivos legados em `https://siconfi.tesouro.gov.br/siconfi/pages/public/declaracao/declaracao_list.jsf` — filtrar anos anteriores a 2015 |
| **Note** | Paper usou SISTN para 2010–2014. Para replicação exata, é necessário comparar se os dados do SICONFI para período retroativo coincidem com SISTN. |

---

### Variable 7: SIGA Brasil — Execução Orçamentária da União (alternativa)

| Attribute | Value |
|-----------|-------|
| **Role** | Alternativa ao Portal da Transparência para dados da União |
| **Concept** | Execução orçamentária federal por elemento de despesa |
| **Source** | Senado Federal — SIGA Brasil |
| **URL** | `https://www12.senado.leg.br/orcamento/sigabrasil` |
| **Frequency** | Mensal |
| **Coverage** | 2000–presente |
| **Authentication** | Nenhuma (acesso público via interface web) |
| **Download method** | Interface web: Orçamento > Execução > filtros: Função=04, Elemento=319011 → exportar CSV |
| **File format** | CSV/XLSX |
| **Note** | O SIGA Brasil foi a fonte original do paper para dados da União. |

---

## Summary Table

| # | Variável | Fonte | Método download | Autenticação | Formato |
|---|----------|-------|-----------------|--------------|---------|
| 1 | CNT nominal trimestral (benchmark) | IBGE SIDRA T7321 | API REST ou bulk XLSX | Nenhuma | JSON / XLSX |
| 2 | Sal.+CE União (liquidado) | Portal Transparência | Arquivos CSV mensais | Chave API gratuita | CSV |
| 3 | CI Imputada União (RPPS) | SICONFI Anexo 4 | API REST ou portal | Nenhuma | JSON / CSV |
| 4 | Sal.+CE 27 Estados | SICONFI Anexo 1 | API REST em loop | Nenhuma | JSON / CSV |
| 5 | Sal.+CE Municípios (>90%) | SICONFI Anexo 1 ou FINBRA | API REST ou FINBRA bulk | Nenhuma | JSON / CSV |
| 6 | Dados 2010–2014 (legado) | SISTN / SICONFI retroativo | Portal SICONFI | Nenhuma | CSV |
| 7 | Sal.+CE União (alternativa) | SIGA Brasil | Interface web | Nenhuma | CSV / XLSX |

---

## Bimestral → Trimestral Conversion (paper methodology)

Once SICONFI bimestral data is downloaded, apply this conversion in `src/processing/indicator.py`:

| Bimestre | Meses | Trimestre |
|----------|-------|-----------|
| Bim 1 (jan-fev) | Jan, Fev | → 100% Q1 |
| Bim 2 (mar-abr) | Mar, Abr | → 50% Q1 + 50% Q2 |
| Bim 3 (mai-jun) | Mai, Jun | → 100% Q2 |
| Bim 4 (jul-ago) | Jul, Ago | → 50% Q2 + 50% Q3 |
| Bim 5 (set-out) | Set, Out | → 100% Q3 |
| Bim 6 (nov-dez) | Nov, Dez | → 50% Q3 + 50% Q4 |

---

## Expected Output Files in `data/raw/`

| File | Source | Rows (approx.) |
|------|--------|---------------|
| `cnt_quarterly.csv` | IBGE SIDRA | 60 (2010Q1–2024Q4) |
| `uniao_pessoal_mensal.csv` | Portal Transparência | ~180 rows (1/mês) |
| `siconfi_rpps_bimestral.csv` | SICONFI Anexo 4 | ~90 rows (6 bim × 15 anos) |
| `siconfi_estados_bimestral.csv` | SICONFI Anexo 1 | ~2.430 (27 estados × 6 bim × 15 anos) |
| `siconfi_municipios_bimestral.csv` | SICONFI Anexo 1 | ~450.000+ (todos municípios) |

---

## Verification Against Paper (Table 2)

After downloading, verify by running:
```bash
python3 scripts/verify_paper_table2.py
```

Expected values (Santos et al. 2015, Tabela 2):

| Trimestre | CNT real (R$ bi) | Série estimada (R$ bi) | Desvio |
|-----------|-----------------|----------------------|--------|
| 2011Q3 | 199.00 | 188.30 | -5.38% |
| 2010Q1 | 163.11 | 169.90 | +4.16% |
| 2014Q4 | 324.89 | 325.00 | +0.03% |
| 2010–2014 max | — | — | 5.38% |

---

## Next Steps After Download

1. Place all files in `data/raw/`
2. Run `python3 scripts/verify_paper_table2.py` to confirm data integrity
3. Run `python3 pipeline.py` — will fail clearly with `FileNotFoundError` if any file is missing
4. All disaggregation infrastructure (`src/disaggregation/denton.py`, `regression_based.py`) is ready
5. All validation infrastructure (`src/validation/metrics.py`) is ready
