"""
Modelos de dados eleitorais: votos por seção, legenda, resultado histórico.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CargoEnum(str, Enum):
    PREFEITO = "prefeito"
    VEREADOR = "vereador"
    DEPUTADO_ESTADUAL = "deputado_estadual"
    DEPUTADO_FEDERAL = "deputado_federal"
    SENADOR = "senador"
    GOVERNADOR = "governador"
    PRESIDENTE = "presidente"


class TipoEleicaoEnum(str, Enum):
    MUNICIPAL = "municipal"
    ESTADUAL_FEDERAL = "estadual_federal"


@dataclass
class ResultadoSecao:
    """
    Registro atômico: votos de um candidato (ou legenda) em uma seção eleitoral.
    Corresponde ao arquivo de resultados do TSE.
    """
    ano_eleicao: int
    turno: int
    tipo_eleicao: TipoEleicaoEnum
    cargo: CargoEnum

    # Localização
    codigo_municipio: str
    codigo_zona: str
    codigo_secao: str
    codigo_bairro: Optional[str] = None

    # Candidato / Partido
    numero_candidato: Optional[str] = None   # None = voto de legenda
    nome_candidato: Optional[str] = None
    numero_partido: str = ""
    sigla_partido: str = ""

    # Resultado
    votos: int = 0
    votos_legenda: int = 0    # votos só na legenda sem candidato
    votos_validos_secao: int = 0
    total_comparecimento: int = 0


@dataclass
class ResultadoBairro:
    """
    Agregação de ResultadoSecao ao nível de bairro — unidade de estratégia.
    """
    ano_eleicao: int
    cargo: CargoEnum
    codigo_bairro: str
    nome_bairro: str
    codigo_municipio: str
    sigla_partido: str

    # Por candidato (numero_candidato → votos)
    votos_por_candidato: dict[str, int] = field(default_factory=dict)
    votos_legenda: int = 0
    votos_validos_bairro: int = 0
    total_eleitores_bairro: int = 0

    @property
    def votos_partido_total(self) -> int:
        return sum(self.votos_por_candidato.values()) + self.votos_legenda

    @property
    def percentual_partido(self) -> float:
        if self.votos_validos_bairro == 0:
            return 0.0
        return self.votos_partido_total / self.votos_validos_bairro * 100


@dataclass
class ResultadoMunicipio:
    """Resultado agregado por município, usado para calcular o quociente."""
    ano_eleicao: int
    cargo: CargoEnum
    codigo_municipio: str
    nome_municipio: str
    sigla_partido: str

    total_votos_partido: int = 0
    total_votos_validos: int = 0
    total_vagas: int = 0            # vagas disponíveis (câmara)

    @property
    def quociente_eleitoral(self) -> float:
        """QE = total votos válidos / vagas da câmara."""
        if self.total_vagas == 0:
            return 0.0
        return self.total_votos_validos / self.total_vagas

    @property
    def quociente_partidario(self) -> float:
        """QP = votos partido / QE (número de vagas conquistadas)."""
        qe = self.quociente_eleitoral
        if qe == 0:
            return 0.0
        return self.total_votos_partido / qe

    @property
    def vagas_conquistadas(self) -> int:
        return int(self.quociente_partidario)


@dataclass
class HerancaEleitoral:
    """
    Mede quanto da votação de prefeito/vereador municipal se converte em
    base territorial para a chapa estadual/federal.
    """
    codigo_bairro: str
    nome_bairro: str
    codigo_municipio: str

    # Eleição municipal (referência)
    votos_prefeito_bairro: int = 0
    votos_vereadores_bairro: int = 0
    total_validos_municipal: int = 0

    # Eleição estadual/federal (alvo)
    votos_legenda_estadual: int = 0
    total_validos_estadual: int = 0

    @property
    def forca_heranca(self) -> float:
        """
        Correlação entre força municipal e performance estadual.
        Valores próximos de 1.0 indicam alta conversão de herança.
        """
        if self.total_validos_municipal == 0 or self.total_validos_estadual == 0:
            return 0.0
        base_municipal = (
            self.votos_prefeito_bairro + self.votos_vereadores_bairro
        ) / self.total_validos_municipal
        base_estadual = self.votos_legenda_estadual / self.total_validos_estadual
        if base_municipal == 0:
            return 0.0
        return min(base_estadual / base_municipal, 2.0)   # cap em 2x
