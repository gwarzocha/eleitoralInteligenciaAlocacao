"""
queries/conexao.py — Conexão DuckDB com ATTACH dos dois bancos e helpers de listagem.
"""
import duckdb
import pandas as pd
import streamlit as st

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    DB_2024,
    DB_2022,
    ALIAS_2024,
    ALIAS_2022,
    UFS_POR_ANO,
    CARGOS_POR_ANO,
)


# ---------------------------------------------------------------------------
# Conexão principal — singleton por processo Streamlit
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def get_connection() -> duckdb.DuckDBPyConnection:
    """
    Retorna conexão DuckDB em memória com os dois bancos ATTACHados como
    READ_ONLY.  Usa @st.cache_resource para garantir uma única instância
    por processo (thread-safe para leituras simultâneas).
    """
    con = duckdb.connect(database=":memory:")

    # Attach banco 2024
    con.execute(
        f"ATTACH '{DB_2024}' AS {ALIAS_2024} (READ_ONLY)"
    )

    # Attach banco 2022
    con.execute(
        f"ATTACH '{DB_2022}' AS {ALIAS_2022} (READ_ONLY)"
    )

    return con


# ---------------------------------------------------------------------------
# Helpers de listagem (com cache de 1 hora)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def listar_ufs(ano: int) -> list[str]:
    """
    Retorna a lista de UFs disponíveis para o ano informado.
    Usa o mapeamento estático de config.py (não precisa de query —
    as UFs já são conhecidas pela arquitetura do banco).
    """
    return sorted(UFS_POR_ANO.get(ano, []))


@st.cache_data(ttl=3600, show_spinner=False)
def listar_municipios(uf: str, ano: int) -> list[tuple[int, str]]:
    """
    Retorna lista de (CD_MUNICIPIO, NM_MUNICIPIO) para a UF/ano informados,
    ordenada alfabeticamente pelo nome do município.

    Returns
    -------
    list[tuple[int, str]]
        Ex.: [(71072, "ABAETETUBA"), (71099, "ABEL FIGUEIREDO"), ...]
    """
    con = get_connection()

    try:
        if ano == 2024:
            sql = f"""
                SELECT DISTINCT
                    CAST(CD_MUNICIPIO AS BIGINT) AS cd,
                    NM_MUNICIPIO                  AS nm
                FROM {ALIAS_2024}.resultados_2024
                WHERE SG_UF = ?
                ORDER BY nm
            """
        else:  # 2022
            sql = f"""
                SELECT DISTINCT
                    CAST(CD_MUNICIPIO AS BIGINT) AS cd,
                    NM_MUNICIPIO                  AS nm
                FROM {ALIAS_2022}.resultados_2022
                WHERE SG_UF = ?
                ORDER BY nm
            """

        rows = con.execute(sql, [uf]).fetchall()
        return [(int(r[0]), r[1]) for r in rows]

    except Exception as exc:  # noqa: BLE001
        st.error(f"Erro ao listar municípios: {exc}")
        return []


@st.cache_data(ttl=3600, show_spinner=False)
def listar_partidos(
    uf: str,
    cd_cargo: int,
    ano: int,
    cd_municipio: int | None = None,
) -> list[str]:
    """
    Retorna lista de siglas de partido que têm candidatos para o cargo/UF/ano.
    Opcionalmente filtrado por município.

    Returns
    -------
    list[str]
        Ex.: ["MDB", "PL", "PT", ...]
    """
    con = get_connection()

    try:
        municipio_filter = ""
        params: list = [uf, cd_cargo]

        if cd_municipio is not None:
            municipio_filter = "AND CAST(CD_MUNICIPIO AS BIGINT) = ?"
            params.append(cd_municipio)

        if ano == 2024:
            sql = f"""
                SELECT DISTINCT SG_PARTIDO
                FROM {ALIAS_2024}.resultados_2024
                WHERE SG_UF    = ?
                  AND CD_CARGO = ?
                  {municipio_filter}
                ORDER BY SG_PARTIDO
            """
        else:
            sql = f"""
                SELECT DISTINCT SG_PARTIDO
                FROM {ALIAS_2022}.resultados_2022
                WHERE SG_UF    = ?
                  AND CD_CARGO = ?
                  {municipio_filter}
                ORDER BY SG_PARTIDO
            """

        rows = con.execute(sql, params).fetchall()
        return [r[0] for r in rows]

    except Exception as exc:  # noqa: BLE001
        st.error(f"Erro ao listar partidos: {exc}")
        return []
