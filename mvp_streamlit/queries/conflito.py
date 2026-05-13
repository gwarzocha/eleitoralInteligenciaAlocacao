"""
queries/conflito.py — Query builder principal para detecção de canibalização territorial.

Toda a lógica de JOIN, ROW_NUMBER e classificação de conflito fica 100% no DuckDB.
Streamlit recebe apenas o DataFrame final já formatado.
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
# Helpers internos
# ---------------------------------------------------------------------------

def _alias_secao_2022(uf: str) -> str:
    """Retorna o nome da tabela de seção de 2022 para a UF informada."""
    return f"votacao_secao_votacao_secao_2022_{uf.upper()}"


def _build_query_2024(
    uf: str,
    cd_cargo: int,
    sg_partido: str | None,
    cd_municipio: int | None,
    top_n: int,
) -> tuple[str, list]:
    """
    Constrói a query CTE completa para eleição 2024 (municipal).
    Retorna (sql_string, params_list).
    """
    municipio_filter_secao = ""
    municipio_filter_res = ""

    # params for votos_secao CTE: uf, cd_cargo [, cd_municipio]
    params_secao: list = [uf, cd_cargo]
    if cd_municipio is not None:
        municipio_filter_secao = "AND vs.CD_MUNICIPIO = ?"
        params_secao.append(cd_municipio)

    # params for candidatos CTE: uf, cd_cargo [, cd_municipio] [, sg_partido]
    params_candidatos: list = [uf, cd_cargo]
    partido_filter = ""
    if cd_municipio is not None:
        municipio_filter_res = "AND r.CD_MUNICIPIO = ?"
        params_candidatos.append(cd_municipio)
    if sg_partido:
        partido_filter = "AND r.SG_PARTIDO = ?"
        params_candidatos.append(sg_partido)

    params_tail: list = [top_n, MIN_VOTOS_BAIRRO, ALERTA_THRESHOLD]

    sql = f"""
WITH
-- 1. Votos por seção: filtra UF, cargo, turno 1 e exclui votos especiais
votos_secao AS (
    SELECT
        vs.SG_UF,
        CAST(vs.CD_MUNICIPIO  AS BIGINT) AS CD_MUNICIPIO,
        vs.NM_MUNICIPIO,
        CAST(vs.NR_ZONA       AS BIGINT) AS NR_ZONA,
        CAST(vs.NR_SECAO      AS BIGINT) AS NR_SECAO,
        CAST(vs.NR_VOTAVEL    AS BIGINT) AS NR_VOTAVEL,
        CAST(vs.QT_VOTOS      AS BIGINT) AS QT_VOTOS
    FROM {ALIAS_2024}.resultados_2024_secao vs
    WHERE vs.SG_UF    = ?
      AND vs.CD_CARGO = ?
      AND vs.NR_TURNO = 1
      AND CAST(vs.NR_VOTAVEL AS BIGINT) < 90
      {municipio_filter_secao}
),

-- 2. Bairros por seção: normaliza NM_BAIRRO e exclui inválidos
bairros_secao AS (
    SELECT
        el.SG_UF,
        CAST(el.CD_MUNICIPIO AS BIGINT) AS CD_MUNICIPIO,
        CAST(el.NR_ZONA      AS BIGINT) AS NR_ZONA,
        CAST(el.NR_SECAO     AS BIGINT) AS NR_SECAO,
        UPPER(TRIM(el.NM_BAIRRO))       AS NM_BAIRRO
    FROM {ALIAS_2024}.eleitorado_local el
    WHERE UPPER(TRIM(el.NM_BAIRRO)) NOT IN ({_BAIRROS_INVALIDOS_CLAUSE})
      AND TRIM(el.NM_BAIRRO) IS NOT NULL
),

-- 3. Lookup de partido/federação por candidato
candidatos AS (
    SELECT DISTINCT
        CAST(r.CD_MUNICIPIO   AS BIGINT) AS CD_MUNICIPIO,
        r.SG_UF,
        CAST(r.NR_CANDIDATO   AS BIGINT) AS NR_CANDIDATO,
        r.NM_CANDIDATO,
        r.NM_URNA_CANDIDATO,
        r.SG_PARTIDO,
        r.NM_PARTIDO,
        COALESCE(r.SG_FEDERACAO, '')     AS SG_FEDERACAO,
        COALESCE(r.NM_FEDERACAO, '')     AS NM_FEDERACAO
    FROM {ALIAS_2024}.resultados_2024 r
    WHERE r.SG_UF    = ?
      AND r.CD_CARGO = ?
      {municipio_filter_res}
      {partido_filter}
),

