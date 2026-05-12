"""
Rotas de análise: conflito, oportunidade, otimização e simulação.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ...engines.conflict import detectar_conflitos, resumo_conflitos
from ...engines.opportunity import analisar_bairros, mapa_oportunidade_conflito
from ...engines.optimizer import otimizar_alocacao, simular_acordo_territorial
from ...models.candidates import (
    Candidato,
    Chapa,
    TerritorioCandidato,
)
from ...models.electoral import CargoEnum, ResultadoMunicipio, TipoEleicaoEnum
from ...models.spatial import Bairro
from ..schemas import (
    AlertaConflitoPydantic,
    AnaliseCompletaRequest,
    AnaliseCompletaResponse,
    AlocacaoRecursoPydantic,
    BairroAnalisadoPydantic,
    ChapaInput,
    ConflitosResponse,
    MapaOportunidadeResponse,
    OtimizacaoResponse,
    SimulacaoAcordoRequest,
    SimulacaoAcordoResponse,
)

router = APIRouter(prefix="/analise", tags=["Análise"])


def _chapa_from_input(inp: ChapaInput) -> Chapa:
    try:
        cargo = CargoEnum(inp.cargo)
    except ValueError:
        raise HTTPException(422, f"Cargo inválido: {inp.cargo}")

    candidatos = []
    for c in inp.candidatos:
        try:
            cargo_c = CargoEnum(c.cargo)
        except ValueError:
            cargo_c = cargo
        candidatos.append(Candidato(
            numero=c.numero,
            nome=c.nome,
            cargo=cargo_c,
            sigla_partido=c.sigla_partido,
            codigo_municipio=c.codigo_municipio,
            ano_eleicao=c.ano_eleicao,
            total_votos_historicos=c.total_votos_historicos,
        ))

    chapa = Chapa(
        sigla_partido=inp.sigla_partido,
        numero_partido=inp.numero_partido,
        codigo_municipio=inp.codigo_municipio,
        ano_eleicao=inp.ano_eleicao,
        cargo=cargo,
        candidatos=candidatos,
        total_vagas_disputa=inp.total_vagas_disputa,
        fundo_total_reais=inp.fundo_total_reais,
        meta_quociente_partidario=inp.meta_quociente_partidario,
    )

    # Mapear territórios para candidatos
    idx = {c.numero: c for c in chapa.candidatos}
    for t in inp.territorios:
        cand = idx.get(t.numero_candidato)
        if cand is None:
            continue
        tc = TerritorioCandidato(
            codigo_bairro=t.codigo_bairro,
            nome_bairro=t.codigo_bairro,
            votos_historicos=t.votos_historicos,
            percentual_do_candidato=0.0,
        )
        cand.territorios.append(tc)

    # Recalcular percentuais
    for cand in chapa.candidatos:
        total = sum(t.votos_historicos for t in cand.territorios)
        if cand.total_votos_historicos == 0:
            cand.total_votos_historicos = total
        total = cand.total_votos_historicos or 1
        for t in cand.territorios:
            t.percentual_do_candidato = t.votos_historicos / total
        if total > 0:
            cand.indice_concentracao = sum(
                (t.votos_historicos / total) ** 2 for t in cand.territorios
            )

    return chapa


def _resultado_municipio(
    codigo_municipio: str,
    sigla_partido: str,
    total_votos: int,
    total_vagas: int,
    votos_partido: int,
) -> ResultadoMunicipio:
    rm = ResultadoMunicipio(
        ano_eleicao=2024,
        cargo=CargoEnum.DEPUTADO_ESTADUAL,
        codigo_municipio=codigo_municipio,
        nome_municipio=codigo_municipio,
        sigla_partido=sigla_partido,
        total_votos_partido=votos_partido,
        total_votos_validos=total_votos,
        total_vagas=total_vagas,
    )
    return rm


@router.post("/conflitos", response_model=ConflitosResponse)
def analisar_conflitos(payload: ChapaInput, limiar: float = 0.15):
    """Detecta pares de candidatos com sobreposição territorial."""
    chapa = _chapa_from_input(payload)
    alertas = detectar_conflitos(chapa, limiar_sobreposicao=limiar)
    resumo = resumo_conflitos(alertas)
    return ConflitosResponse(
        resumo=resumo,
        alertas=[
            AlertaConflitoPydantic(
                candidato_a=a.candidato_a,
                nome_a=a.nome_a,
                candidato_b=a.candidato_b,
                nome_b=a.nome_b,
                sobreposicao_jaccard=a.sobreposicao_jaccard,
                sobreposicao_ponderada=a.sobreposicao_ponderada,
                bairros_conflito=a.bairros_conflito,
                favorecido_por_bairro=a.favorecido_por_bairro,
                perda_estimada_votos=a.perda_estimada_votos,
                nivel_alerta=a.nivel_alerta,
                descricao=a.descricao,
            )
            for a in alertas
        ],
    )


@router.post("/mapa", response_model=MapaOportunidadeResponse)
def mapa_oportunidade(payload: AnaliseCompletaRequest):
    """Classifica bairros em categorias de oportunidade e conflito."""
    chapa = _chapa_from_input(payload.chapa)
    alertas = detectar_conflitos(chapa, payload.limiar_sobreposicao)

    # Contagem de conflitos por bairro
    conflito_por_bairro: dict[str, int] = {}
    for a in alertas:
        for b in a.bairros_conflito:
            conflito_por_bairro[b] = conflito_por_bairro.get(b, 0) + 1

    bairros = [
        Bairro(
            codigo_bairro=b["codigo"],
            nome_bairro=b["nome"],
            codigo_municipio=payload.chapa.codigo_municipio,
            nome_municipio=payload.chapa.codigo_municipio,
            total_eleitores=b.get("total_eleitores", 5000),
        )
        for b in payload.bairros_info
    ]

    # Construir ResultadoBairro sintético a partir dos territórios
    from ...models.electoral import ResultadoBairro
    resultados_bairro = []
    for b in bairros:
        rb = ResultadoBairro(
            ano_eleicao=payload.chapa.ano_eleicao,
            cargo=CargoEnum(payload.chapa.cargo),
            codigo_bairro=b.codigo_bairro,
            nome_bairro=b.nome_bairro,
            codigo_municipio=b.codigo_municipio,
            sigla_partido=payload.chapa.sigla_partido,
            votos_validos_bairro=b.total_eleitores,
        )
        for cand in chapa.candidatos:
            for t in cand.territorios:
                if t.codigo_bairro == b.codigo_bairro:
                    rb.votos_por_candidato[cand.numero] = t.votos_historicos
        resultados_bairro.append(rb)

    bairros_analisados = analisar_bairros(
        bairros, resultados_bairro, chapa, conflito_por_bairro
    )
    mapa = mapa_oportunidade_conflito(bairros_analisados)

    def ba_to_pydantic(b):
        return BairroAnalisadoPydantic(
            codigo=b.codigo_bairro,
            nome=b.nome_bairro,
            categoria=b.categoria,
            prioridade=b.prioridade,
            forca_legenda_pct=round(b.forca_legenda * 100, 2),
            candidatos_presentes=b.candidatos_presentes,
            n_conflito=b.n_candidatos_conflito,
            potencial_votos_extras=b.potencial_votos_extras,
            elasticidade=round(b.elasticidade_bairro, 3),
            indice_vacuo=round(b.indice_vacuo, 3),
            indice_heranca=round(b.indice_heranca, 3),
        )

    return MapaOportunidadeResponse(
        total_bairros=mapa["total_bairros"],
        por_categoria=mapa["por_categoria"],
        bairros=[ba_to_pydantic(b) for b in bairros_analisados],
        top_oportunidades=[ba_to_pydantic(b) for b in mapa["top_oportunidades"]],
        zonas_guerra=[ba_to_pydantic(b) for b in mapa["zonas_guerra"]],
    )


@router.post("/otimizar", response_model=OtimizacaoResponse)
def otimizar(payload: AnaliseCompletaRequest):
    """Sugere distribuição ótima do fundo eleitoral entre candidatos."""
    chapa = _chapa_from_input(payload.chapa)
    alertas = detectar_conflitos(chapa, payload.limiar_sobreposicao)

    conflito_por_bairro: dict[str, int] = {}
    for a in alertas:
        for b in a.bairros_conflito:
            conflito_por_bairro[b] = conflito_por_bairro.get(b, 0) + 1

    bairros = [
        Bairro(
            codigo_bairro=b["codigo"],
            nome_bairro=b["nome"],
            codigo_municipio=payload.chapa.codigo_municipio,
            nome_municipio=payload.chapa.codigo_municipio,
            total_eleitores=b.get("total_eleitores", 5000),
        )
        for b in payload.bairros_info
    ]
    from ...models.electoral import ResultadoBairro
    resultados_bairro = []
    for b in bairros:
        rb = ResultadoBairro(
            ano_eleicao=payload.chapa.ano_eleicao,
            cargo=CargoEnum(payload.chapa.cargo),
            codigo_bairro=b.codigo_bairro,
            nome_bairro=b.nome_bairro,
            codigo_municipio=b.codigo_municipio,
            sigla_partido=payload.chapa.sigla_partido,
            votos_validos_bairro=b.total_eleitores,
        )
        for cand in chapa.candidatos:
            for t in cand.territorios:
                if t.codigo_bairro == b.codigo_bairro:
                    rb.votos_por_candidato[cand.numero] = t.votos_historicos
        resultados_bairro.append(rb)

    bairros_analisados = analisar_bairros(
        bairros, resultados_bairro, chapa, conflito_por_bairro
    )

    votos_partido = sum(c.total_votos_historicos for c in chapa.candidatos)
    rm = _resultado_municipio(
        payload.chapa.codigo_municipio,
        payload.chapa.sigla_partido,
        payload.total_votos_validos,
        payload.total_vagas,
        votos_partido,
    )

    resultado = otimizar_alocacao(chapa, rm, bairros_analisados, alertas)

    return OtimizacaoResponse(
        qp_atual=resultado.qp_atual,
        qp_projetado=resultado.qp_projetado,
        vagas_atuais=resultado.vagas_atuais,
        vagas_projetadas=resultado.vagas_projetadas,
        alocacoes=[
            AlocacaoRecursoPydantic(
                numero_candidato=a.numero_candidato,
                nome_candidato=a.nome_candidato,
                percentual_atual=round(a.percentual_atual * 100, 2),
                percentual_otimizado=round(a.percentual_otimizado * 100, 2),
                votos_projetados=a.votos_projetados,
                justificativa=a.justificativa,
            )
            for a in resultado.alocacoes
        ],
        alertas_atendidos=resultado.alertas_atendidos,
        alertas_pendentes=resultado.alertas_pendentes,
    )


@router.post("/simular-acordo", response_model=SimulacaoAcordoResponse)
def simular_acordo(payload: SimulacaoAcordoRequest):
    """Simula impacto de um acordo territorial entre candidatos da chapa."""
    chapa = _chapa_from_input(payload.chapa)

    bairros_todos = set()
    for cand in chapa.candidatos:
        for t in cand.territorios:
            bairros_todos.add(t.codigo_bairro)

    bairros = [
        Bairro(
            codigo_bairro=b,
            nome_bairro=b,
            codigo_municipio=payload.chapa.codigo_municipio,
            nome_municipio=payload.chapa.codigo_municipio,
            total_eleitores=5000,
        )
        for b in bairros_todos
    ]

    from ...models.electoral import ResultadoBairro
    resultados_bairro = [
        ResultadoBairro(
            ano_eleicao=payload.chapa.ano_eleicao,
            cargo=CargoEnum(payload.chapa.cargo),
            codigo_bairro=b.codigo_bairro,
            nome_bairro=b.nome_bairro,
            codigo_municipio=b.codigo_municipio,
            sigla_partido=payload.chapa.sigla_partido,
            votos_validos_bairro=5000,
        )
        for b in bairros
    ]

    bairros_analisados = analisar_bairros(bairros, resultados_bairro, chapa, {})

    rm = _resultado_municipio(
        payload.chapa.codigo_municipio,
        payload.chapa.sigla_partido,
        payload.total_votos_validos,
        payload.total_vagas,
        sum(c.total_votos_historicos for c in chapa.candidatos),
    )

    cenario = simular_acordo_territorial(
        chapa, payload.territorios_fixados, rm, bairros_analisados, payload.nome_cenario
    )

    return SimulacaoAcordoResponse(
        nome_cenario=cenario.nome_cenario,
        territorios_fixados=cenario.territorios_fixados,
        votos_projetados_por_candidato=cenario.votos_projetados_por_candidato,
        total_votos_chapa=cenario.total_votos_chapa,
        qp_projetado=cenario.qp_projetado,
        vagas_projetadas=cenario.vagas_projetadas,
        ganho_vs_baseline=cenario.ganho_vs_baseline,
    )


@router.post("/completa", response_model=AnaliseCompletaResponse)
def analise_completa(payload: AnaliseCompletaRequest):
    """Executa pipeline completo: conflitos + mapa + otimização."""
    conflitos = analisar_conflitos(payload.chapa, payload.limiar_sobreposicao)
    mapa = mapa_oportunidade(payload)
    otimizacao = otimizar(payload)
    return AnaliseCompletaResponse(
        conflitos=conflitos,
        mapa=mapa,
        otimizacao=otimizacao,
    )
