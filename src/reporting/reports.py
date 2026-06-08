"""
Geração de relatórios textuais e tabulares do projeto.

Relatórios:
  1. Relatório metodológico (replicação do paper)
  2. Relatório de fontes de dados
  3. Tabela de desvios (Tabela 2 do paper)
  4. Tabela comparativa de métodos
  5. Relatório de melhorias
  6. Série final recomendada
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd
from tabulate import tabulate

from config import OUTPUT_TABLES, OUTPUT_SERIES, OUTPUT_REPORTS, YEAR_START, YEAR_END

# ──────────────────────────────────────────────────────────────────────────────
# Utilitários
# ──────────────────────────────────────────────────────────────────────────────

def _save_csv(df: pd.DataFrame, filename: str, index: bool = True) -> Path:
    path = OUTPUT_TABLES / filename
    df.to_csv(path, index=index, float_format="%.4f")
    return path


def _save_series(series: pd.Series, filename: str) -> Path:
    path = OUTPUT_SERIES / filename
    series.to_csv(path, header=True, float_format="%.4f")
    return path


def _print_section(title: str, width: int = 72) -> None:
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print(f"{'=' * width}")


# ──────────────────────────────────────────────────────────────────────────────
# Relatório 1: Metodológico
# ──────────────────────────────────────────────────────────────────────────────

def print_methodology_report() -> None:
    _print_section("AGENTE 1 — RELATÓRIO METODOLÓGICO (Replicação do Paper)")

    report = """
PAPER REPLICADO:
  Santos et al. (2015) — "Uma Metodologia Simplificada de Estimação do
  Consumo do Governo Nominal em Bases Trimestrais", Nota Técnica Ipea.

CONCEITO CENTRAL:
  Consumo do Governo ≈ Produção Total das Administrações Públicas
  = Valor Adicionado (Remunerações + EOB) + Consumo Intermediário
  Remunerações = Salários + Contrib. Efetivas + Contrib. Imputadas

MÉTODO:
  1. Construir série indicadora trimestral a partir de dados fiscais
  2. Usar método de Denton (1971) para alinhar ao total anual das CNT
  3. Comparar estimativa trimestral com CNT publicado

SÉRIE SELECIONADA (Série 13 — melhor do paper, MSE=2.778):
  - União:      Liquidado [Salários + Contrib.Efetiva + Contrib.Imputada]
  - Estados:    Liquidado [Salários + Contrib.Efetiva] (11 estados, ~70%)
  - Municípios: Liquidado [Salários + Contrib.Efetiva] (17 mun., ~27%)
  - Excluídos:  Consumo Intermediário, Restos a Pagar

FONTE DE DADOS ORIGINAL:
  União:          SIGA Brasil (Senado Federal)
  Estados:        Portais de Transparência Estaduais
  Municípios:     RREO via SISTN (bimestral, GND)
  Contribuições
  Imputadas:      RREO Anexo 4 (RPPS)
  Benchmark:      CNT anuais (IBGE, Ref. 2010)

CONVERSÃO BIMESTRAL → TRIMESTRAL (paper):
  Bim 2 (mar-abr): divide por 2 → ½ para Q1, ½ para Q2
  Bim 5 (set-out): divide por 2 → ½ para Q3, ½ para Q4
  Demais bimestres: alocados integralmente ao trimestre correspondente

PRECISÃO DO PAPER (2010-2014):
  Período 2010-2011: desvio máximo 5.38% (2011Q3)
  Período 2012-2014: desvio máximo < 3.11% (2013Q3)
  A partir de 2012:  precisão ≥ 97%

HIPÓTESES DO PAPER:
  H1: Pesos de componentes são constantes dentro de cada ano
  H2: Padrão sazonal dos RP pagos segue o padrão das despesas liquidadas
  H3: Cobertura parcial dos estados e municípios é representativa
  H4: Excluir CI e RP melhora a qualidade da série indicadora

LIMITAÇÕES IDENTIFICADAS (Agente 5 — Challenger):
  - Cobertura municipal ~27% é baixa (viés se municípios excluídos diferem)
  - Estimativa de depreciação (EOB) excluída sem alternativa
  - Pesos constantes dentro do ano ignoram sazonalidade intra-anual dos RPs
  - Método Denton proporcional assume razão q/p constante cross-years
  - SISTN substituído pelo SICONFI em 2015 (mudança de fonte)