-- 4. Votos por candidato por bairro (cross-walk key: UF+MUNICIPIO+ZONA+SECAO)
votos_por_bairro AS (
    SELECT
        vs.NM_MUNICIPIO,
        bs.NM_BAIRRO,
        c.NM_URNA_CANDIDATO,
        c.NM_CANDIDATO,
        c.SG_PARTIDO,
        c.NM_PARTIDO,
        c.SG_FEDERACAO,
        c.NM_FEDERACAO,
        SUM(vs.QT_VOTOS) AS votos_candidato_bairro
    FROM votos_secao vs
    JOIN bairros_secao bs
        ON  vs.SG_UF        = bs.SG_UF
        AND vs.CD_MUNICIPIO = bs.CD_MUNICIPIO
        AND vs.NR_ZONA      = bs.NR_ZONA
        AND vs.NR_SECAO     = bs.NR_SECAO
    JOIN candidatos c
        ON  vs.SG_UF        = c.SG_UF
        AND vs.CD_MUNICIPIO = c.CD_MUNICIPIO
        AND vs.NR_VOTAVEL   = c.NR_CANDIDATO
    GROUP BY
        vs.NM_MUNICIPIO,
        bs.NM_BAIRRO,
        c.NM_URNA_CANDIDATO,
        c.NM_CANDIDATO,
        c.SG_PARTIDO,
        c.NM_PARTIDO,
        c.SG_FEDERACAO,
        c.NM_FEDERACAO
),

-- 5. Ranking: posição geral no bairro, qtd candidatos do mesmo partido no bairro, total de votos do bairro
ranking AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY NM_MUNICIPIO, NM_BAIRRO
            ORDER BY votos_candidato_bairro DESC
        ) AS rank_geral_bairro,
        COUNT(*) OVER (
            PARTITION BY NM_MUNICIPIO, NM_BAIRRO, SG_PARTIDO
        ) AS n_candidatos_partido_bairro,
        SUM(votos_candidato_bairro) OVER (
            PARTITION BY NM_MUNICIPIO, NM_BAIRRO
        ) AS total_votos_bairro
    FROM votos_por_bairro
),

-- 6. Filtro: apenas candidatos dentro do Top N do bairro + com votos mínimos
top_n_bairro AS (
    SELECT *
    FROM ranking
    WHERE rank_geral_bairro <= ?
      AND total_votos_bairro  >= ?
),

-- 7. Resultado final: adiciona % de votos e status de conflito
resultado_final AS (
    SELECT
        NM_MUNICIPIO                                                AS "Município",
        NM_BAIRRO                                                   AS "Bairro",
        NM_URNA_CANDIDATO                                           AS "Candidato (Urna)",
        NM_CANDIDATO                                                AS "Candidato (Completo)",
        SG_PARTIDO                                                  AS "Partido",
        NM_PARTIDO                                                  AS "Nome Partido",
        SG_FEDERACAO                                                AS "Federação",
        NM_FEDERACAO                                                AS "Nome Federação",
        CAST(votos_candidato_bairro AS BIGINT)                      AS "Votos no Bairro",
        CAST(total_votos_bairro     AS BIGINT)                      AS "Total Votos Bairro",
        ROUND(
            100.0 * votos_candidato_bairro / NULLIF(total_votos_bairro, 0),
            2
        )                                                           AS "% Bairro",
        CAST(rank_geral_bairro              AS BIGINT)              AS "Posição Bairro",
        CAST(n_candidatos_partido_bairro    AS BIGINT)              AS "Candidatos Partido/Bairro",
        CASE
            WHEN n_candidatos_partido_bairro >= {CRITICO_THRESHOLD} THEN 'CRÍTICO'
            WHEN n_candidatos_partido_bairro >= {ALERTA_THRESHOLD}  THEN 'ALERTA'
            ELSE 'OK'
        END                                                         AS "Status Conflito",
        'PARTIDO'                                                   AS "Tipo Conflito"
    FROM top_n_bairro
)

SELECT *
FROM resultado_final
WHERE "Status Conflito" IN ('ALERTA', 'CRÍTICO')
  AND n_candidatos_partido_bairro >= ?
