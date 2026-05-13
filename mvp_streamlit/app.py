"""
app.py — Moneyball Eleitoral: Canibalização Territorial de Votos
MVP v1.0  |  Streamlit + DuckDB
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from config import ALERTA_THRESHOLD, CRITICO_THRESHOLD, STATUS_COLORS
from queries.conexao import get_connection
from queries.conflito import calcular_metricas, query_conflito_territorial
from ui.filtros import render_filtros
from ui.formatacao import fmt_numero, fmt_pct

# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Moneyball Eleitoral",
    page_icon="🗳️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    div[data-testid="metric-container"] {
        border-left: 4px solid #1f77b4;
        padding-left: 0.6rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Conexão (singleton)
# ---------------------------------------------------------------------------
try:
    con = get_connection()
except Exception as exc:
    st.error(f"**Erro ao conectar ao banco:** {exc}")
    st.stop()

# ---------------------------------------------------------------------------
# Sidebar — filtros
# ---------------------------------------------------------------------------
filtros = render_filtros(con)

ano          = filtros["ano"]
uf           = filtros["uf"]
cd_cargo     = filtros["cd_cargo"]
nm_cargo     = filtros["nm_cargo"]
cd_municipio = filtros["cd_municipio"]
nm_municipio = filtros["nm_municipio"]
parties      = filtros["parties"]     # tuple[str]
top_n        = filtros["top_n"]

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("🗳️ Moneyball Eleitoral")
st.caption("Detecta candidatos do mesmo partido disputando o mesmo bairro (canibalização territorial).")

# Guia o usuário passo a passo
if not uf:
    st.info("👈 Selecione o **Estado** no painel lateral para começar.")
    st.stop()

if nm_municipio is None:
    st.info("👈 Selecione o **Município** no painel lateral para carregar a análise.")
    st.stop()

st.subheader(f"{nm_municipio} — {nm_cargo} · {ano}")
if parties:
    st.caption(f"Partidos filtrados: {', '.join(parties)}")

# ---------------------------------------------------------------------------
# Query principal
# ---------------------------------------------------------------------------
with st.spinner(f"Analisando geometria eleitoral de {nm_municipio}..."):
    df, erro = query_conflito_territorial(
        uf=uf,
        cd_cargo=cd_cargo,
        ano=ano,
        nm_municipio=nm_municipio,
        top_n=top_n,
        parties=parties if parties else None,
    )

if erro:
    st.error(erro)
    st.stop()

if df.empty:
    st.warning(
        "Nenhum dado retornado. Verifique se o banco contém dados para "
        f"**{nm_municipio}** · **{nm_cargo}** · **{ano}**."
    )
    st.stop()

# ---------------------------------------------------------------------------
# KPIs (baseados nos conflitos detectados)
# ---------------------------------------------------------------------------
metricas = calcular_metricas(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("🏘️ Bairros em Conflito",  fmt_numero(metricas["bairros_em_conflito"]))
c2.metric("👥 Candidatos Afetados",  fmt_numero(metricas["candidatos_afetados"]))
c3.metric("🗳️ Votos em Risco",       fmt_numero(metricas["votos_em_risco"]))
c4.metric("⚠️ Linhas em Conflito",   fmt_numero(metricas["pares_conflito"]))

st.divider()

# Alerta resumo (estilo app de referência)
conflitos = df[df["candidatos_mesmo_partido"] >= ALERTA_THRESHOLD]
if not conflitos.empty:
    n_bairros = conflitos["Bairro"].nunique()
    st.warning(
        f"⚠️ **Alerta de Canibalização Territorial:** detectamos **{n_bairros}** bairro(s) "
        f"onde candidatos da mesma legenda estão dividindo votos no Top {top_n}."
    )

# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_tabela, tab_conflitos, tab_ajuda = st.tabs(
    ["📋 Top N por Bairro", "🚨 Apenas Conflitos", "ℹ️ Como Interpretar"]
)

# ── Tab 1: tabela completa top N (igual ao app de referência) ───────────────
with tab_tabela:
    st.markdown(
        f"**{len(df):,} candidatos** no Top {top_n} por bairro em {nm_municipio}. "
        f"Linhas em vermelho = canibalização detectada."
    )

    def _highlight_conflict(val):
        if val >= CRITICO_THRESHOLD:
            return f"background-color: {STATUS_COLORS['CRÍTICO']}33; color: {STATUS_COLORS['CRÍTICO']}; font-weight:bold"
        if val >= ALERTA_THRESHOLD:
            return f"background-color: {STATUS_COLORS['ALERTA']}33; color: {STATUS_COLORS['ALERTA']}; font-weight:bold"
        return ""

    # Colunas a exibir (presentes em 2024 e 2022)
    cols_base = ["Bairro", "Partido", "Candidato", "Situacao", "Votos",
                 "candidatos_mesmo_partido", "Status"]
    # 2022 adiciona Federacao e candidatos_mesma_federacao
    cols_extra = [c for c in ["Federacao", "candidatos_mesma_federacao"] if c in df.columns]
    cols_show = [c for c in cols_base + cols_extra if c in df.columns]

    df_display = df[cols_show].copy()
    df_display["Votos"] = df_display["Votos"].apply(fmt_numero)

    styled = df_display.style.map(
        _highlight_conflict, subset=["candidatos_mesmo_partido"]
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)

    csv = df[cols_show].to_csv(index=False, sep=";", decimal=",", encoding="utf-8-sig")
    st.download_button(
        "⬇️ Baixar CSV completo",
        data=csv,
        file_name=f"topN_{nm_municipio}_{ano}_{nm_cargo.replace(' ','_')}.csv",
        mime="text/csv",
    )

# ── Tab 2: apenas conflitos ─────────────────────────────────────────────────
with tab_conflitos:
    if conflitos.empty:
        st.success("✅ Nenhum conflito detectado com os filtros atuais.")
    else:
        st.markdown(f"**{len(conflitos):,} linha(s)** com status ALERTA ou CRÍTICO.")

        # Agrupa por bairro + partido para exibição em expanders
        grupos = conflitos.groupby(["Bairro", "Partido"], sort=False)
        for (bairro, partido), grupo in grupos:
            status = grupo["Status"].iloc[0]
            cor = STATUS_COLORS.get(status, "#888")
            label = (
                f"**{bairro}** › {partido} "
                f"— {len(grupo)} candidato(s) | "
                f":{cor.lstrip('#')}[{status}]"
            )
            with st.expander(f"{bairro} › {partido}  [{status}]  ({len(grupo)} cands.)",
                             expanded=(status == "CRÍTICO")):
                g = grupo[cols_show].copy()
                g["Votos"] = g["Votos"].apply(fmt_numero)
                st.dataframe(g.reset_index(drop=True), use_container_width=True, hide_index=True)
                st.caption(
                    f"Total de votos em conflito neste bairro: "
                    f"**{fmt_numero(int(grupo['Votos'].sum()))}**"
                )

        csv_conf = conflitos[cols_show].to_csv(
            index=False, sep=";", decimal=",", encoding="utf-8-sig"
        )
        st.download_button(
            "⬇️ Baixar conflitos CSV",
            data=csv_conf,
            file_name=f"conflitos_{nm_municipio}_{ano}.csv",
            mime="text/csv",
        )

# ── Tab 3: como interpretar ─────────────────────────────────────────────────
with tab_ajuda:
    st.markdown(
        f"""