"""
    print(report)


# ──────────────────────────────────────────────────────────────────────────────
# Relatório 2: Fontes de dados
# ──────────────────────────────────────────────────────────────────────────────

def print_data_sources_report() -> None:
    _print_section("AGENTE 2 — RELATÓRIO DE FONTES DE DADOS")

    headers = ["Variável", "Fonte Original", "Fonte Moderna", "Cobertura", "Obs."]
    rows = [
        ["Sal.+CE União", "SIGA Brasil", "SICONFI / Portal Transp.", "2010-pres.", "Mensal"],
        ["CI Imputada União", "RREO Anexo 4 (SISTN)", "RREO Anexo 4 (SICONFI)", "2010-pres.", "Bimestral"],
        ["Sal.+CE Estados", "PTs Estaduais", "SICONFI (todos os 27)", "2010-pres.", "Bimestral"],
        ["RP Estados", "RREO (SISTN)", "SICONFI", "2010-pres.", "Bimestral"],
        ["Pesos RP Estados", "EOE (STN)", "SICONFI DCA", "2010-pres.", "Anual"],
        ["Sal.+CE Municípios", "RREO bimestral", "SICONFI", "2010-pres.", "Bimestral"],
        ["Pesos GND Mun.", "FINBRA (STN)", "SICONFI / FINBRA", "2010-pres.", "Anual"],
        ["Benchmark Anual", "CNT IBGE Ref.2000/2010", "CNT IBGE Ref.2015+", "2010-pres.", "Trimestral"],
        ["Benchmark Trimestral", "CNT IBGE (validação)", "SIDRA Tabela 7321", "1996-pres.", "Trimestral"],
    ]
    print(tabulate(rows, headers=headers, tablefmt="grid"))

    print("""
MUDANÇAS METODOLÓGICAS RELEVANTES (Agente 3 — Especialista CN):

  2015: SISTN → SICONFI (impacto: base de dados unificada, +qualidade)
  2015: IBGE revisa CNT para referência 2010 com critério de LIQUIDAÇÃO
        (antes: empenho; agora: liquidação efetiva)
  2016: Novo SCN 2010 com TRU ampliadas disponíveis para estados
  2019: SICONFI com cobertura de 100% dos municípios (vs. ~60% antes)
  2021: IBGE revisa séries retroativas na mudança para Ref. 2015+
  2024: SICONFI publica DCA mensal para todos os entes (melhoria)

IMPACTO NAS HIPÓTESES DO PAPER:
  - Cobertura 70% (estados) → 100% disponível via SICONFI
  - Cobertura 27% (municípios) → >80% disponível via SICONFI
  - Bimestral → mensal disponível para muitos entes
  - FINBRA pesos anuais → DCA mensal (mais granularidade)