ORDER BY
    "Município",
    "Bairro",
    "Partido",
    "Posição Bairro"
"""
    # params order:
    # votos_secao:  uf, cd_cargo [, cd_municipio]
    # candidatos:   uf, cd_cargo [, cd_municipio] [, sg_partido]
    # top_n_bairro: top_n, MIN_VOTOS_BAIRRO
    # WHERE final:  ALERTA_THRESHOLD
    full_params = params_secao + params_candidatos + params_tail
    return sql, full_params


def _build_query_2022(
    uf: str,
    cd_cargo: int,
    sg_partido: str | None,
    cd_municipio: int | None,
    top_n: int,
) -> tuple[str, list]:
    """
    Constrói a query CTE completa para eleição 2022 (geral).
    Inclui lógica de federações na canibalização.
    Retorna (sql_string, params_list).
    """
    tabela_secao = _alias_secao_2022(uf)

    municipio_filter_secao = ""
    municipio_filter_res = ""

    # params for votos_secao CTE: uf, cd_cargo [, cd_municipio]
    params_secao: list = [uf, cd_cargo]
    if cd_municipio is not None:
        municipio_filter_secao = "AND CAST(vs.CD_MUNICIPIO AS BIGINT) = ?"
        params_secao.append(cd_municipio)

    # params for candidatos CTE: uf, cd_cargo [, cd_municipio] [, sg_partido]
    params_candidatos: list = [uf, cd_cargo]
    partido_filter = ""
    if cd_municipio is not None:
        municipio_filter_res = "AND CAST(r.CD_MUNICIPIO AS BIGINT) = ?"
        params_candidatos.append(cd_municipio)
    if sg_partido:
        partido_filter = "AND r.SG_PARTIDO = ?"
        params_candidatos.append(sg_partido)

    params_tail: list = [top_n, MIN_VOTOS_BAIRRO, ALERTA_THRESHOLD]

    sql = f"""
WITH
-- 1. Votos por seção 2022
votos_secao AS (
    SELECT
        vs.SG_UF,
        CAST(vs.CD_MUNICIPIO  AS BIGINT) AS CD_MUNICIPIO,
        vs.NM_MUNICIPIO,
        CAST(vs.NR_ZONA       AS BIGINT) AS NR_ZONA,
        CAST(vs.NR_SECAO      AS BIGINT) AS NR_SECAO,
        CAST(vs.NR_VOTAVEL    AS BIGINT) AS NR_VOTAVEL,
        CAST(vs.QT_VOTOS      AS BIGINT) AS QT_VOTOS
    FROM {ALIAS_2022}.{tabela_secao} vs
    WHERE vs.SG_UF    = ?
      AND vs.CD_CARGO = ?
      AND vs.NR_TURNO = 1
      AND CAST(vs.NR_VOTAVEL AS BIGINT) < 90
      {municipio_filter_secao}
),

-- 2. Bairros por seção 2022 (CD_MUNICIPIO e NR_ZONA/SECAO são VARCHAR neste banco)
bairros_secao AS (
    SELECT
        el.SG_UF,
        CAST(el.CD_MUNICIPIO AS BIGINT) AS CD_MUNICIPIO,
        CAST(el.NR_ZONA      AS BIGINT) AS NR_ZONA,
        CAST(el.NR_SECAO     AS BIGINT) AS NR_SECAO,
        UPPER(TRIM(el.NM_BAIRRO))       AS NM_BAIRRO
    FROM {ALIAS_2022}.eleitorado_local_2022_clean el
    WHERE UPPER(TRIM(el.NM_BAIRRO)) NOT IN ({_BAIRROS_INVALIDOS_CLAUSE})
      AND TRIM(el.NM_BAIRRO) IS NOT NULL
),

-- 3. Lookup de partido/federação 2022
candidatos AS (
    SELECT DISTINCT
        CAST(r.CD_MUNICIPIO  AS BIGINT) AS CD_MUNICIPIO,
        r.SG_UF,
        CAST(r.NR_CANDIDATO  AS BIGINT) AS NR_CANDIDATO,
        r.NM_CANDIDATO,
        r.NM_URNA_CANDIDATO,
        r.SG_PARTIDO,
        r.NM_PARTIDO,
        COALESCE(r.SG_FEDERACAO, '') AS SG_FEDERACAO,
        COALESCE(r.NM_FEDERACAO, '') AS NM_FEDERACAO
    FROM {ALIAS_2022}.resultados_2022 r
    WHERE r.SG_UF    = ?
      AND r.CD_CARGO = ?
      {municipio_filter_res}
      {partido_filter}
),

