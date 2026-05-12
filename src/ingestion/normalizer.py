"""
Normalizador: transforma ResultadoSecao (granularidade de seção) em
ResultadoBairro e ResultadoMunicipio, que são as unidades de análise
estratégica do sistema.

Fluxo:
  ResultadoSecao[]
      → _agrupar_por_bairro()   → ResultadoBairro[]
      → _agrupar_por_municipio() → ResultadoMunicipio[]
      → calcular_heranca()       → HerancaEleitoral[]
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Sequence

from ..models.electoral import (
    CargoEnum,
    HerancaEleitoral,
    ResultadoBairro,
    ResultadoMunicipio,
    ResultadoSecao,
)
from ..models.candidates import Candidato, Chapa, TerritorioCandidato

logger = logging.getLogger(__name__)

# Chave de agrupamento de bairro: (ano, cargo, municipio, bairro, partido)
_ChaveBairro = tuple[int, str, str, str, str]
# Chave de agrupamento de município: (ano, cargo, municipio, partido)
_ChaveMunicipio = tuple[int, str, str, str]


def agrupar_por_bairro(
    resultados: Sequence[ResultadoSecao],
    mapa_secao_bairro: dict[str, str] | None = None,
    mapa_nome_bairro: dict[str, str] | None = None,
) -> list[ResultadoBairro]:
    """
    Agrega ResultadoSecao por (ano, cargo, municipio, bairro, partido).

    mapa_secao_bairro: {secao_id → codigo_bairro}
    mapa_nome_bairro:  {codigo_bairro → nome_bairro}
    """
    acum: dict[_ChaveBairro, ResultadoBairro] = {}

    for r in resultados:
        # Resolver bairro a partir do mapa externo ou do próprio registro
        bairro_cod = r.codigo_bairro
        if not bairro_cod and mapa_secao_bairro:
            secao_id = f"{r.codigo_municipio}-{r.codigo_zona}-{r.codigo_secao}"
            bairro_cod = mapa_secao_bairro.get(secao_id)
        bairro_cod = bairro_cod or "SEM_BAIRRO"

        nome_bairro = "Sem Bairro"
        if mapa_nome_bairro and bairro_cod in mapa_nome_bairro:
            nome_bairro = mapa_nome_bairro[bairro_cod]

        chave: _ChaveBairro = (
            r.ano_eleicao,
            r.cargo.value,
            r.codigo_municipio,
            bairro_cod,
            r.sigla_partido,
        )

        if chave not in acum:
            acum[chave] = ResultadoBairro(
                ano_eleicao=r.ano_eleicao,
                cargo=r.cargo,
                codigo_bairro=bairro_cod,
                nome_bairro=nome_bairro,
                codigo_municipio=r.codigo_municipio,
                sigla_partido=r.sigla_partido,
            )

        rb = acum[chave]
        rb.votos_validos_bairro += r.votos_validos_secao

        if r.numero_candidato:
            rb.votos_por_candidato[r.numero_candidato] = (
                rb.votos_por_candidato.get(r.numero_candidato, 0) + r.votos
            )
        else:
            rb.votos_legenda += r.votos_legenda

    return list(acum.values())


def agrupar_por_municipio(
    resultados: Sequence[ResultadoSecao],
    total_vagas_por_municipio: dict[str, int] | None = None,
) -> list[ResultadoMunicipio]:
    """Agrega por (ano, cargo, municipio, partido), calcula quociente."""
    acum: dict[_ChaveMunicipio, ResultadoMunicipio] = {}
    validos_mun: dict[tuple[int, str, str], int] = defaultdict(int)

    for r in resultados:
        chave_mun = (r.ano_eleicao, r.cargo.value, r.codigo_municipio)
        validos_mun[chave_mun] += r.votos_validos_secao

        chave: _ChaveMunicipio = (
            r.ano_eleicao,
            r.cargo.value,
            r.codigo_municipio,
            r.sigla_partido,
        )
        if chave not in acum:
            acum[chave] = ResultadoMunicipio(
                ano_eleicao=r.ano_eleicao,
                cargo=r.cargo,
                codigo_municipio=r.codigo_municipio,
                nome_municipio=r.nome_candidato or "",  # será preenchido depois
                sigla_partido=r.sigla_partido,
                total_vagas=total_vagas_por_municipio.get(r.codigo_municipio, 9)
                if total_vagas_por_municipio else 9,
            )
        rm = acum[chave]
        if r.numero_candidato:
            rm.total_votos_partido += r.votos
        else:
            rm.total_votos_partido += r.votos_legenda

    # Preencher total de votos válidos por município
    for (ano, cargo, mun, partido), rm in acum.items():
        rm.total_votos_validos = validos_mun[(ano, cargo, mun)]

    return list(acum.values())


def construir_territorios_candidato(
    resultados_bairro: Sequence[ResultadoBairro],
    chapa: Chapa,
) -> None:
    """
    Preenche in-place os TerritorioCandidato de cada Candidato da Chapa
    usando os ResultadoBairro históricos.
    """
    # Índice de candidatos por número
    idx: dict[str, Candidato] = {c.numero: c for c in chapa.candidatos}

    # Mapa: candidato → lista de (bairro_cod, votos)
    votos_por_candidato: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    validos_por_bairro: dict[str, int] = {}

    for rb in resultados_bairro:
        if rb.sigla_partido != chapa.sigla_partido:
            continue
        validos_por_bairro[rb.codigo_bairro] = max(
            validos_por_bairro.get(rb.codigo_bairro, 0),
            rb.votos_validos_bairro,
        )
        for num, votos in rb.votos_por_candidato.items():
            votos_por_candidato[num][rb.codigo_bairro] += votos

    for num, candidato in idx.items():
        if num not in votos_por_candidato:
            continue
        bairro_votos = votos_por_candidato[num]
        total_cand = sum(bairro_votos.values())
        candidato.total_votos_historicos = total_cand

        territorios = []
        for bairro_cod, votos in bairro_votos.items():
            validos = validos_por_bairro.get(bairro_cod, 1) or 1
            pct_bairro = votos / validos
            pct_cand = votos / total_cand if total_cand > 0 else 0.0
            territorios.append(
                TerritorioCandidato(
                    codigo_bairro=bairro_cod,
                    nome_bairro=bairro_cod,
                    votos_historicos=votos,
                    percentual_no_bairro=pct_bairro,
                    percentual_do_candidato=pct_cand,
                )
            )
        candidato.territorios = sorted(territorios, key=lambda t: t.votos_historicos, reverse=True)

        # Índice de concentração Herfindahl-Hirschman
        if total_cand > 0:
            candidato.indice_concentracao = sum(
                (v / total_cand) ** 2 for v in bairro_votos.values()
            )

        total_bairros = len(validos_por_bairro)
        candidato.cobertura_geografica = (
            len(bairro_votos) / total_bairros if total_bairros > 0 else 0.0
        )


def calcular_heranca(
    resultados_municipal: Sequence[ResultadoBairro],
    resultados_estadual: Sequence[ResultadoBairro],
    sigla_partido: str,
) -> list[HerancaEleitoral]:
    """
    Cruza votação municipal (referência de base territorial) com estadual
    para mensurar conversão de herança eleitoral por bairro.
    """
    # Municipal por bairro
    mun_idx: dict[str, ResultadoBairro] = {}
    for rb in resultados_municipal:
        if rb.sigla_partido == sigla_partido and rb.cargo in (
            CargoEnum.PREFEITO, CargoEnum.VEREADOR
        ):
            existing = mun_idx.get(rb.codigo_bairro)
            if existing is None:
                mun_idx[rb.codigo_bairro] = rb
            else:
                # merge
                for num, v in rb.votos_por_candidato.items():
                    existing.votos_por_candidato[num] = existing.votos_por_candidato.get(num, 0) + v
                existing.votos_validos_bairro = max(
                    existing.votos_validos_bairro, rb.votos_validos_bairro
                )

    # Estadual por bairro
    est_idx: dict[str, ResultadoBairro] = {}
    for rb in resultados_estadual:
        if rb.sigla_partido == sigla_partido:
            est_idx[rb.codigo_bairro] = rb

    herancas = []
    for bairro_cod, rb_mun in mun_idx.items():
        rb_est = est_idx.get(bairro_cod)
        heranca = HerancaEleitoral(
            codigo_bairro=bairro_cod,
            nome_bairro=rb_mun.nome_bairro,
            codigo_municipio=rb_mun.codigo_municipio,
            votos_prefeito_bairro=rb_mun.votos_por_candidato.get("prefeito", 0),
            votos_vereadores_bairro=sum(
                v for k, v in rb_mun.votos_por_candidato.items() if k != "prefeito"
            ),
            total_validos_municipal=rb_mun.votos_validos_bairro,
            votos_legenda_estadual=rb_est.votos_legenda if rb_est else 0,
            total_validos_estadual=rb_est.votos_validos_bairro if rb_est else 0,
        )
        herancas.append(heranca)

    return herancas
