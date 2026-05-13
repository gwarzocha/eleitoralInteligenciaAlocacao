"""
queries/conflito.py — Query builder baseado no padrão de referência comprovado.

Arquitetura:
  raw_votos → geo_map → candidatos → consolidado_bairro → ranking_final
  Todo o Top N e candidatos_mesmo_partido resolvidos no DuckDB via Window Functions.
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
# Helpers de nome de tabela
# ---------------------------------------------------------------------------

def _tabela_secao_2024(uf: str) -> str:
    return f"votacao_secao_votacao_secao_2024_{uf.upper()}"


def _tabela_secao_2022(uf: str) -> str:
    return f"votacao_secao_votacao_secao_2022_{uf.upper()}"


# ---------------------------------------------------------------------------
# Filtro de partido — f-string controlada (valores vêm de dropdown do DB)
# ---------------------------------------------------------------------------

def _partido_filter_sql(parties: list[str] | None, alias: str = "cand") -> str:
    if not parties:
        return ""
    party_list = ", ".join(f"'{p}'" for p in parties)
    return f"AND {alias}.sg_partido IN ({party_list})"


# ---------------------------------------------------------------------------
# Query 2024 — padrão exato do código de referência + alias ATTACH
# ---------------------------------------------------------------------------

def _build_query_2024(
    uf: str,
    cd_cargo: int,
    nm_municipio: str,          # obrigatório — predicate pushdown
    top_n: int,
    parties: list[str] | None,
) -> str:
    table_secao = _tabela_secao_2024(uf)
    ds_cargo    = DS_CARGOS_2024.get(cd_cargo, "Vereador")
    party_filter = _partido_filter_sql(parties)

    return f"""
WITH raw_votos AS (
    -- 1. PREDICATE PUSHDOWN: filtra município na raiz
    SELECT nr_zona, nr_secao, nr_votavel, qt_votos
    FROM {ALIAS_2024}.{table_secao}
    WHERE ds_cargo = '{ds_cargo}'
      AND nm_municipio = '{nm_municipio}'
),
geo_map AS (
    -- 2. MAPA GEOGRÁFICO: bairros desta cidade
    SELECT nr_zona, nr_secao, NM_BAIRRO AS Bairro
    FROM {ALIAS_2024}.eleitorado_local
    WHERE sg_uf = '{uf.upper()}'
      AND nm_municipio = '{nm_municipio}'
      AND NM_BAIRRO IS NOT NULL
      AND UPPER(TRIM(NM_BAIRRO)) NOT IN (
            '', 'SEM INFORMAÇÃO', 'SEM INFORMACAO',
            'NAO INFORMADO', 'NÃO INFORMADO', 'S/N', 'SN'
      )
),
candidatos AS (
    -- 3. METADADOS DA CHAPA
    SELECT DISTINCT
        CAST(nr_candidato AS BIGINT) AS nr_candidato,
        sg_partido AS Partido,
        NM_URNA_CANDIDATO AS Candidato,
        DS_SIT_TOT_TURNO  AS Situacao
    FROM {ALIAS_2024}.resultados_2024
    WHERE ds_cargo = '{ds_cargo}'
      AND nm_municipio = '{nm_municipio}'
      {party_filter}
),
consolidado_bairro AS (
    -- 4. JOIN + AGREGAÇÃO com aliases fixos para evitar KeyError no Pandas
    SELECT
        g.Bairro         AS Bairro,
        cand.Partido     AS Partido,
        cand.Candidato   AS Candidato,
        cand.Situacao    AS Situacao,
        SUM(CAST(v.qt_votos AS BIGINT)) AS Votos
    FROM raw_votos v
    JOIN geo_map g
        ON v.nr_zona    = g.nr_zona
       AND v.nr_secao   = g.nr_secao
    JOIN candidatos cand
        ON CAST(v.nr_votavel AS BIGINT) = cand.nr_candidato
    WHERE CAST(v.nr_votavel AS BIGINT) < 90
    GROUP BY 1, 2, 3, 4
),
ranking_final AS (
    -- 5. WINDOW FUNCTIONS: Top N e conflito de chapa no DuckDB
    SELECT *,
        ROW_NUMBER() OVER(PARTITION BY Bairro ORDER BY Votos DESC) AS rank_bairro,
        COUNT(*) OVER(PARTITION BY Bairro, Partido)               AS candidatos_mesmo_partido
    FROM consolidado_bairro
    WHERE Votos > 0
)
SELECT
    '{nm_municipio}'               AS Municipio,
    Bairro,
    Partido,
    Candidato,
    Situacao,
    Votos,
    candidatos_mesmo_partido,
    CASE
        WHEN candidatos_mesmo_partido >= {CRITICO_THRESHOLD} THEN 'CRÍTICO'
        WHEN candidatos_mesmo_partido >= {ALERTA_THRESHOLD}  THEN 'ALERTA'
        ELSE 'OK'
    END AS Status