-- 4. Votos por candidato por bairro
votos_por_bairro AS (
    SELECT
        vs.NM_MUNICIPIO,
        bs.NM_BAIRRO,
        c.NM_URNA_CANDIDATO,
        c.NM_CANDIDATO,
        c.SG_PARTIDO,
        c.NM_PARTIDO,
        c.SG_FEDERACAO,
        c.NM_FEDERACAO,
        SUM(vs.QT_VOTOS) AS votos_candidato_bairro
    FROM votos_secao vs
    JOIN bairros_secao bs
        ON  vs.SG_UF        = bs.SG_UF
        AND vs.CD_MUNICIPIO = bs.CD_MUNICIPIO
        AND vs.NR_ZONA      = bs.NR_ZONA
        AND vs.NR_SECAO     = bs.NR_SECAO
    JOIN candidatos c
        ON  vs.SG_UF        = c.SG_UF
        AND vs.CD_MUNICIPIO = c.CD_MUNICIPIO
        AND vs.NR_VOTAVEL   = c.NR_CANDIDATO
    GROUP BY
        vs.NM_MUNICIPIO,
        bs.NM_BAIRRO,
        c.NM_URNA_CANDIDATO,
        c.NM_CANDIDATO,
        c.SG_PARTIDO,
        c.NM_PARTIDO,
        c.SG_FEDERACAO,
        c.NM_FEDERACAO
),

-- 5. Ranking por partido E por federação separadamente
ranking AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY NM_MUNICIPIO, NM_BAIRRO
            ORDER BY votos_candidato_bairro DESC
        ) AS rank_geral_bairro,

        -- Canibalização por partido
        COUNT(*) OVER (
            PARTITION BY NM_MUNICIPIO, NM_BAIRRO, SG_PARTIDO
        ) AS n_candidatos_partido_bairro,

        -- Canibalização por federação (só quando federação preenchida)
        CASE
            WHEN SG_FEDERACAO <> '' THEN
                COUNT(*) OVER (
                    PARTITION BY NM_MUNICIPIO, NM_BAIRRO, SG_FEDERACAO
                )
            ELSE 1
        END AS n_candidatos_federacao_bairro,

        SUM(votos_candidato_bairro) OVER (
            PARTITION BY NM_MUNICIPIO, NM_BAIRRO
        ) AS total_votos_bairro
    FROM votos_por_bairro
),

-- 6. Top N por bairro com votos mínimos
top_n_bairro AS (
    SELECT *
    FROM ranking
    WHERE rank_geral_bairro <= ?
      AND total_votos_bairro  >= ?
),

-- 7. Resultado final: canibalização via partido OU federação
resultado_final AS (
    SELECT
        NM_MUNICIPIO                                                   AS "Município",
        NM_BAIRRO                                                      AS "Bairro",
        NM_URNA_CANDIDATO                                              AS "Candidato (Urna)",
        NM_CANDIDATO                                                   AS "Candidato (Completo)",
        SG_PARTIDO                                                     AS "Partido",
        NM_PARTIDO                                                     AS "Nome Partido",
        SG_FEDERACAO                                                   AS "Federação",
        NM_FEDERACAO                                                   AS "Nome Federação",
        CAST(votos_candidato_bairro           AS BIGINT)               AS "Votos no Bairro",
        CAST(total_votos_bairro               AS BIGINT)               AS "Total Votos Bairro",
        ROUND(
            100.0 * votos_candidato_bairro / NULLIF(total_votos_bairro, 0),
            2
        )                                                              AS "% Bairro",
        CAST(rank_geral_bairro                AS BIGINT)               AS "Posição Bairro",
        CAST(n_candidatos_partido_bairro      AS BIGINT)               AS "Candidatos Partido/Bairro",
        CAST(n_candidatos_federacao_bairro    AS BIGINT)               AS "Candidatos Fed./Bairro",
        -- Status considera o maior dos dois contadores
        CASE
            WHEN GREATEST(n_candidatos_partido_bairro, n_candidatos_federacao_bairro)
                 >= {CRITICO_THRESHOLD} THEN 'CRÍTICO'
            WHEN GREATEST(n_candidatos_partido_bairro, n_candidatos_federacao_bairro)
                 >= {ALERTA_THRESHOLD}  THEN 'ALERTA'
            ELSE 'OK'
        END                                                            AS "Status Conflito",
        -- Tipo: FEDERAÇÃO tem precedência quando é o gatilho
        CASE
            WHEN n_candidatos_federacao_bairro > n_candidatos_partido_bairro
                 AND SG_FEDERACAO <> '' THEN 'FEDERAÇÃO'
            ELSE 'PARTIDO'
        END                                                            AS "Tipo Conflito"
    FROM top_n_bairro
)

