"""
app.py — Moneyball Eleitoral: Detecção de Canibalização Territorial de Votos.

Ponto de entrada do MVP Streamlit.
Execute com:
    streamlit run app.py
a partir da pasta mvp_streamlit/.
"""
import sys
import os

# Garante que imports relativos funcionem tanto em dev quanto em produção
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
import pandas as pd

from queries.conexao import get_connection
from queries.conflito import query_conflito_territorial, calcular_metricas
from ui.filtros import render_filtros
from ui.formatacao import aplicar_formatacao_df, fmt_numero, fmt_pct
from config import STATUS_COLORS

# ---------------------------------------------------------------------------
# Configuração da página — deve ser o primeiro comando Streamlit
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Moneyball Eleitoral",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS mínimo para highlight de status
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .status-critico  { color: #FF4B4B; font-weight: bold; }
    .status-alerta   { color: #FFA500; font-weight: bold; }
    div[data-testid="metric-container"] { border-left: 4px solid #1f77b4; padding-left: 0.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Moneyball Eleitoral")
st.markdown(
    """
    **Inteligência Geopolítica Eleitoral** — detecta *canibalização de votos*:
    situações em que dois ou mais candidatos do mesmo partido (ou federação)
    disputam os mesmos bairros nos **Top N** mais votados,
    fragmentando a base eleitoral e reduzindo as chances de eleição.

    Use os filtros no painel lateral para selecionar eleição, UF, cargo e partido.
    """,
    help="Baseado em dados TSE — eleições 2024 (municipal) e 2022 (geral).",
)

st.divider()

# ---------------------------------------------------------------------------
# Conexão DuckDB (singleton — cacheada por @st.cache_resource)
# ---------------------------------------------------------------------------
con = get_connection()

# ---------------------------------------------------------------------------
# Sidebar — filtros
# ---------------------------------------------------------------------------
filtros = render_filtros(con)

ano: int                 = filtros["ano"]
uf: str                  = filtros["uf"]
cd_cargo: int            = filtros["cd_cargo"]
nm_cargo: str            = filtros["nm_cargo"]
sg_partido: str | None   = filtros["sg_partido"]
cd_municipio: int | None = filtros["cd_municipio"]
nm_municipio: str | None = filtros["nm_municipio"]
top_n: int               = filtros["top_n"]

# ---------------------------------------------------------------------------
# Área principal — só renderiza quando UF estiver selecionada
# ---------------------------------------------------------------------------
if not uf:
    st.info(
        "Selecione uma **UF** no painel lateral para iniciar a análise.",
        icon="👈",
    )
    st.stop()

# Cabeçalho do contexto selecionado
partido_label    = sg_partido    if sg_partido    else "Todos os partidos"
municipio_label  = nm_municipio  if nm_municipio  else "Todos os municípios"
st.subheader(
    f"Análise: {ano} · {uf} · {nm_cargo} · {partido_label} · {municipio_label}"
)

# ---------------------------------------------------------------------------
# Execução da query principal
# ---------------------------------------------------------------------------
with st.spinner("Consultando DuckDB..."):
    df_resultado, erro = query_conflito_territorial(
        uf=uf,
        cd_cargo=cd_cargo,
        ano=ano,
        sg_partido=sg_partido,
        nm_municipio=nm_municipio,
        top_n=top_n,
    )

# Exibe erro crítico e para
if erro:
    st.error(erro)
    st.stop()

# ---------------------------------------------------------------------------
# Métricas resumo (4 colunas)
# ---------------------------------------------------------------------------
metricas = calcular_metricas(df_resultado)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        label="Bairros em Conflito",
        value=fmt_numero(metricas["bairros_em_conflito"]),
        help="Bairros onde ≥ 2 candidatos do mesmo partido/federação estão no Top N.",
    )

with col2:
    st.metric(
        label="Candidatos Afetados",
        value=fmt_numero(metricas["candidatos_afetados"]),
        help="Candidatos únicos envolvidos em situações de canibalização.",
    )

with col3:
    st.metric(
        label="Votos em Risco",
        value=fmt_numero(metricas["votos_em_risco"]),
        help="Soma de votos dos candidatos em conflito (votos que poderiam ser concentrados).",
    )

with col4:
    st.metric(
        label="Municípios Afetados",
        value=fmt_numero(metricas["municipios_afetados"]),
        help="Número de municípios com pelo menos um bairro em conflito.",
    )

st.divider()

# ---------------------------------------------------------------------------
# Resultado vazio — nenhum conflito encontrado
# ---------------------------------------------------------------------------
if df_resultado.empty:
    st.warning(
        "Nenhum conflito de canibalização encontrado para os filtros selecionados. "
        "Tente ampliar o escopo: aumente o **Top N**, selecione **Todos os partidos** "
        "ou escolha uma UF maior.",
        icon="✅",
    )
    st.stop()

# ---------------------------------------------------------------------------
# Tabs de visualização
# ---------------------------------------------------------------------------
tab_alertas, tab_ranking, tab_ajuda = st.tabs(
    ["⚠️ Alertas de Conflito", "📊 Ranking por Bairro", "ℹ️ Como interpretar"]
)

# ── Tab 1: Tabela de alertas ─────────────────────────────────────────────
with tab_alertas:
    st.markdown(
        f"**{len(df_resultado):,} linhas** com status ALERTA ou CRÍTICO "
        f"(Top {top_n} candidatos por bairro, mínimo 50 votos no bairro)."
    )

    # DataFrame formatado (strings PT-BR) para exibição
    df_fmt = aplicar_formatacao_df(df_resultado)

    # Determina colunas disponíveis para column_config
    colunas_disponiveis = set(df_fmt.columns)

    column_config: dict = {}

    if "Status Conflito" in colunas_disponiveis:
        column_config["Status Conflito"] = st.column_config.TextColumn(
            label="Status",
            help="CRÍTICO = ≥3 candidatos do mesmo partido/federação no Top N do bairro. "
                 "ALERTA = 2 candidatos.",
            width="small",
        )

    if "Votos no Bairro" in colunas_disponiveis:
        column_config["Votos no Bairro"] = st.column_config.TextColumn(
            label="Votos no Bairro",
            help="Total de votos do candidato neste bairro (turno 1).",
        )

    if "% Bairro" in colunas_disponiveis:
        column_config["% Bairro"] = st.column_config.TextColumn(
            label="% Bairro",
            help="Percentual de votos do candidato sobre o total de votos do bairro.",
        )

    if "Posição Bairro" in colunas_disponiveis:
        column_config["Posição Bairro"] = st.column_config.TextColumn(
            label="Posição",
            width="small",
        )

    if "Candidatos Partido/Bairro" in colunas_disponiveis:
        column_config["Candidatos Partido/Bairro"] = st.column_config.TextColumn(
            label="Cands. Partido/Bairro",
            help="Quantos candidatos do mesmo partido estão no Top N deste bairro.",
            width="small",
        )

    if "Candidatos Fed./Bairro" in colunas_disponiveis:
        column_config["Candidatos Fed./Bairro"] = st.column_config.TextColumn(
            label="Cands. Fed./Bairro",
            help="Quantos candidatos da mesma federação estão no Top N deste bairro.",
            width="small",
        )

    if "Tipo Conflito" in colunas_disponiveis:
        column_config["Tipo Conflito"] = st.column_config.TextColumn(
            label="Tipo",
            width="small",
        )

    # Highlight por cor usando styler
    def _highlight_status(val: str) -> str:
        if val == "CRÍTICO":
            return f"background-color: {STATUS_COLORS['CRÍTICO']}33; color: {STATUS_COLORS['CRÍTICO']}; font-weight: bold"
        elif val == "ALERTA":
            return f"background-color: {STATUS_COLORS['ALERTA']}33; color: {STATUS_COLORS['ALERTA']}; font-weight: bold"
        return ""

    if "Status Conflito" in df_fmt.columns:
        styled = df_fmt.style.map(_highlight_status, subset=["Status Conflito"])
    else:
        styled = df_fmt.style

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config=column_config,
    )

    # Botão de download CSV
    csv_bytes = df_resultado.to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig")
    st.download_button(
        label="⬇️ Baixar CSV",
        data=csv_bytes,
        file_name=f"conflitos_{ano}_{uf}_{nm_cargo.replace(' ', '_')}.csv",
        mime="text/csv",
    )

# ── Tab 2: Ranking por bairro ────────────────────────────────────────────
with tab_ranking:
    st.markdown("**Top 20 bairros** com maior número de candidatos do mesmo partido/federação em conflito.")

    col_bairro   = "Bairro"
    col_municipio = "Município"
    col_cands    = "Candidatos Partido/Bairro"
    col_votos    = "Votos no Bairro"
    col_status   = "Status Conflito"

    # Verifica colunas disponíveis
    if col_cands not in df_resultado.columns:
        # Fallback para 2022 que tem federação
        col_cands = "Candidatos Fed./Bairro" if "Candidatos Fed./Bairro" in df_resultado.columns else None

    if col_cands:
        # Agrupa por município+bairro: pega o maior contador de conflito e soma de votos
        agg_dict: dict = {
            col_cands: "max",
            col_votos: "sum",
        }
        if col_status in df_resultado.columns:
            agg_dict[col_status] = lambda s: (
                "CRÍTICO" if "CRÍTICO" in s.values else "ALERTA"
            )

        df_ranking = (
            df_resultado
            .groupby([col_municipio, col_bairro], as_index=False)
            .agg(agg_dict)
            .sort_values(col_cands, ascending=False)
            .head(20)
            .reset_index(drop=True)
        )
        df_ranking.index = df_ranking.index + 1  # rank começa em 1

        # Formata para exibição
        df_rank_fmt = df_ranking.copy()
        df_rank_fmt[col_votos] = df_rank_fmt[col_votos].apply(fmt_numero)

        st.dataframe(
            df_rank_fmt,
            use_container_width=True,
            column_config={
                col_cands: st.column_config.NumberColumn(
                    label="Candidatos em Conflito",
                    format="%d",
                ),
            },
        )

        # Bar chart com DuckDB-aggregated data (já agregada — apenas display)
        st.markdown("**Votos totais em bairros com conflito (Top 20):**")

        chart_df = (
            df_ranking[[col_bairro, col_votos]]
            .set_index(col_bairro)
        )
        # col_votos já foi formatado como string acima, usa o original
        chart_df_raw = (
            df_resultado
            .groupby([col_municipio, col_bairro], as_index=False)[col_votos]
            .sum()
            .sort_values(col_votos, ascending=False)
            .head(20)
        )
        chart_df_raw["label"] = (
            chart_df_raw[col_municipio].str[:10]
            + " / "
            + chart_df_raw[col_bairro].str[:20]
        )
        chart_df_raw = chart_df_raw.set_index("label")[[col_votos]]

        st.bar_chart(chart_df_raw, use_container_width=True)
    else:
        st.info("Coluna de candidatos por partido/bairro não disponível para ranking.")

# ── Tab 3: Como interpretar ──────────────────────────────────────────────
with tab_ajuda:
    st.markdown(
        """
        ## O que é canibalização de votos?

        Ocorre quando **dois ou mais candidatos do mesmo partido (ou federação eleitoral)**
        concentram sua votação nos **mesmos bairros**, disputando o mesmo eleitorado.

        Em sistemas proporcionais (vereadores, deputados), isso pode significar que nenhum
        deles atinge o quociente eleitoral, mesmo que a soma dos votos fosse suficiente
        para eleger um candidato.

        ---

        ## Como este sistema calcula

        1. **Dados por seção eleitoral** — cada seção é mapeada ao seu bairro via
           `eleitorado_local` (cross-walk: UF + Município + Zona + Seção).
        2. **Top N por bairro** — apenas os candidatos mais votados de cada bairro
           são considerados (configurável no painel lateral, padrão: 10).
        3. **Votos mínimos** — bairros com menos de 50 votos no total são ignorados.
        4. **ALERTA** — 2 candidatos do mesmo partido/federação no Top N do bairro.
        5. **CRÍTICO** — 3 ou mais candidatos do mesmo partido/federação no Top N.

        ---

        ## Federações (2022)

        Em 2022, partidos formaram federações eleitorais. Candidatos de partidos
        diferentes mas da mesma federação também são contabilizados em conjunto,
        pois dividem a mesma base eleitoral e os votos de legenda.

        A coluna **Tipo Conflito** indica se o conflito é por PARTIDO ou por FEDERAÇÃO.

        ---

        ## Dicas de uso

        - Comece selecionando uma **UF menor** (ex.: SE, RR) para ver os resultados
          mais rápido antes de escalar para SP ou MG.
        - Use o filtro de **Partido** para focar na análise do seu próprio partido.
        - Aumente o **Top N** para capturar conflitos em bairros mais dispersos.
        - Exporte o CSV para cruzar com a base de diretório do partido.

        ---

        ## Interpretação estratégica

        | Status   | Ação recomendada |
        |----------|-----------------|
        | ALERTA   | Mapear territórios sobrepostos; considerar acordo de divisão de bairros |
        | CRÍTICO  | Urgente: redistribuição de cabos eleitorais ou realinhamento de candidatura |

        > Os dados são da eleição passada (2024 municipal / 2022 geral) e servem como
        > **proxy** para projetar o comportamento da próxima eleição na mesma base territorial.
        """,
        unsafe_allow_html=False,
    )