## O que é canibalização territorial?

Quando **{ALERTA_THRESHOLD} ou mais candidatos do mesmo partido** aparecem no
**Top {top_n}** de um mesmo bairro, eles dividem a base eleitoral em vez de
complementar territórios — reduzindo as chances de eleição de ambos.

## Como este painel calcula

| Passo | O que acontece |
|-------|----------------|
| 1 | Filtra as seções eleitorais do município na tabela `votacao_secao_votacao_secao_{ano}_UF` |
| 2 | Cruza seção → bairro via `eleitorado_local` (chave: `nr_zona + nr_secao`) |
| 3 | Une com metadados de candidatos via `resultados_{ano}` |
| 4 | Agrega votos por candidato × bairro |
| 5 | Aplica `ROW_NUMBER()` e `COUNT()` via Window Functions no DuckDB |
| 6 | Retorna os Top {top_n} candidatos de cada bairro com o indicador `candidatos_mesmo_partido` |

## Legenda de status

| Status | Condição | Ação sugerida |
|--------|----------|---------------|
| 🟠 **ALERTA** | 2 candidatos do partido no Top {top_n} | Mapear sobreposição territorial |
| 🔴 **CRÍTICO** | ≥ 3 candidatos do partido no Top {top_n} | Redistribuição urgente de cabos eleitorais |

{"## Federações (2022) — O sistema verifica `SG_FEDERACAO` separadamente, pois candidatos de partidos distintos da mesma federação também disputam a mesma base eleitoral." if ano == 2022 else ""}
        """
    )