SELECT *
FROM resultado_final
WHERE "Status Conflito" IN ('ALERTA', 'CRÍTICO')
  AND GREATEST("Candidatos Partido/Bairro", "Candidatos Fed./Bairro") >= ?
ORDER BY
    "Município",
    "Bairro",
    "Partido",
    "Posição Bairro"
"""
    # params order:
    # votos_secao:  uf, cd_cargo [, cd_municipio]
    # candidatos:   uf, cd_cargo [, cd_municipio] [, sg_partido]
    # top_n_bairro: top_n, MIN_VOTOS_BAIRRO
    # WHERE final:  ALERTA_THRESHOLD
    full_params = params_secao + params_candidatos + params_tail
    return sql, full_params


# ---------------------------------------------------------------------------
# Função pública principal
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def query_conflito_territorial(
    uf: str,
    cd_cargo: int,
    ano: int,
    sg_partido: str | None = None,
    cd_municipio: int | None = None,
    top_n: int = 10,
) -> tuple[pd.DataFrame, str]:
    """
    Executa a query de canibalização territorial e retorna o DataFrame final.

    Parameters
    ----------
    uf : str
        Sigla da UF (ex.: 'SP').
    cd_cargo : int
        Código do cargo (ex.: 13 para Vereador em 2024).
    ano : int
        Ano da eleição: 2024 ou 2022.
    sg_partido : str | None
        Filtra por partido (None = todos os partidos).
    cd_municipio : int | None
        Filtra por município (None = toda a UF).
    top_n : int
        Quantos candidatos por bairro considerar (padrão 10).

    Returns
    -------
    tuple[pd.DataFrame, str]
        (df_resultado, mensagem_erro)
        df_resultado: DataFrame com conflitos encontrados (vazio se nenhum)
        mensagem_erro: string vazia em caso de sucesso
    """
    con = get_connection()

    try:
        if ano == 2024:
            sql, params = _build_query_2024(uf, cd_cargo, sg_partido, cd_municipio, top_n)
        elif ano == 2022:
            sql, params = _build_query_2022(uf, cd_cargo, sg_partido, cd_municipio, top_n)
        else:
            return pd.DataFrame(), f"Ano {ano} não suportado."

        df = con.execute(sql, params).df()

        if df.empty:
            return df, ""

        return df, ""

    except duckdb.CatalogException as exc:
        msg = (
            f"Tabela não encontrada para UF={uf}, ano={ano}. "
            f"Verifique se o banco contém os dados desta UF. "
            f"Detalhe: {exc}"
        )
        return pd.DataFrame(), msg

    except Exception as exc:  # noqa: BLE001
        msg = f"Erro ao executar query de conflito: {exc}"
        return pd.DataFrame(), msg


# ---------------------------------------------------------------------------
# Métricas agregadas (separadas para cache independente)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=3600, show_spinner=False)
def calcular_metricas(df: pd.DataFrame) -> dict:
    """
    Calcula métricas de resumo a partir do DataFrame de conflitos.
    Recebe o DataFrame já filtrado para evitar re-query.
    """
    if df.empty:
        return {
            "bairros_em_conflito": 0,
            "candidatos_afetados": 0,
            "votos_em_risco": 0,
            "municipios_afetados": 0,
        }

    # Usa nomes de coluna em lowercase (aliases do SQL em português)
    col_bairro = "Bairro"
    col_candidato = "Candidato (Urna)"
    col_votos = "Votos no Bairro"
    col_municipio = "Município"

    return {
        "bairros_em_conflito": df[[col_municipio, col_bairro]].drop_duplicates().shape[0],
        "candidatos_afetados": df[col_candidato].nunique(),
        "votos_em_risco": int(df[col_votos].sum()),
        "municipios_afetados": df[col_municipio].nunique(),
    }
