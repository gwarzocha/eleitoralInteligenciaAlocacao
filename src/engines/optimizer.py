"""
Motor de Otimização de Recursos e Acordo Territorial.

Objetivo: maximizar o Quociente Partidário (QP) distribuindo o fundo
eleitoral entre os candidatos da chapa.

Restrições:
  - Soma dos recursos alocados = 100% do fundo
  - Respeitar limites mínimos e máximos por candidato
  - Penalizar alocação em pares com conflito crítico (evitar canibalização)
  - Bônus para candidatos que cobrem "áreas órfãs" (vácuos de representação)

Algoritmo: Programação Linear (LP) simplificada via método de gradiente
escalado, sem dependência de solver externo. Para produção real, substituir
pelo scipy.optimize.linprog ou PuLP.

Simulador de Acordo Territorial:
  Permite ao gestor fixar território de cada candidato e recalcular
  a projeção de votos e QP resultante.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from ..models.candidates import AlertaConflito, Candidato, Chapa
from ..models.electoral import ResultadoMunicipio
from .opportunity import BairroAnalisado


@dataclass
class AlocacaoRecurso:
    numero_candidato: str
    nome_candidato: str
    percentual_atual: float = 0.0       # % do fundo antes da otimização
    percentual_otimizado: float = 0.0   # % sugerido pelo motor
    votos_projetados: int = 0
    justificativa: list[str] = field(default_factory=list)


@dataclass
class ResultadoOtimizacao:
    qp_atual: float = 0.0
    qp_projetado: float = 0.0
    vagas_atuais: int = 0
    vagas_projetadas: int = 0
    alocacoes: list[AlocacaoRecurso] = field(default_factory=list)
    economia_estimada_reais: float = 0.0
    alertas_atendidos: int = 0
    alertas_pendentes: int = 0


@dataclass
class CenarioAcordo:
    """Resultado de simulação: candidato A cobre bairros X, B cobre bairros Y."""
    nome_cenario: str
    territorios_fixados: dict[str, list[str]]   # numero_candidato → [bairros]
    votos_projetados_por_candidato: dict[str, int] = field(default_factory=dict)
    total_votos_chapa: int = 0
    qp_projetado: float = 0.0
    vagas_projetadas: int = 0
    ganho_vs_baseline: int = 0   # votos extras vs. sem acordo


def _projetar_votos_com_recurso(
    candidato: Candidato,
    percentual_fundo: float,
    bairros_ativos: Sequence[BairroAnalisado],
    fator_conversao: float = 0.15,
) -> int:
    """
    Projeta votos totais dado um percentual do fundo eleitoral.

    Modelo simplificado:
      votos = votos_base × (1 + log(1 + 10 × percentual) × fator_conversao × elasticidade_media)

    elasticidade_media: média ponderada da elasticidade dos bairros ativos do candidato.
    """
    bairros_idx = {b.codigo_bairro: b for b in bairros_ativos}
    elasticidades = []
    for t in candidato.territorios:
        ba = bairros_idx.get(t.codigo_bairro)
        if ba:
            elasticidades.append(ba.elasticidade_bairro * t.percentual_do_candidato)

    elast_media = sum(elasticidades) / len(elasticidades) if elasticidades else 0.5

    multiplicador = 1.0 + math.log1p(10 * percentual_fundo) * fator_conversao * elast_media
    return int(candidato.total_votos_historicos * multiplicador)


def _penalidade_conflito(
    numero_candidato: str,
    alertas: Sequence[AlertaConflito],
) -> float:
    """Soma das sobreposições ponderadas onde esse candidato está envolvido."""
    return sum(
        a.sobreposicao_ponderada
        for a in alertas
        if a.candidato_a == numero_candidato or a.candidato_b == numero_candidato
    )


def otimizar_alocacao(
    chapa: Chapa,
    resultado_municipio: ResultadoMunicipio,
    bairros_analisados: Sequence[BairroAnalisado],
    alertas: Sequence[AlertaConflito],
    min_pct_candidato: float = 0.02,
    max_pct_candidato: float = 0.40,
    n_iteracoes: int = 500,
) -> ResultadoOtimizacao:
    """
    Distribui o fundo eleitoral entre candidatos da chapa visando maximizar QP.

    Usa gradiente ascendente com penalidades: a cada iteração, redireciona
    marginal de recurso do candidato com menor utilidade marginal para o maior.
    """
    candidatos = [c for c in chapa.candidatos if c.total_votos_historicos > 0]
    n = len(candidatos)
    if n == 0:
        return ResultadoOtimizacao()

    # Inicializar com distribuição uniforme
    pcts = [1.0 / n] * n

    def utilidade_marginal(idx: int, pct: float) -> float:
        c = candidatos[idx]
        votos = _projetar_votos_com_recurso(c, pct, bairros_analisados)
        penalidade = _penalidade_conflito(c.numero, alertas)
        bonus_vacuo = sum(
            1.0 for ba in bairros_analisados
            if ba.categoria in ("oportunidade", "herança_perdida")
            and c.numero in ba.candidatos_presentes
        ) * 0.05
        return votos * (1.0 - penalidade * 0.5) * (1.0 + bonus_vacuo)

    delta = 0.005   # passo de redistribuição

    for _ in range(n_iteracoes):
        utils = [utilidade_marginal(i, pcts[i]) for i in range(n)]
        idx_pior = min(range(n), key=lambda i: utils[i])
        idx_melhor = max(range(n), key=lambda i: utils[i])

        if idx_pior == idx_melhor:
            break

        transferencia = min(delta, pcts[idx_pior] - min_pct_candidato)
        if transferencia <= 0:
            continue

        novo_melhor = pcts[idx_melhor] + transferencia
        if novo_melhor > max_pct_candidato:
            continue

        pcts[idx_pior] -= transferencia
        pcts[idx_melhor] += transferencia

    # Normalizar para somar 100%
    total = sum(pcts)
    pcts = [p / total for p in pcts]

    # Construir resultado
    alocacoes = []
    total_votos_proj = 0

    for i, c in enumerate(candidatos):
        votos_proj = _projetar_votos_com_recurso(c, pcts[i], bairros_analisados)
        total_votos_proj += votos_proj

        justificativas = []
        pen = _penalidade_conflito(c.numero, alertas)
        if pen > 0.3:
            justificativas.append(f"Penalizado por conflito territorial ({pen:.0%} sobreposição)")
        if pcts[i] > 1.0 / n * 1.2:
            justificativas.append("Candidato prioritário: alta elasticidade e baixo conflito")
        if pcts[i] < 1.0 / n * 0.8:
            justificativas.append("Redução indicada: conflito elevado ou cobertura fragmentada")

        alocacoes.append(AlocacaoRecurso(
            numero_candidato=c.numero,
            nome_candidato=c.nome,
            percentual_atual=1.0 / n,
            percentual_otimizado=pcts[i],
            votos_projetados=votos_proj,
            justificativa=justificativas,
        ))

    qe = resultado_municipio.quociente_eleitoral or 1
    qp_proj = total_votos_proj / qe

    qp_atual = resultado_municipio.quociente_partidario
    vagas_atuais = resultado_municipio.vagas_conquistadas
    vagas_proj = int(qp_proj)

    atendidos = sum(
        1 for a in alertas
        if a.nivel_alerta in ("crítico", "alto")
        and any(
            al.percentual_otimizado < al.percentual_atual
            for al in alocacoes
            if al.numero_candidato in (a.candidato_a, a.candidato_b)
        )
    )

    return ResultadoOtimizacao(
        qp_atual=round(qp_atual, 3),
        qp_projetado=round(qp_proj, 3),
        vagas_atuais=vagas_atuais,
        vagas_projetadas=vagas_proj,
        alocacoes=sorted(alocacoes, key=lambda a: a.percentual_otimizado, reverse=True),
        alertas_atendidos=atendidos,
        alertas_pendentes=len(alertas) - atendidos,
    )


def simular_acordo_territorial(
    chapa: Chapa,
    territorios_fixados: dict[str, list[str]],
    resultado_municipio: ResultadoMunicipio,
    bairros_analisados: Sequence[BairroAnalisado],
    nome_cenario: str = "Cenário Customizado",
) -> CenarioAcordo:
    """
    Simula o que acontece se cada candidato focar exclusivamente nos
    bairros especificados em territorios_fixados.

    Projeção: para bairros fixados, candidato recebe 100% da elasticidade
    disponível (sem disputa interna). Para bairros fora do acordo, o
    candidato recebe 0 reforço.
    """
    bairros_idx = {b.codigo_bairro: b for b in bairros_analisados}
    votos_proj: dict[str, int] = {}
    total_votos = 0

    for c in chapa.candidatos:
        bairros_fixados = set(territorios_fixados.get(c.numero, []))

        votos_base = 0
        for t in c.territorios:
            if t.codigo_bairro in bairros_fixados:
                ba = bairros_idx.get(t.codigo_bairro)
                elast = ba.elasticidade_bairro if ba else 1.0
                # Sem conflito: multiplicador maior
                votos_base += int(t.votos_historicos * (1.0 + 0.25 * elast))
            else:
                # Sem reforço: mantém base mínima (30% dos votos históricos)
                votos_base += int(t.votos_historicos * 0.30)

        votos_proj[c.numero] = votos_base
        total_votos += votos_base

    qe = resultado_municipio.quociente_eleitoral or 1
    qp = total_votos / qe

    # Baseline: sem acordo (cada candidato com 100% dos votos históricos)
    baseline = sum(c.total_votos_historicos for c in chapa.candidatos)

    return CenarioAcordo(
        nome_cenario=nome_cenario,
        territorios_fixados=territorios_fixados,
        votos_projetados_por_candidato=votos_proj,
        total_votos_chapa=total_votos,
        qp_projetado=round(qp, 3),
        vagas_projetadas=int(qp),
        ganho_vs_baseline=total_votos - baseline,
    )