FROM ranking_final
WHERE rank_bairro <= {top_n}
ORDER BY Bairro ASC, Votos DESC
"""


# ---------------------------------------------------------------------------
# Query 2022 — mesmo padrão + lógica de federação
# ---------------------------------------------------------------------------

def _build_query_2022(
    uf: str,
    cd_cargo: int,
    nm_municipio: str,
    top_n: int,
    parties: list[str] | None,
) -> str:
    table_secao  = _tabela_secao_2022(uf)
    party_filter = _partido_filter_sql(parties)

    return f"""
WITH raw_votos AS (
    SELECT NM_MUNICIPIO AS nm_municipio, NR_ZONA AS nr_zona, NR_SECAO AS nr_secao,
           CAST(NR_VOTAVEL AS BIGINT) AS nr_votavel,
           CAST(QT_VOTOS   AS BIGINT) AS qt_votos
    FROM {ALIAS_2022}.{table_secao}
    WHERE SG_UF      = '{uf.upper()}'
      AND CD_CARGO   = {cd_cargo}
      AND NM_MUNICIPIO = '{nm_municipio}'
      AND CAST(NR_VOTAVEL AS BIGINT) < 90
),
geo_map AS (
    SELECT NR_ZONA AS nr_zona, NR_SECAO AS nr_secao, NM_BAIRRO AS Bairro
    FROM {ALIAS_2022}.eleitorado_local_2022_clean
    WHERE SG_UF        = '{uf.upper()}'
      AND NM_MUNICIPIO = '{nm_municipio}'
      AND NM_BAIRRO IS NOT NULL
      AND UPPER(TRIM(NM_BAIRRO)) NOT IN (
            '', 'SEM INFORMAÇÃO', 'SEM INFORMACAO',
            'NAO INFORMADO', 'NÃO INFORMADO', 'S/N', 'SN'
      )
),
candidatos AS (
    SELECT DISTINCT
        CAST(NR_CANDIDATO AS BIGINT)     AS nr_candidato,
        SG_PARTIDO                        AS Partido,
        NM_URNA_CANDIDATO                 AS Candidato,
        DS_SIT_TOT_TURNO                  AS Situacao,
        COALESCE(SG_FEDERACAO, '')        AS sg_federacao
    FROM {ALIAS_2022}.resultados_2022
    WHERE SG_UF        = '{uf.upper()}'
      AND CD_CARGO     = {cd_cargo}
      AND NM_MUNICIPIO = '{nm_municipio}'
      {party_filter}
),
consolidado_bairro AS (
    SELECT
        g.Bairro         AS Bairro,
        cand.Partido     AS Partido,
        cand.Candidato   AS Candidato,
        cand.Situacao    AS Situacao,
        cand.sg_federacao AS sg_federacao,
        SUM(v.qt_votos)  AS Votos
    FROM raw_votos v
    JOIN geo_map g
        ON CAST(v.nr_zona  AS BIGINT) = CAST(g.nr_zona  AS BIGINT)
       AND CAST(v.nr_secao AS BIGINT) = CAST(g.nr_secao AS BIGINT)
    JOIN candidatos cand
        ON v.nr_votavel = cand.nr_candidato
    GROUP BY 1, 2, 3, 4, 5
),
ranking_final AS (
    SELECT *,
        ROW_NUMBER() OVER(PARTITION BY Bairro ORDER BY Votos DESC)          AS rank_bairro,
        COUNT(*) OVER(PARTITION BY Bairro, Partido)                          AS candidatos_mesmo_partido,
        CASE
            WHEN sg_federacao <> '' THEN
                COUNT(*) OVER(PARTITION BY Bairro, sg_federacao)
            ELSE 1
        END                                                                   AS candidatos_mesma_federacao
    FROM consolidado_bairro
    WHERE Votos > 0
)
SELECT
    '{nm_municipio}'                    AS Municipio,
    Bairro,
    Partido,
    Candidato,
    Situacao,
    sg_federacao                        AS Federacao,
    Votos,
    candidatos_mesmo_partido,
    candidatos_mesma_federacao,
    GREATEST(candidatos_mesmo_partido, candidatos_mesma_federacao) AS conflito_max,
    CASE
        WHEN GREATEST(candidatos_mesmo_partido, candidatos_mesma_federacao) >= {CRITICO_THRESHOLD} THEN 'CRÍTICO'
        WHEN GREATEST(candidatos_mesmo_partido, candidatos_mesma_federacao) >= {ALERTA_THRESHOLD}  THEN 'ALERTA'
        ELSE 'OK'
    END AS Status
