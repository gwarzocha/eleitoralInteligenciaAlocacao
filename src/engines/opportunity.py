"""
Motor de Mapeamento de Oportunidades Territoriais.

Identifica:
1. "Vácuos de Representação" — bairros onde o partido tem força de legenda
   mas nenhum candidato da chapa atual tem presença ativa.
2. "Herança Não Convertida" — bairros com alta votação municipal do partido
   mas baixa conversão estadual/federal.
3. Elasticidade de voto por bairro — potencial de crescimento dado
   investimento de campanha.
4. Categorização final de cada bairro: OPORTUNIDADE / CONFLITO / COBERTO / ADVERSO.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..models.candidates import Chapa
from ..models.electoral import HerancaEleitoral, ResultadoBairro
from ..models.spatial import Bairro


@dataclass
class BairroAnalisado:
    codigo_bairro: str
    nome_bairro: str
    codigo_municipio: str

    # Força do partido
    forca_legenda: float = 0.0         # % votos legenda / votos válidos
    forca_municipal: float = 0.0       # % votos municipais do partido

    # Cobertura por candidatos da chapa
    candidatos_presentes: list[str] = field(default_factory=list)
    n_candidatos_conflito: int = 0     # quantos candidatos estão em conflito aqui

    # Índices calculados
    indice_vacuo: float = 0.0          # 0=coberto, 1=vácuo total
    indice_heranca: float = 0.0        # conversão municipal→estadual
    elasticidade_bairro: float = 1.0   # potencial de crescimento
    potencial_votos_extras: int = 0    # votos recuperáveis com reforço

    # Classificação final
    categoria: str = "indefinido"
    # "oportunidade"  → força sem cobertura adequada
    # "conflito"       → disputado por ≥2 candidatos internos
    # "coberto"        → bem coberto, sem conflito
    # "adverso"        → partido fraco, não prioritário
    # "herança_perdida" → base municipal não convertida

    prioridade: int = 99               # 1=máxima, ordenar ASC


def _calcular_elasticidade_bairro(
    forca_atual: float,
    n_candidatos: int,
    indice_vacuo: float,
) -> float:
    """
    Elasticidade do bairro ao investimento de campanha.

    Bairros com força moderada (nem dominados, nem hostis) e sem cobertura
    respondem melhor ao investimento marginal.
    Curva em sino: pico em forca_atual ~ 25-35%.
    """
    import math

    # Forca ótima de crescimento: ~30%
    otimo = 0.30
    distancia = abs(forca_atual - otimo)

    # Quanto mais próximo do ótimo, mais elástico
    base_elasticidade = math.exp(-5 * distancia ** 2)

    # Bônus por vacuo: sem candidato → maior potencial de captura
    bonus_vacuo = 1.0 + indice_vacuo

    # Penalidade por excesso de candidatos (canibalização reduz elasticidade)
    penalidade_sobreposicao = 1.0 / max(n_candidatos, 1)

    return base_elasticidade * bonus_vacuo * penalidade_sobreposicao


def _estimar_potencial(
    forca_legenda: float,
    total_eleitores: int,
    indice_vacuo: float,
    elasticidade: float,
) -> int:
    """
    Estima quantos votos adicionais são recuperáveis com presença ativa.
    Proxy: eleitores × forca_legenda × vacuo × elasticidade × fator_campanha.
    """
    fator_campanha = 0.20   # 20% de conversão de eleitorado potencial
    return int(total_eleitores * forca_legenda * indice_vacuo * elasticidade * fator_campanha)


def _categorizar(
    forca_legenda: float,
    n_candidatos: int,
    n_conflito: int,
    indice_vacuo: float,
    indice_heranca: float,
    limiar_forca: float = 0.10,
    limiar_conflito: int = 2,
) -> tuple[str, int]:
    """
    Retorna (categoria, prioridade).
    """
    if n_conflito >= limiar_conflito:
        return "conflito", 1   # Resolver primeiro — drena recursos

    # Vácuo: partido tem força mas nenhum candidato cobre o bairro
    is_vacuo = n_candidatos == 0 and forca_legenda >= limiar_forca
    if is_vacuo or (forca_legenda >= limiar_forca and indice_vacuo > 0.20):
        if indice_heranca < 0.4:
            return "herança_perdida", 2   # Alta base municipal, baixa conversão
        return "oportunidade", 2

    if forca_legenda >= limiar_forca and n_candidatos >= 1:
        return "coberto", 4

    if forca_legenda < limiar_forca * 0.5:
        return "adverso", 5

    return "indefinido", 3


def analisar_bairros(
    bairros: Sequence[Bairro],
    resultados_bairro: Sequence[ResultadoBairro],
    chapa: Chapa,
    alertas_conflito_bairros: dict[str, int],   # bairro_cod → nº pares em conflito
    herancas: Sequence[HerancaEleitoral] | None = None,
    limiar_forca_partido: float = 0.10,
) -> list[BairroAnalisado]:
    """
    Analisa cada bairro e produz a lista de BairroAnalisado classificados.

    alertas_conflito_bairros: mapa de quantos pares de candidatos estão
    em conflito em cada bairro (vem do motor de conflito).
    """
    # Índice de força de legenda por bairro
    forca_legenda_idx: dict[str, float] = {}
    for rb in resultados_bairro:
        if rb.sigla_partido == chapa.sigla_partido:
            forca_legenda_idx[rb.codigo_bairro] = rb.percentual_partido / 100.0

    # Índice de herança
    heranca_idx: dict[str, float] = {}
    if herancas:
        for h in herancas:
            heranca_idx[h.codigo_bairro] = h.forca_heranca

    # Candidatos presentes por bairro
    cobertura_idx: dict[str, list[str]] = {}
    for c in chapa.candidatos:
        for bairro in c.bairros_cobertos:
            cobertura_idx.setdefault(bairro, []).append(c.numero)

    resultados: list[BairroAnalisado] = []

    for bairro in bairros:
        b_cod = bairro.codigo_bairro
        forca = forca_legenda_idx.get(b_cod, 0.0)
        candidatos = cobertura_idx.get(b_cod, [])
        n_cands = len(candidatos)
        n_conflito = alertas_conflito_bairros.get(b_cod, 0)

        # Vácuo: força do partido sem cobertura de candidato
        indice_vacuo = max(0.0, forca - (n_cands * 0.15)) if n_cands == 0 else 0.0
        if n_cands == 0 and forca > 0:
            indice_vacuo = forca   # 100% vácuo se há força mas nenhum candidato

        indice_heranca = heranca_idx.get(b_cod, 0.5)
        elasticidade = _calcular_elasticidade_bairro(forca, n_cands, indice_vacuo)
        potencial = _estimar_potencial(
            forca, bairro.total_eleitores, indice_vacuo, elasticidade
        )

        categoria, prioridade = _categorizar(
            forca, n_cands, n_conflito, indice_vacuo, indice_heranca, limiar_forca_partido
        )

        resultados.append(BairroAnalisado(
            codigo_bairro=b_cod,
            nome_bairro=bairro.nome_bairro,
            codigo_municipio=bairro.codigo_municipio,
            forca_legenda=forca,
            forca_municipal=forca * indice_heranca,
            candidatos_presentes=candidatos,
            n_candidatos_conflito=n_conflito,
            indice_vacuo=indice_vacuo,
            indice_heranca=indice_heranca,
            elasticidade_bairro=elasticidade,
            potencial_votos_extras=potencial,
            categoria=categoria,
            prioridade=prioridade,
        ))

    return sorted(resultados, key=lambda b: (b.prioridade, -b.potencial_votos_extras))


def mapa_oportunidade_conflito(
    bairros_analisados: Sequence[BairroAnalisado],
) -> dict:
    """Agrega o mapa para consumo pelo dashboard."""
    from collections import Counter
    contagem = Counter(b.categoria for b in bairros_analisados)

    return {
        "total_bairros": len(bairros_analisados),
        "por_categoria": dict(contagem),
        "bairros": [
            {
                "codigo": b.codigo_bairro,
                "nome": b.nome_bairro,
                "categoria": b.categoria,
                "prioridade": b.prioridade,
                "forca_legenda_pct": round(b.forca_legenda * 100, 2),
                "candidatos_presentes": b.candidatos_presentes,
                "n_conflito": b.n_candidatos_conflito,
                "potencial_votos_extras": b.potencial_votos_extras,
                "elasticidade": round(b.elasticidade_bairro, 3),
                "indice_vacuo": round(b.indice_vacuo, 3),
                "indice_heranca": round(b.indice_heranca, 3),
            }
            for b in bairros_analisados
        ],
        "top_oportunidades": [
            b for b in bairros_analisados
            if b.categoria in ("oportunidade", "herança_perdida")
        ][:10],
        "zonas_guerra": [
            b for b in bairros_analisados
            if b.categoria == "conflito"
        ][:10],
    }
