"""
queries/conflito.py — Query builder para detecção de canibalização territorial.

Estrutura baseada no app de referência (votacao_secao_votacao_secao_AAAA_UF).
Todo processamento pesado (JOIN, ROW_NUMBER, GROUP BY) fica 100% no DuckDB.
"""
import duckdb
import pandas as pd
import streamlit as st

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import (
    ALIAS_2024,
    ALIAS_2022,
    MIN_VOTOS_BAIRRO,
    CRITICO_THRESHOLD,
    ALERTA_THRESHOLD,
    DS_CARGOS_2024,
)
from queries.conexao import get_connection


# ---------------------------------------------------------------------------
# Constantes internas
# ---------------------------------------------------------------------------

_BAIRROS_INVALIDOS_SQL = (
    "''",
    "'SEM INFORMAÇÃO'",
    "'SEM INFORMACAO'",
    "'NAO INFORMADO'",
    "'NÃO INFORMADO'",
    "'S/N'",
    "'SN'",
)

_BAIRROS_INVALIDOS_CLAUSE = ", ".join(_BAIRROS_INVALIDOS_SQL)


# ---------------------------------------------------------------------------
# Helpers de nome de tabela
# ---------------------------------------------------------------------------

def _tabela_secao_2024(uf: str) -> str:
    return f"votacao_secao_votacao_secao_2024_{uf.upper()}"


def _tabela_secao_2022(uf: str) -> str:
    return f"votacao_secao_votacao_secao_2022_{uf.upper()}"


# ---------------------------------------------------------------------------
# Query 2024 (eleição municipal)
# ---------------------------------------------------------------------------

