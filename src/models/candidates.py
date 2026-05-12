"""
Modelos de candidatos: perfil, território de atuação, alocação de recursos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from .electoral import CargoEnum


@dataclass
class TerritorioCandidato:
    """
    Descreve a presença territorial de um candidato: quais bairros ele
    efetivamente cobre com votos históricos e/ou campanha ativa.
    """
    codigo_bairro: str
    nome_bairro: str

    votos_historicos: int = 0          # votos do candidato nesse bairro (ref. passada)
    percentual_no_bairro: float = 0.0  # % dos votos válidos do bairro
    percentual_do_candidato: float = 0.0  # % do total de votos do candidato nesse bairro
    elasticidade: float = 1.0          # sensibilidade de voto a esforço de campanha
    prioridade_alocacao: int = 0       # 1=alta, 2=média, 3=baixa (calculado pelo motor)


@dataclass
class Candidato:
    """Perfil completo de um candidato na chapa."""
    numero: str
    nome: str
    cargo: CargoEnum
    sigla_partido: str
    codigo_municipio: str
    ano_eleicao: int

    # Identidade política
    numero_partido: str = ""
    coligacao: Optional[str] = None

    # Território de influência (calculado pelo motor)
    territorios: list[TerritorioCandidato] = field(default_factory=list)

    # Métricas agregadas (calculadas)
    total_votos_historicos: int = 0
    indice_concentracao: float = 0.0   # Herfindahl do candidato (0=disperso, 1=concentrado)
    cobertura_geografica: float = 0.0  # % de bairros do município onde tem presença

    # Alocação de recursos
    recurso_sugerido: float = 0.0      # em % do fundo total
    recurso_alocado: float = 0.0       # em % do fundo total (decisão do gestor)

    @property
    def bairros_cobertos(self) -> list[str]:
        return [t.codigo_bairro for t in self.territorios if t.votos_historicos > 0]

    @property
    def bairros_primarios(self) -> list[str]:
        """Bairros onde o candidato concentra 80% dos seus votos."""
        total = sum(t.votos_historicos for t in self.territorios)
        if total == 0:
            return []
        ordered = sorted(self.territorios, key=lambda t: t.votos_historicos, reverse=True)
        acum = 0
        primarios = []
        for t in ordered:
            acum += t.votos_historicos
            primarios.append(t.codigo_bairro)
            if acum / total >= 0.80:
                break
        return primarios


@dataclass
class Chapa:
    """
    Conjunto de candidatos de um partido em um pleito estadual/federal.
    É o objeto central de análise de conflito e otimização.
    """
    sigla_partido: str
    numero_partido: str
    codigo_municipio: str
    ano_eleicao: int
    cargo: CargoEnum

    candidatos: list[Candidato] = field(default_factory=list)
    total_vagas_disputa: int = 0
    meta_quociente_partidario: float = 1.0   # mínimo de 1 vaga

    # Budget total do fundo eleitoral para essa chapa
    fundo_total_reais: float = 0.0

    def get_candidato(self, numero: str) -> Optional[Candidato]:
        for c in self.candidatos:
            if c.numero == numero:
                return c
        return None

    @property
    def total_votos_projetados(self) -> int:
        return sum(c.total_votos_historicos for c in self.candidatos)


@dataclass
class AlertaConflito:
    """Resultado do motor de detecção de conflito entre dois candidatos."""
    candidato_a: str          # numero do candidato
    nome_a: str
    candidato_b: str
    nome_b: str

    # Métricas de sobreposição
    sobreposicao_jaccard: float = 0.0   # % de bairros em comum / bairros total
    sobreposicao_ponderada: float = 0.0 # ponderada por votos
    bairros_conflito: list[str] = field(default_factory=list)

    # Candidato mais eficiente em cada bairro de conflito
    favorecido_por_bairro: dict[str, str] = field(default_factory=dict)  # bairro → numero_candidato

    # Perda estimada por canibalização (votos desperdiçados)
    perda_estimada_votos: int = 0
    nivel_alerta: str = "baixo"   # "baixo" | "médio" | "alto" | "crítico"

    @property
    def descricao(self) -> str:
        return (
            f"Conflito {self.nivel_alerta.upper()}: {self.nome_a} × {self.nome_b} — "
            f"sobreposição de {self.sobreposicao_ponderada:.1%} em "
            f"{len(self.bairros_conflito)} bairro(s), "
            f"~{self.perda_estimada_votos} votos em risco."
        )