""")


# ──────────────────────────────────────────────────────────────────────────────
# Relatório 3: Tabela de desvios (réplica + extensão)
# ──────────────────────────────────────────────────────────────────────────────

def print_deviation_table(cnt: pd.Series,
                           estimated: pd.Series,
                           model_name: str = "Série Estimada") -> None:
    _print_section(f"TABELA DE DESVIOS: CNT vs. {model_name}")

    df = pd.DataFrame({
        "CNT (bi)": cnt,
        model_name + " (bi)": estimated.reindex(cnt.index),
    }).dropna()

    df["Desvio (bi)"] = df[model_name + " (bi)"] - df["CNT (bi)"]
    df["Desvio (%)"] = 100 * df["Desvio (bi)"] / df["CNT (bi)"]

    df = df.round(2)
    df.index = [f"{i.year}/{i.quarter}" for i in df.index]

    print(tabulate(df, headers="keys", tablefmt="grid", floatfmt=".2f"))

    # Estatísticas resumo
    errs = df["Desvio (%)"].values
    print(f"\n  Desvio médio: {errs.mean():.2f}%  |  "
          f"Desvio abs. médio: {np.abs(errs).mean():.2f}%  |  "
          f"Máx. desvio abs.: {np.abs(errs).max():.2f}%")


# ──────────────────────────────────────────────────────────────────────────────
# Relatório 4: Comparativo de métodos
# ──────────────────────────────────────────────────────────────────────────────

def print_methods_comparison(metrics_df: pd.DataFrame) -> None:
    _print_section("AGENTE 4 + 6 — COMPARATIVO DE MÉTODOS")

    cols = ["model", "RMSE", "MAE", "MAPE", "MaxPE", "Corr", "TheilU1", "TheilU2"]
    cols_avail = [c for c in cols if c in metrics_df.columns]
    df = metrics_df[cols_avail].copy()

    if "RMSE" in df.columns:
        df = df.sort_values("RMSE")
        df.index = range(1, len(df) + 1)
        df.index.name = "rank"

    print(tabulate(df, headers="keys", tablefmt="grid",
                   floatfmt=".4f", showindex=True))

    if "RMSE" in df.columns and len(df) >= 2:
        best_rmse = df["RMSE"].iloc[0]
        paper_rmse = df[df["model"].str.contains("serie13", case=False)]["RMSE"]
        if not paper_rmse.empty:
            melhora = (1 - best_rmse / paper_rmse.values[0]) * 100
            print(f"\n  Melhor modelo supera Serie13 do paper em: {melhora:.1f}% de RMSE")


# ──────────────────────────────────────────────────────────────────────────────
# Relatório 5: Hipóteses e desafios (Agente 5)
# ──────────────────────────────────────────────────────────────────────────────

def print_challenger_report() -> None:
    _print_section("AGENTE 5 — CHALLENGER: AVALIAÇÃO DAS HIPÓTESES")

    print("""
  HIPÓTESE 1: Por que excluir o consumo intermediário?
  ─────────────────────────────────────────────────────
  EVIDÊNCIA FAVORÁVEL:
    - CI municipal disponível só em GND 3 (mistura muitos componentes)
    - Peso dos elementos CI em GND 3 é inferior a 50% → estimativa ruidosa
    - Séries com CI tiveram RMSE MAIOR (Séries 7-12 do paper)
  EVIDÊNCIA CONTRÁRIA:
    - CI representa ~28% da produção total do governo (Tabela 1 do paper)
    - Excluir CI significa depender de representatividade das remunerações
    - Com SICONFI DCA (mensal, por elemento), qualidade do CI melhora
  CONCLUSÃO:
    - Para dados pré-2019: manter exclusão do paper (evidência empírica)
    - Para dados 2019+: testar inclusão com dados SICONFI DCA

  HIPÓTESE 2: Por que excluir restos a pagar?
  ─────────────────────────────────────────────
  EVIDÊNCIA FAVORÁVEL:
    - Peso dos RP relativos ao consumo é pequeno (~5-10% do total)
    - Dados de RP por elemento são de qualidade inferior nos PTs estaduais
    - Inclusão de RP adicionou ruído (RMSE piorou nas Séries 2,4,6)
  EVIDÊNCIA CONTRÁRIA:
    - Conceito correto da CNT é "liquidação efetiva" = inclui RP processados
    - Em anos com mudança política, RP podem ser materiais
    - SICONFI fornece dados de RP mais confiáveis que SISTN antigo
  CONCLUSÃO:
    - Manter exclusão no modelo base
    - Testar inclusão com dados SICONFI pós-2015

  HIPÓTESE 3: Representatividade da amostra (70%/27%) é suficiente?
  ──────────────────────────────────────────────────────────────────
  EVIDÊNCIA FAVORÁVEL:
    - Grandes estados (SP, RJ, MG) dominam o gasto estadual
    - 11 estados do paper cobrem as principais economias regionais
  EVIDÊNCIA CONTRÁRIA:
    - 27% dos municípios é claramente insuficiente
    - SICONFI tem cobertura de 100% dos estados e >90% dos municípios
  CONCLUSÃO:
    - AMPLIAR cobertura para todos os estados (27) e mais municípios
    - Esta é a melhoria mais imediata disponível com dados modernos

  HIPÓTESE 4: Denton proporcional é o melhor método?
  ────────────────────────────────────────────────────
  EVIDÊNCIA FAVORÁVEL:
    - Recomendado pelo Manual QNA do FMI (Bloem et al. 2001)
    - Usado pelo IBGE no cálculo oficial das CNT
    - Preserva padrão sazonal do indicador
  EVIDÊNCIA CONTRÁRIA:
    - Quando indicador tem erros sistemáticos, proporcional amplifica
    - Chow-Lin permite regressão com constante (corrige escala)
    - Fernandez é mais robusto com indicadores imprecisos
  CONCLUSÃO:
    - Testar todos os métodos empiricamente neste estudo
    - Denton proporcional segue como benchmark