def _build_query_2024(
    uf: str,
    cd_cargo: int,
    sg_partido: str | None,
    nm_municipio: str | None,
    top_n: int,
) -> tuple[str, list]:
    """
    Constrói query CTE para eleição 2024.
    Usa tabela de seção por UF (votacao_secao_votacao_secao_2024_{UF})
    e filtra por DS_CARGO string, igual ao app de referência.
    """
    table_secao = _tabela_secao_2024(uf)
    ds_cargo = DS_CARGOS_2024.get(cd_cargo, "Vereador")

    # Filtros dinâmicos e params correspondentes
    mun_filter_secao = ""
    mun_filter_geo   = ""
    mun_filter_cand  = ""
    partido_filter   = ""
    params: list = []

    if nm_municipio:
        mun_filter_secao = "AND vs.nm_municipio = ?"
        params.append(nm_municipio)

    if nm_municipio:
        mun_filter_geo = "AND g.nm_municipio = ?"
        params.append(nm_municipio)

    if nm_municipio:
        mun_filter_cand = "AND r.NM_MUNICIPIO = ?"
        params.append(nm_municipio)

    if sg_partido:
        partido_filter = "AND r.SG_PARTIDO = ?"
        params.append(sg_partido)

    sql = f"""
WITH
-- 1. Votos por seção: tabela por UF, filtra por DS_CARGO e exclui votos especiais
raw_votos AS (
    SELECT
        vs.nm_municipio,
        CAST(vs.nr_zona    AS BIGINT) AS nr_zona,
        CAST(vs.nr_secao   AS BIGINT) AS nr_secao,
        CAST(vs.nr_votavel AS BIGINT) AS nr_votavel,
        CAST(vs.qt_votos   AS BIGINT) AS qt_votos
    FROM {ALIAS_2024}.{table_secao} vs
    WHERE vs.ds_cargo = '{ds_cargo}'
      AND CAST(vs.nr_votavel AS BIGINT) < 90
      {mun_filter_secao}
),

-- 2. Cross-walk seção → bairro
geo_map AS (
    SELECT
        g.nm_municipio,
        CAST(g.nr_zona  AS BIGINT) AS nr_zona,
        CAST(g.nr_secao AS BIGINT) AS nr_secao,
        UPPER(TRIM(g.NM_BAIRRO))   AS nm_bairro
    FROM {ALIAS_2024}.eleitorado_local g
    WHERE g.sg_uf = '{uf}'
      AND UPPER(TRIM(g.NM_BAIRRO)) NOT IN ({_BAIRROS_INVALIDOS_CLAUSE})
      AND g.NM_BAIRRO IS NOT NULL
      {mun_filter_geo}
),

-- 3. Lookup partido/federação por candidato
candidatos AS (
    SELECT DISTINCT
        r.NM_MUNICIPIO                       AS nm_municipio,
        CAST(r.NR_CANDIDATO AS BIGINT)       AS nr_candidato,
        r.NM_URNA_CANDIDATO,
        r.NM_CANDIDATO,
        r.SG_PARTIDO,
        r.NM_PARTIDO,
        COALESCE(r.SG_FEDERACAO, '')         AS sg_federacao,
        COALESCE(r.NM_FEDERACAO, '')         AS nm_federacao
    FROM {ALIAS_2024}.resultados_2024 r
    WHERE r.SG_UF    = '{uf}'
      AND r.CD_CARGO = {cd_cargo}
      {mun_filter_cand}
      {partido_filter}
),

-- 4. Consolidado: votos por candidato por bairro
consolidado_bairro AS (
    SELECT
        v.nm_municipio,
        g.nm_bairro,
        c.NM_URNA_CANDIDATO,
        c.NM_CANDIDATO,
        c.SG_PARTIDO,
        c.NM_PARTIDO,
        c.sg_federacao,
        c.nm_federacao,
        SUM(v.qt_votos) AS votos_candidato_bairro
    FROM raw_votos v
    JOIN geo_map g
        ON  v.nm_municipio = g.nm_municipio
        AND v.nr_zona      = g.nr_zona
        AND v.nr_secao     = g.nr_secao
    JOIN candidatos c
        ON  v.nm_municipio = c.nm_municipio
        AND v.nr_votavel   = c.nr_candidato
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
),

-- 5. Ranking com window functions
ranking AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY nm_municipio, nm_bairro
            ORDER BY votos_candidato_bairro DESC
        )                                                          AS rank_geral_bairro,
        COUNT(*) OVER (
            PARTITION BY nm_municipio, nm_bairro, SG_PARTIDO
        )                                                          AS n_candidatos_partido_bairro,
        SUM(votos_candidato_bairro) OVER (
            PARTITION BY nm_municipio, nm_bairro
        )                                                          AS total_votos_bairro
    FROM consolidado_bairro
)

-- Resultado final: aliases PT-BR no SELECT; WHERE usa nomes originais do CTE ranking
SELECT
    nm_municipio                                                            AS "Município",
    nm_bairro                                                               AS "Bairro",
    NM_URNA_CANDIDATO                                                       AS "Candidato (Urna)",
    NM_CANDIDATO                                                            AS "Candidato (Completo)",
    SG_PARTIDO                                                              AS "Partido",
    NM_PARTIDO                                                              AS "Nome Partido",
    sg_federacao                                                            AS "Federação",
    nm_federacao                                                            AS "Nome Federação",
    CAST(votos_candidato_bairro AS BIGINT)                                  AS "Votos no Bairro",
    CAST(total_votos_bairro     AS BIGINT)                                  AS "Total Votos Bairro",
    ROUND(100.0 * votos_candidato_bairro / NULLIF(total_votos_bairro, 0), 2) AS "% Bairro",
    CAST(rank_geral_bairro            AS BIGINT)                            AS "Posição Bairro",
    CAST(n_candidatos_partido_bairro  AS BIGINT)                            AS "Candidatos Partido/Bairro",
    CASE
        WHEN n_candidatos_partido_bairro >= {CRITICO_THRESHOLD} THEN 'CRÍTICO'
        WHEN n_candidatos_partido_bairro >= {ALERTA_THRESHOLD}  THEN 'ALERTA'
        ELSE 'OK'
    END                                                                     AS "Status Conflito",
    'PARTIDO'                                                               AS "Tipo Conflito"
FROM ranking
WHERE rank_geral_bairro          <= {top_n}
  AND total_votos_bairro         >= {MIN_VOTOS_BAIRRO}
  AND n_candidatos_partido_bairro >= {ALERTA_THRESHOLD}
ORDER BY nm_municipio, nm_bairro, SG_PARTIDO, rank_geral_bairro
"""
    return sql, params


# ---------------------------------------------------------------------------
# Query 2022 (eleição geral) — inclui lógica de federação
# ---------------------------------------------------------------------------

