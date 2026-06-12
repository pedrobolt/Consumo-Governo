"""Tabular reporting for the Consumo do Governo pipeline."""

import numpy as np
import pandas as pd
from tabulate import tabulate


def print_deviation_table(cnt: pd.Series,
                          estimated: pd.Series,
                          model_name: str = "Série Estimada") -> None:
    """Print quarterly deviation table (CNT vs estimated) to stdout."""
    sep = "=" * 72
    print(f"\n{sep}\n  TABELA DE DESVIOS: CNT vs. {model_name}\n{sep}")

    df = pd.DataFrame({
        "CNT (bi)": cnt,
        model_name + " (bi)": estimated.reindex(cnt.index),
    }).dropna()

    df["Desvio (bi)"] = df[model_name + " (bi)"] - df["CNT (bi)"]
    df["Desvio (%)"]  = 100 * df["Desvio (bi)"] / df["CNT (bi)"]
    df = df.round(2)
    df.index = [f"{i.year}/T{i.quarter}" for i in df.index]

    print(tabulate(df, headers="keys", tablefmt="grid", floatfmt=".2f"))

    errs = df["Desvio (%)"].values
    print(
        f"\n  Desvio médio: {errs.mean():.2f}%  |  "
        f"Desvio abs. médio: {np.abs(errs).mean():.2f}%  |  "
        f"Máx. desvio abs.: {np.abs(errs).max():.2f}%"
    )
