"""
Motor de Detecção de Conflito e Canibalização.

Lógica central:
1. Para cada par de candidatos (A, B) da mesma chapa, calcular:
   - Sobreposição de Jaccard sobre bairros onde ambos têm presença
   - Sobreposição ponderada (por votos históricos)
   - Bairros críticos: onde os dois candidatos competem pelo mesmo eleitorado

2. Em cada bairro de conflito, identificar quem tem maior "elasticidade"
   (melhor custo-benefício por recurso investido naquele bairro).

3. Emitir AlertaConflito com nível (baixo/médio/alto/crítico) e
   indicação de qual candidato deve ser favorecido por bairro.
"""
from __future__ import annotations

import itertools
import math
from typing import Sequence

from ..models.candidates import AlertaConflito, Candidato, Chapa, TerritorioCandidato


# Limiares de sobreposição ponderada para classificação do nível
_LIMIARES = {
    "crítico": 0.60,
    "alto": 0.40,
    "médio": 0.20,
    "baixo": 0.0,
}


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    intersecao = set_a & set_b
    uniao = set_a | set_b
    if not uniao:
        return 0.0
    return len(intersecao) / len(uniao)


def _sobreposicao_ponderada(
    territorios_a: list[TerritorioCandidato],
    territorios_b: list[TerritorioCandidato],
    bairros_conflito: set[str],
) -> float:
    """
    Peso = votos combinados nos bairros conflitantes / votos totais combinados.
    """
    idx_a = {t.codigo_bairro: t.votos_historicos for t in territorios_a}
    idx_b = {t.codigo_bairro: t.votos_historicos for t in territorios_b}

    votos_conflito = sum(
        idx_a.get(b, 0) + idx_b.get(b, 0) for b in bairros_conflito
    )
    votos_totais = sum(idx_a.values()) + sum(idx_b.values())

    if votos_totais == 0:
        return 0.0
    return votos_conflito / votos_totais


def _calcular_elasticidade(
    candidato: Candidato, bairro_cod: str
) -> float:
    """
    Elasticidade estimada de voto de um candidato em um bairro.

    Proxy: se o candidato tem alta participação no total do bairro mas
    baixa concentração (índice HHI baixo), ele tem "spread" — é eficiente
    ao investir nesse bairro. Penaliza candidatos muito concentrados
    (canibalizariam o próprio eleitorado).

    Retorna valor >= 0. Maior = mais eficiente para receber aporte no bairro.
    """
    territorio = next(
        (t for t in candidato.territorios if t.codigo_bairro == bairro_cod), None
    )
    if territorio is None:
        return 0.0

    # Penalidade por concentração: candidatos com HHI alto têm menos espaço de crescimento
    penalidade_concentracao = 1.0 - min(candidato.indice_concentracao, 0.9)

    # Bonus por penetração no bairro já existente (base ativa)
    bonus_penetracao = math.log1p(territorio.percentual_no_bairro * 100) / math.log1p(100)

    return penalidade_concentracao * (1.0 + bonus_penetracao)


def _nivel_alerta(sobreposicao: float) -> str:
    for nivel, limiar in _LIMIARES.items():
        if sobreposicao >= limiar:
            return nivel
    return "baixo"


def _estimar_perda_votos(
    candidato_a: Candidato,
    candidato_b: Candidato,
    bairros_conflito: set[str],
) -> int:
    """
    Estimativa conservadora de votos desperdiçados por canibalização.

    Para cada bairro de conflito: o candidato menos eficiente perde uma
    fração dos seus votos históricos para o canibalismo interno.
    Usa fator de canibalização de ~30% como baseline empírico.
    """
    idx_a = {t.codigo_bairro: t.votos_historicos for t in candidato_a.territorios}
    idx_b = {t.codigo_bairro: t.votos_historicos for t in candidato_b.territorios}

    perda = 0
    fator_canibalizacao = 0.30

    for bairro in bairros_conflito:
        votos_a = idx_a.get(bairro, 0)
        votos_b = idx_b.get(bairro, 0)
        # O menor dos dois "perde" pois seu eleitorado é disputado
        perda += int(min(votos_a, votos_b) * fator_canibalizacao)

    return perda