def _build_query_2022(
    uf: str,
    cd_cargo: int,
    sg_partido: str | None,
    nm_municipio: str | None,
    top_n: int,
) -> tuple[str, list]:
    """
    Constrói query CTE para eleição 2022.
    Detecta canibalização tanto por partido quanto por federação (SG_FEDERACAO).
    """
    table_secao = _tabela_secao_2022(uf)

    mun_filter_secao = ""
    mun_filter_geo   = ""
    mun_filter_cand  = ""
    partido_filter   = ""
    params: list = []

    if nm_municipio:
        mun_filter_secao = "AND vs.NM_MUNICIPIO = ?"
        params.append(nm_municipio)

    if nm_municipio:
        mun_filter_geo = "AND g.NM_MUNICIPIO = ?"
        params.append(nm_municipio)

    if nm_municipio:
        mun_filter_cand = "AND r.NM_MUNICIPIO = ?"
        params.append(nm_municipio)

    if sg_partido:
        partido_filter = "AND r.SG_PARTIDO = ?"
        params.append(sg_partido)

    sql = f"""
WITH
-- 1. Votos por seção 2022 (CD_CARGO inteiro)
raw_votos AS (
    SELECT
        vs.NM_MUNICIPIO                  AS nm_municipio,
        CAST(vs.NR_ZONA    AS BIGINT)    AS nr_zona,
        CAST(vs.NR_SECAO   AS BIGINT)    AS nr_secao,
        CAST(vs.NR_VOTAVEL AS BIGINT)    AS nr_votavel,
        CAST(vs.QT_VOTOS   AS BIGINT)    AS qt_votos
    FROM {ALIAS_2022}.{table_secao} vs
    WHERE vs.SG_UF    = '{uf}'
      AND vs.CD_CARGO = {cd_cargo}
      AND CAST(vs.NR_VOTAVEL AS BIGINT) < 90
      {mun_filter_secao}
),

-- 2. Cross-walk seção → bairro 2022
geo_map AS (
    SELECT
        g.NM_MUNICIPIO                   AS nm_municipio,
        CAST(g.NR_ZONA  AS BIGINT)       AS nr_zona,
        CAST(g.NR_SECAO AS BIGINT)       AS nr_secao,
        UPPER(TRIM(g.NM_BAIRRO))         AS nm_bairro
    FROM {ALIAS_2022}.eleitorado_local_2022_clean g
    WHERE g.SG_UF = '{uf}'
      AND UPPER(TRIM(g.NM_BAIRRO)) NOT IN ({_BAIRROS_INVALIDOS_CLAUSE})
      AND g.NM_BAIRRO IS NOT NULL
      {mun_filter_geo}
),

-- 3. Lookup partido/federação 2022
candidatos AS (
    SELECT DISTINCT
        r.NM_MUNICIPIO                       AS nm_municipio,
        CAST(r.NR_CANDIDATO AS BIGINT)       AS nr_candidato,
        r.NM_URNA_CANDIDATO,
        r.NM_CANDIDATO,
        r.SG_PARTIDO,
        r.NM_PARTIDO,
        COALESCE(r.SG_FEDERACAO, '')         AS sg_federacao,
        COALESCE(r.NM_FEDERACAO, '')         AS nm_federacao
    FROM {ALIAS_2022}.resultados_2022 r
    WHERE r.SG_UF    = '{uf}'
      AND r.CD_CARGO = {cd_cargo}
      {mun_filter_cand}
      {partido_filter}
),

-- 4. Consolidado por bairro
consolidado_bairro AS (
    SELECT
        v.nm_municipio,
        g.nm_bairro,
        c.NM_URNA_CANDIDATO,
        c.NM_CANDIDATO,
        c.SG_PARTIDO,
        c.NM_PARTIDO,
        c.sg_federacao,
        c.nm_federacao,
        SUM(v.qt_votos) AS votos_candidato_bairro
    FROM raw_votos v
    JOIN geo_map g
        ON  v.nm_municipio = g.nm_municipio
        AND v.nr_zona      = g.nr_zona
        AND v.nr_secao     = g.nr_secao
    JOIN candidatos c
        ON  v.nm_municipio = c.nm_municipio
        AND v.nr_votavel   = c.nr_candidato
    GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
),

-- 5. Ranking com contadores de partido E federação
ranking AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY nm_municipio, nm_bairro
            ORDER BY votos_candidato_bairro DESC
        )                                                              AS rank_geral_bairro,

        COUNT(*) OVER (
            PARTITION BY nm_municipio, nm_bairro, SG_PARTIDO
        )                                                              AS n_candidatos_partido_bairro,

        CASE
            WHEN sg_federacao <> '' THEN
                COUNT(*) OVER (PARTITION BY nm_municipio, nm_bairro, sg_federacao)
            ELSE 1
        END                                                            AS n_candidatos_federacao_bairro,

        SUM(votos_candidato_bairro) OVER (
            PARTITION BY nm_municipio, nm_bairro
        )                                                              AS total_votos_bairro
    FROM consolidado_bairro
)

SELECT
    nm_municipio                                                                AS "Município",
    nm_bairro                                                                   AS "Bairro",
    NM_URNA_CANDIDATO                                                           AS "Candidato (Urna)",
    NM_CANDIDATO                                                                AS "Candidato (Completo)",
    SG_PARTIDO                                                                  AS "Partido",
    NM_PARTIDO                                                                  AS "Nome Partido",
    sg_federacao                                                                AS "Federação",
    nm_federacao                                                                AS "Nome Federação",
    CAST(votos_candidato_bairro AS BIGINT)                                      AS "Votos no Bairro",
    CAST(total_votos_bairro     AS BIGINT)                                      AS "Total Votos Bairro",
    ROUND(100.0 * votos_candidato_bairro / NULLIF(total_votos_bairro, 0), 2)   AS "% Bairro",
    CAST(rank_geral_bairro                   AS BIGINT)                         AS "Posição Bairro",
    CAST(n_candidatos_partido_bairro         AS BIGINT)                         AS "Candidatos Partido/Bairro",
    CAST(n_candidatos_federacao_bairro       AS BIGINT)                         AS "Candidatos Fed./Bairro",
    CASE
        WHEN GREATEST(n_candidatos_partido_bairro, n_candidatos_federacao_bairro) >= {CRITICO_THRESHOLD} THEN 'CRÍTICO'
        WHEN GREATEST(n_candidatos_partido_bairro, n_candidatos_federacao_bairro) >= {ALERTA_THRESHOLD}  THEN 'ALERTA'
        ELSE 'OK'
    END                                                                         AS "Status Conflito",
    CASE
        WHEN n_candidatos_federacao_bairro > n_candidatos_partido_bairro
             AND sg_federacao <> '' THEN 'FEDERAÇÃO'
        ELSE 'PARTIDO'
    END                                                                         AS "Tipo Conflito"
FROM ranking
WHERE rank_geral_bairro >= 1
  AND rank_geral_bairro <= {top_n}
  AND total_votos_bairro >= {MIN_VOTOS_BAIRRO}
  AND GREATEST(n_candidatos_partido_bairro, n_candidatos_federacao_bairro) >= {ALERTA_THRESHOLD}
ORDER BY nm_municipio, nm_bairro, SG_PARTIDO, rank_geral_bairro
"""
    return sql, params