FROM ranking_final
WHERE rank_bairro <= {top_n}
ORDER BY Bairro ASC, Votos DESC
"""


# ---------------------------------------------------------------------------
# Função pública principal
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def query_conflito_territorial(
    uf: str,
    cd_cargo: int,
    ano: int,
    nm_municipio: str,
    top_n: int = 10,
    parties: tuple[str, ...] | None = None,   # tuple para ser hashável pelo cache
) -> tuple[pd.DataFrame, str]:
    """
    Executa a query de canibalização e retorna (df, mensagem_erro).

    nm_municipio é obrigatório — o predicate pushdown filtra a cidade
    na raiz de cada CTE para não sobrecarregar a memória.

    parties deve ser uma tuple (não list) para compatibilidade com @st.cache_data.
    """
    parties_list = list(parties) if parties else None
    con = get_connection()

    try:
        if ano == 2024:
            sql = _build_query_2024(uf, cd_cargo, nm_municipio, top_n, parties_list)
        elif ano == 2022:
            sql = _build_query_2022(uf, cd_cargo, nm_municipio, top_n, parties_list)
        else:
            return pd.DataFrame(), f"Ano {ano} não suportado."

        df = con.execute(sql).df()
        return df, ""

    except duckdb.CatalogException as exc:
        return pd.DataFrame(), (
            f"Tabela não encontrada para UF={uf}, ano={ano}. "
            f"Verifique se o banco contém os dados desta UF. Detalhe: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        return pd.DataFrame(), f"Erro ao executar query: {exc}"


# ---------------------------------------------------------------------------
# Métricas de resumo (baseadas na coluna candidatos_mesmo_partido)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def calcular_metricas(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"bairros_em_conflito": 0, "candidatos_afetados": 0,
                "votos_em_risco": 0, "pares_conflito": 0}

    conflitos = df[df["candidatos_mesmo_partido"] >= ALERTA_THRESHOLD]
    return {
        "bairros_em_conflito": conflitos["Bairro"].nunique(),
        "candidatos_afetados": conflitos["Candidato"].nunique(),
        "votos_em_risco": int(conflitos["Votos"].sum()),
        "pares_conflito": int((conflitos["candidatos_mesmo_partido"] >= ALERTA_THRESHOLD).sum()),
    }