""")


# ──────────────────────────────────────────────────────────────────────────────
# Relatório 6: Melhorias (Agente 6)
# ──────────────────────────────────────────────────────────────────────────────

def print_improvements_report(metrics_df: pd.DataFrame) -> None:
    _print_section("AGENTE 6 — RELATÓRIO DE MELHORIAS")

    print("""
  MELHORIAS TESTADAS:

  M1. Cobertura ampliada (27 estados)
      Hipótese: mais entes → indicador mais representativo
      Status: Testado via série "moderna_a"

  M2. Método Chow-Lin (vs. Denton proporcional)
      Hipótese: regressão GLS captura melhor a relação indicador-variável
      Status: Testado via "chow_lin_*"

  M3. Método Fernandez (erros I(1))
      Hipótese: robustez quando indicador tem erros não estacionários
      Status: Testado via "fernandez_*"

  M4. Método Litterman (ARIMA(1,1,0))
      Hipótese: blend de Chow-Lin e Fernandez pode superar ambos
      Status: Testado via "litterman_*"

  M5. Denton segunda diferença
      Hipótese: maior suavidade temporal melhora ajuste
      Status: Testado via "denton_prop_d2"

  M6. Inclusão de consumo intermediário (dados SICONFI DCA)
      Hipótese: CI via SICONFI tem qualidade superior ao dado RREO/GND
      Status: Testado via "moderna_b"
""")

    if not metrics_df.empty and "RMSE" in metrics_df.columns:
        best = metrics_df.sort_values("RMSE").iloc[0]
        print(f"  MELHOR ESPECIFICAÇÃO: {best['model']}")
        print(f"  RMSE: {best['RMSE']:.4f} | MAPE: {best.get('MAPE', 'N/A'):.2f}% | "
              f"Corr: {best.get('Corr', 0):.4f}")


# ──────────────────────────────────────────────────────────────────────────────
# Exportar série final
# ──────────────────────────────────────────────────────────────────────────────

def export_final_series(cnt: pd.Series,
                         best_series: pd.Series,
                         all_series: Dict[str, pd.Series]) -> Path:
    """Salva a série final e todas as variantes em CSV."""

    df = pd.DataFrame({
        "cnt_publicada_bi": cnt,
        "melhor_estimativa_bi": best_series.reindex(cnt.index),
    })

    for name, s in all_series.items():
        df[f"estimativa_{name}_bi"] = s.reindex(cnt.index)

    df.index.name = "data"
    path = _save_csv(df, "serie_final_consumo_governo.csv")
    print(f"\n  Série final exportada: {path}")
    return path


# ──────────────────────────────────────────────────────────────────────────────
# Relatório completo
# ──────────────────────────────────────────────────────────────────────────────

def generate_full_report(cnt: pd.Series,
                          best_series: pd.Series,
                          all_series: Dict[str, pd.Series],
                          metrics_df: pd.DataFrame,
                          model_name: str = "Serie13_DentonProp") -> None:
    """Gera todos os relatórios textuais em sequência."""

    print(f"\n{'#' * 72}")
    print("  PROJETO: CONSUMO DO GOVERNO NOMINAL TRIMESTRAL – BRASIL")
    print(f"  Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Período:   {YEAR_START}Q1 – {YEAR_END}Q4")
    print(f"{'#' * 72}")

    print_methodology_report()
    print_data_sources_report()
    print_deviation_table(cnt, best_series, model_name)
    print_methods_comparison(metrics_df)
    print_challenger_report()
    print_improvements_report(metrics_df)

    export_final_series(cnt, best_series, all_series)

    _print_section("CRITÉRIOS DE SUCESSO ATINGIDOS")
    if not metrics_df.empty and "MAPE" in metrics_df.columns:
        best_mape = metrics_df["MAPE"].min()
        best_corr = metrics_df["Corr"].max() if "Corr" in metrics_df.columns else 0
        best_rmse = metrics_df["RMSE"].min()
        print(f"  MAPE mínimo:  {best_mape:.2f}%  (target: < 2%)"
              f"  {'✓ ATINGIDO' if best_mape < 2 else '✗ não atingido'}")
        print(f"  Corr máxima:  {best_corr:.4f}  (target: > 0.98)"
              f"  {'✓ ATINGIDO' if best_corr > 0.98 else '✗ não atingido'}")
        print(f"  RMSE mínimo:  {best_rmse:.4f} R$ bi")