def detectar_conflitos(
    chapa: Chapa,
    limiar_sobreposicao: float = 0.15,
    min_votos_presenca: int = 100,
) -> list[AlertaConflito]:
    """
    Ponto de entrada principal do motor de conflito.

    Para cada par de candidatos na chapa, avalia sobreposição territorial
    e emite AlertaConflito quando acima do limiar.

    limiar_sobreposicao: sobreposição ponderada mínima para gerar alerta
    min_votos_presenca: mínimo de votos históricos para considerar presença real
    """
    alertas: list[AlertaConflito] = []

    candidatos_ativos = [
        c for c in chapa.candidatos if c.total_votos_historicos >= min_votos_presenca
    ]

    for cand_a, cand_b in itertools.combinations(candidatos_ativos, 2):
        bairros_a = {
            t.codigo_bairro
            for t in cand_a.territorios
            if t.votos_historicos >= min_votos_presenca
        }
        bairros_b = {
            t.codigo_bairro
            for t in cand_b.territorios
            if t.votos_historicos >= min_votos_presenca
        }

        bairros_conflito = bairros_a & bairros_b
        if not bairros_conflito:
            continue

        jaccard = _jaccard(bairros_a, bairros_b)
        ponderada = _sobreposicao_ponderada(
            cand_a.territorios, cand_b.territorios, bairros_conflito
        )

        if ponderada < limiar_sobreposicao:
            continue

        # Para cada bairro de conflito, determinar quem deve receber aporte
        favorecido: dict[str, str] = {}
        for bairro in bairros_conflito:
            elast_a = _calcular_elasticidade(cand_a, bairro)
            elast_b = _calcular_elasticidade(cand_b, bairro)
            favorecido[bairro] = cand_a.numero if elast_a >= elast_b else cand_b.numero

        perda = _estimar_perda_votos(cand_a, cand_b, bairros_conflito)

        alerta = AlertaConflito(
            candidato_a=cand_a.numero,
            nome_a=cand_a.nome,
            candidato_b=cand_b.numero,
            nome_b=cand_b.nome,
            sobreposicao_jaccard=jaccard,
            sobreposicao_ponderada=ponderada,
            bairros_conflito=sorted(bairros_conflito),
            favorecido_por_bairro=favorecido,
            perda_estimada_votos=perda,
            nivel_alerta=_nivel_alerta(ponderada),
        )
        alertas.append(alerta)

    # Ordenar por severidade
    ordem = {"crítico": 0, "alto": 1, "médio": 2, "baixo": 3}
    return sorted(alertas, key=lambda a: ordem.get(a.nivel_alerta, 9))


def resumo_conflitos(alertas: Sequence[AlertaConflito]) -> dict:
    """Agrega métricas de conflito para o dashboard."""
    if not alertas:
        return {
            "total_pares_conflito": 0,
            "criticos": 0,
            "altos": 0,
            "medios": 0,
            "baixos": 0,
            "total_votos_risco": 0,
            "bairros_conflito_unicos": 0,
        }

    niveis = {"crítico": 0, "alto": 0, "médio": 0, "baixo": 0}
    for a in alertas:
        niveis[a.nivel_alerta] = niveis.get(a.nivel_alerta, 0) + 1

    todos_bairros = set()
    for a in alertas:
        todos_bairros.update(a.bairros_conflito)

    return {
        "total_pares_conflito": len(alertas),
        "criticos": niveis["crítico"],
        "altos": niveis["alto"],
        "medios": niveis["médio"],
        "baixos": niveis["baixo"],
        "total_votos_risco": sum(a.perda_estimada_votos for a in alertas),
        "bairros_conflito_unicos": len(todos_bairros),
    }
