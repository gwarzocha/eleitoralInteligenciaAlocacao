"""Schemas Pydantic para request/response da API."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ── Ingestão ──────────────────────────────────────────────────────────────────

class IngestaoRequest(BaseModel):
    ano_eleicao: int
    sigla_partido: str
    codigo_municipio: str
    cargo: str   # "deputado_estadual" | "deputado_federal" | ...


# ── Candidatos ────────────────────────────────────────────────────────────────

class CandidatoInput(BaseModel):
    numero: str
    nome: str
    cargo: str
    sigla_partido: str
    codigo_municipio: str
    ano_eleicao: int
    total_votos_historicos: int = 0


class TerritorioCandidatoInput(BaseModel):
    numero_candidato: str
    codigo_bairro: str
    votos_historicos: int


class ChapaInput(BaseModel):
    sigla_partido: str
    numero_partido: str
    codigo_municipio: str
    ano_eleicao: int
    cargo: str
    candidatos: list[CandidatoInput]
    total_vagas_disputa: int = 9
    fundo_total_reais: float = 1_000_000.0
    meta_quociente_partidario: float = 1.0
    territorios: list[TerritorioCandidatoInput] = Field(default_factory=list)


# ── Conflito ──────────────────────────────────────────────────────────────────

class AlertaConflitoPydantic(BaseModel):
    candidato_a: str
    nome_a: str
    candidato_b: str
    nome_b: str
    sobreposicao_jaccard: float
    sobreposicao_ponderada: float
    bairros_conflito: list[str]
    favorecido_por_bairro: dict[str, str]
    perda_estimada_votos: int
    nivel_alerta: str
    descricao: str


class ConflitosResponse(BaseModel):
    resumo: dict
    alertas: list[AlertaConflitoPydantic]


# ── Oportunidade ──────────────────────────────────────────────────────────────

class BairroAnalisadoPydantic(BaseModel):
    codigo: str
    nome: str
    categoria: str
    prioridade: int
    forca_legenda_pct: float
    candidatos_presentes: list[str]
    n_conflito: int
    potencial_votos_extras: int
    elasticidade: float
    indice_vacuo: float
    indice_heranca: float


class MapaOportunidadeResponse(BaseModel):
    total_bairros: int
    por_categoria: dict[str, int]
    bairros: list[BairroAnalisadoPydantic]
    top_oportunidades: list[BairroAnalisadoPydantic]
    zonas_guerra: list[BairroAnalisadoPydantic]


# ── Otimização ────────────────────────────────────────────────────────────────

class AlocacaoRecursoPydantic(BaseModel):
    numero_candidato: str
    nome_candidato: str
    percentual_atual: float
    percentual_otimizado: float
    votos_projetados: int
    justificativa: list[str]


class OtimizacaoResponse(BaseModel):
    qp_atual: float
    qp_projetado: float
    vagas_atuais: int
    vagas_projetadas: int
    alocacoes: list[AlocacaoRecursoPydantic]
    alertas_atendidos: int
    alertas_pendentes: int


# ── Simulador de Acordo ───────────────────────────────────────────────────────

class SimulacaoAcordoRequest(BaseModel):
    chapa: ChapaInput
    territorios_fixados: dict[str, list[str]]   # numero_candidato → [bairros]
    nome_cenario: str = "Cenário Simulado"
    total_votos_validos: int = 100000
    total_vagas: int = 9


class SimulacaoAcordoResponse(BaseModel):
    nome_cenario: str
    territorios_fixados: dict[str, list[str]]
    votos_projetados_por_candidato: dict[str, int]
    total_votos_chapa: int
    qp_projetado: float
    vagas_projetadas: int
    ganho_vs_baseline: int


# ── Análise Completa ──────────────────────────────────────────────────────────

class AnaliseCompletaRequest(BaseModel):
    chapa: ChapaInput
    bairros_info: list[dict]   # {codigo, nome, total_eleitores}
    total_votos_validos: int = 100000
    total_vagas: int = 9
    limiar_sobreposicao: float = 0.15


class AnaliseCompletaResponse(BaseModel):
    conflitos: ConflitosResponse
    mapa: MapaOportunidadeResponse
    otimizacao: OtimizacaoResponse
