"""
ui/filtros.py — Componentes do sidebar para seleção de filtros.
"""
import streamlit as st

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import CARGOS_POR_ANO, TOP_N_DEFAULT, TOP_N_MIN, TOP_N_MAX
from queries.conexao import listar_ufs, listar_municipios, listar_partidos


def render_filtros(con) -> dict:
    """
    Renderiza os controles do sidebar e retorna um dicionário com os valores
    selecionados pelo usuário.

    Parameters
    ----------
    con : duckdb.DuckDBPyConnection
        Conexão DuckDB (usada indiretamente via funções de listagem cacheadas).

    Returns
    -------
    dict com as chaves:
        ano          : int   — 2024 ou 2022
        uf           : str   — sigla da UF selecionada (ou '' se não selecionada)
        cd_cargo     : int   — código do cargo
        nm_cargo     : str   — nome legível do cargo
        sg_partido   : str | None — None = todos os partidos
        cd_municipio : int | None — None = todos os municípios
        top_n        : int   — quantidade de candidatos por bairro
    """
    with st.sidebar:
        st.title("Filtros")
        st.divider()

        # ------------------------------------------------------------------
        # Ano
        # ------------------------------------------------------------------
        ano: int = st.selectbox(
            label="Eleição",
            options=[2024, 2022],
            format_func=lambda a: f"{a} — {'Municipal' if a == 2024 else 'Geral'}",
            index=0,
            key="sb_ano",
        )

        st.divider()

        # ------------------------------------------------------------------
        # UF
        # ------------------------------------------------------------------
        ufs_disponiveis = listar_ufs(ano)
        uf_options = [""] + ufs_disponiveis

        uf: str = st.selectbox(
            label="UF",
            options=uf_options,
            format_func=lambda u: "— Selecione —" if u == "" else u,
            index=0,
            key="sb_uf",
        )

        # ------------------------------------------------------------------
        # Cargo (dinâmico pelo ano)
        # ------------------------------------------------------------------
        cargos_disponiveis = CARGOS_POR_ANO.get(ano, {})
        cargo_options = list(cargos_disponiveis.keys())

        cd_cargo: int = st.selectbox(
            label="Cargo",
            options=cargo_options,
            format_func=lambda c: cargos_disponiveis.get(c, str(c)),
            index=0,
            key="sb_cargo",
        )
        nm_cargo: str = cargos_disponiveis.get(cd_cargo, str(cd_cargo))

        st.divider()

        # ------------------------------------------------------------------
        # Município (opcional — só carrega se UF estiver selecionada)
        # ------------------------------------------------------------------
        cd_municipio: int | None = None

        if uf:
            municipios = listar_municipios(uf, ano)
            mun_options_labels = [("", "Todos os Municípios")] + [
                (str(cd), nm) for cd, nm in municipios
            ]
            mun_values = [x[0] for x in mun_options_labels]
            mun_labels = [x[1] for x in mun_options_labels]

            mun_idx = st.selectbox(
                label="Município",
                options=range(len(mun_values)),
                format_func=lambda i: mun_labels[i],
                index=0,
                key="sb_municipio",
            )
            mun_val = mun_values[mun_idx]
            cd_municipio = int(mun_val) if mun_val != "" else None
        else:
            st.selectbox(
                label="Município",
                options=["— Selecione uma UF primeiro —"],
                disabled=True,
                key="sb_municipio_disabled",
            )

        # ------------------------------------------------------------------
        # Partido (opcional — carrega após UF)
        # ------------------------------------------------------------------
        sg_partido: str | None = None

        if uf:
            partidos = listar_partidos(uf, cd_cargo, ano, cd_municipio)
            partido_options = [""] + partidos

            partido_sel: str = st.selectbox(
                label="Partido",
                options=partido_options,
                format_func=lambda p: "Todos" if p == "" else p,
                index=0,
                key="sb_partido",
            )
            sg_partido = partido_sel if partido_sel != "" else None
        else:
            st.selectbox(
                label="Partido",
                options=["— Selecione uma UF primeiro —"],
                disabled=True,
                key="sb_partido_disabled",
            )

        st.divider()

        # ------------------------------------------------------------------
        # Top N
        # ------------------------------------------------------------------
        top_n: int = st.slider(
            label="Top N candidatos por bairro",
            min_value=TOP_N_MIN,
            max_value=TOP_N_MAX,
            value=TOP_N_DEFAULT,
            step=1,
            help=(
                "Define quantos candidatos mais votados de cada bairro serão "
                "analisados. Valores maiores aumentam o escopo mas podem gerar "
                "mais ruído."
            ),
            key="sl_top_n",
        )

        st.divider()
        st.caption(
            "Moneyball Eleitoral — MVP v1.0\n\n"
            "Detecta canibalização de votos entre candidatos do mesmo partido "
            "ou federação em um mesmo bairro."
        )

    return {
        "ano": ano,
        "uf": uf,
        "cd_cargo": cd_cargo,
        "nm_cargo": nm_cargo,
        "sg_partido": sg_partido,
        "cd_municipio": cd_municipio,
        "top_n": top_n,
    }