# ---------------------------------------------------------------------------
# Função pública principal
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def query_conflito_territorial(
    uf: str,
    cd_cargo: int,
    ano: int,
    sg_partido: str | None = None,
    nm_municipio: str | None = None,
    top_n: int = 10,
) -> tuple[pd.DataFrame, str]:
    """
    Executa a query de canibalização territorial e retorna (df, erro).

    Parameters
    ----------
    uf           : sigla da UF (ex.: 'GO')
    cd_cargo     : código do cargo (ex.: 13 = Vereador 2024)
    ano          : 2024 ou 2022
    sg_partido   : filtrar por partido (None = todos)
    nm_municipio : filtrar por município — nome exato do TSE (None = toda a UF)
    top_n        : candidatos por bairro a considerar
    """
    con = get_connection()

    try:
        if ano == 2024:
            sql, params = _build_query_2024(uf, cd_cargo, sg_partido, nm_municipio, top_n)
        elif ano == 2022:
            sql, params = _build_query_2022(uf, cd_cargo, sg_partido, nm_municipio, top_n)
        else:
            return pd.DataFrame(), f"Ano {ano} não suportado."

        df = con.execute(sql, params).df()
        return df, ""

    except duckdb.CatalogException as exc:
        msg = (
            f"Tabela não encontrada para UF={uf}, ano={ano}. "
            f"Verifique se o banco contém os dados desta UF. "
            f"Detalhe: {exc}"
        )
        return pd.DataFrame(), msg

    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), f"Erro ao executar query de conflito: {exc}"


# ---------------------------------------------------------------------------
# Métricas de resumo
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def calcular_metricas(df: pd.DataFrame) -> dict:
    if df.empty:
        return {
            "bairros_em_conflito": 0,
            "candidatos_afetados": 0,
            "votos_em_risco": 0,
            "municipios_afetados": 0,
        }

    return {
        "bairros_em_conflito": df[["Município", "Bairro"]].drop_duplicates().shape[0],
        "candidatos_afetados": df["Candidato (Urna)"].nunique(),
        "votos_em_risco": int(df["Votos no Bairro"].sum()),
        "municipios_afetados": df["Município"].nunique(),
    }
