"""
ui/formatacao.py — Formatação de números em PT-BR para exibição no Streamlit.
"""
from __future__ import annotations

import pandas as pd


# ---------------------------------------------------------------------------
# Formatadores individuais
# ---------------------------------------------------------------------------

def fmt_numero(n: int | float | None) -> str:
    """
    Formata um número inteiro ou float com separador de milhar PT-BR.

    Exemplos
    --------
    >>> fmt_numero(1234567)
    '1.234.567'
    >>> fmt_numero(None)
    '—'
    """
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "—"
    try:
        # Converte para int se não houver parte decimal significativa
        valor = int(n) if float(n) == int(float(n)) else float(n)
        if isinstance(valor, int):
            # Usa format com locale PT-BR manual: ponto como separador de milhar
            return f"{valor:,}".replace(",", ".")
        else:
            parte_inteira = int(valor)
            parte_decimal = round(abs(valor - parte_inteira) * 100)
            return f"{parte_inteira:,}".replace(",", ".") + f",{parte_decimal:02d}"
    except (TypeError, ValueError):
        return str(n)


def fmt_pct(p: float | None) -> str:
    """
    Formata um percentual em PT-BR.

    Exemplos
    --------
    >>> fmt_pct(12.34)
    '12,34%'
    >>> fmt_pct(None)
    '—'
    """
    if p is None or (isinstance(p, float) and pd.isna(p)):
        return "—"
    try:
        return f"{float(p):.2f}%".replace(".", ",")
    except (TypeError, ValueError):
        return str(p)


# ---------------------------------------------------------------------------
# Aplicação em massa no DataFrame de resultado
# ---------------------------------------------------------------------------

# Colunas numéricas inteiras do DataFrame de conflito (aliases em PT)
_COLUNAS_INTEIRAS: list[str] = [
    "Votos no Bairro",
    "Total Votos Bairro",
    "Posição Bairro",
    "Candidatos Partido/Bairro",
    "Candidatos Fed./Bairro",
]

# Colunas percentuais
_COLUNAS_PCT: list[str] = [
    "% Bairro",
]


def aplicar_formatacao_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Retorna uma cópia do DataFrame com colunas numéricas formatadas em PT-BR.

    Apenas as colunas presentes no DataFrame serão transformadas
    (evita KeyError se a query retornar subconjunto de colunas).

    Parameters
    ----------
    df : pd.DataFrame
        DataFrame original retornado pela query de conflito.

    Returns
    -------
    pd.DataFrame
        Cópia com valores numéricos substituídos por strings formatadas.
    """
    if df.empty:
        return df

    df_fmt = df.copy()

    for col in _COLUNAS_INTEIRAS:
        if col in df_fmt.columns:
            df_fmt[col] = df_fmt[col].apply(fmt_numero)

    for col in _COLUNAS_PCT:
        if col in df_fmt.columns:
            df_fmt[col] = df_fmt[col].apply(fmt_pct)

    return df_fmt
