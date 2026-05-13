"""
ui/filtros.py — Sidebar de filtros do MVP Moneyball Eleitoral.
"""
import streamlit as st

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import CARGOS_POR_ANO, TOP_N_DEFAULT, TOP_N_MIN, TOP_N_MAX
from queries.conexao import listar_ufs, listar_municipios, listar_partidos


def render_filtros(con) -> dict:
    """
    Renderiza o sidebar e retorna os filtros selecionados.

    Retorna dict com:
        ano          : int
        uf           : str  ('' se não selecionado)
        cd_cargo     : int
        nm_cargo     : str
        cd_municipio : int | None
        nm_municipio : str | None   — nome exato do TSE para predicate pushdown
        parties      : tuple[str]   — tuple vazia = todos os partidos
        top_n        : int
    """
    with st.sidebar:
        st.title("⚙️ Filtros")
        st.divider()

        # ── Eleição ────────────────────────────────────────────────────────
        ano: int = st.selectbox(
            label="Eleição",
            options=[2024, 2022],
            format_func=lambda a: f"{a} — {'Municipal' if a == 2024 else 'Geral'}",
            index=0,
            key="sb_ano",
        )

        st.divider()

        # ── UF ─────────────────────────────────────────────────────────────
        ufs_disponiveis = listar_ufs(ano)
        uf: str = st.selectbox(
            label="Estado (UF)",
            options=[""] + ufs_disponiveis,
            format_func=lambda u: "— Selecione —" if u == "" else u,
            index=0,
            key="sb_uf",
        )

        # ── Cargo ──────────────────────────────────────────────────────────
        cargos_disponiveis = CARGOS_POR_ANO.get(ano, {})
        cd_cargo: int = st.selectbox(
            label="Cargo",
            options=list(cargos_disponiveis.keys()),
            format_func=lambda c: cargos_disponiveis.get(c, str(c)),
            index=0,
            key="sb_cargo",
        )
        nm_cargo: str = cargos_disponiveis.get(cd_cargo, str(cd_cargo))

        st.divider()

        # ── Município (obrigatório para predicate pushdown) ─────────────────
        cd_municipio: int | None = None
        nm_municipio: str | None = None

        if uf:
            municipios = listar_municipios(uf, ano)   # list[(cd_int, nm_str)]
            mun_options = [(None, "— Selecione o município —")] + list(municipios)

            mun_idx = st.selectbox(
                label="Município ★",
                options=range(len(mun_options)),
                format_func=lambda i: mun_options[i][1],
                index=0,
                key="sb_municipio",
                help="Obrigatório — filtra os dados na raiz da query (predicate pushdown).",
            )
            selected = mun_options[mun_idx]
            if selected[0] is not None:
                cd_municipio = selected[0]
                nm_municipio = selected[1]
        else:
            st.selectbox(
                label="Município ★",
                options=["— Selecione uma UF primeiro —"],
                disabled=True,
                key="sb_municipio_disabled",
            )

        # ── Partidos (multiselect opcional) ────────────────────────────────
        parties: tuple[str, ...] = ()

        if uf and cd_municipio is not None:
            partidos_disponiveis = listar_partidos(uf, cd_cargo, ano, cd_municipio)
            sel = st.multiselect(
                label="Partidos (opcional)",
                options=partidos_disponiveis,
                default=[],
                key="ms_partidos",
                help="Deixe vazio para analisar todos os partidos.",
            )
            parties = tuple(sel)
        else:
            st.multiselect(
                label="Partidos (opcional)",
                options=[],
                disabled=True,
                key="ms_partidos_disabled",
            )

        st.divider()

        # ── Top N ──────────────────────────────────────────────────────────
        top_n: int = st.slider(
            label="Top N candidatos por bairro",
            min_value=TOP_N_MIN,
            max_value=TOP_N_MAX,
            value=TOP_N_DEFAULT,
            step=1,
            help="Quantos candidatos mais votados de cada bairro considerar.",
            key="sl_top_n",
        )

        st.divider()
        st.caption("Moneyball Eleitoral — MVP v1.0")

    return {
        "ano":          ano,
        "uf":           uf,
        "cd_cargo":     cd_cargo,
        "nm_cargo":     nm_cargo,
        "cd_municipio": cd_municipio,
        "nm_municipio": nm_municipio,
        "parties":      parties,
        "top_n":        top_n,
    }
