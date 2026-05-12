"""
Estrutura de dados espaciais para o sistema de Geopolítica de Precisão Eleitoral.

Hierarquia geográfica:
  Estado → Município → Zona Eleitoral → Seção Eleitoral
                     ↘ Bairro (polígono geográfico que pode conter N seções)

A seção é a menor unidade de apuração do TSE.
O bairro é a menor unidade de planejamento estratégico.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Coordenada:
    latitude: float
    longitude: float

    def to_tuple(self) -> tuple[float, float]:
        return (self.longitude, self.latitude)


@dataclass
class Poligono:
    """Representação simplificada de um polígono geográfico (GeoJSON-like)."""
    coordinates: list[list[float]]  # [[lon, lat], ...]
    tipo: str = "Polygon"

    def centroide(self) -> Coordenada:
        lons = [p[0] for p in self.coordinates]
        lats = [p[1] for p in self.coordinates]
        return Coordenada(
            latitude=sum(lats) / len(lats),
            longitude=sum(lons) / len(lons),
        )


@dataclass
class SecaoEleitoral:
    """
    Menor unidade de apuração eleitoral do TSE.
    Cada seção possui local de votação e eleitores registrados.
    """
    codigo_secao: str          # e.g. "0001"
    codigo_zona: str           # e.g. "001"
    codigo_municipio: str      # IBGE 7 dígitos
    nome_municipio: str
    codigo_bairro: Optional[str] = None
    nome_bairro: Optional[str] = None
    logradouro_local: Optional[str] = None
    coordenada: Optional[Coordenada] = None
    total_eleitores: int = 0

    @property
    def id(self) -> str:
        return f"{self.codigo_municipio}-{self.codigo_zona}-{self.codigo_secao}"


@dataclass
class Bairro:
    """
    Unidade de análise estratégica — agrega múltiplas seções eleitorais.
    """
    codigo_bairro: str
    nome_bairro: str
    codigo_municipio: str
    nome_municipio: str
    poligono: Optional[Poligono] = None
    secoes: list[str] = field(default_factory=list)   # lista de SecaoEleitoral.id
    total_eleitores: int = 0

    # Métricas calculadas pelo motor de análise
    indice_forca_partido: float = 0.0      # % votos legenda / total seção
    indice_vacuo: float = 0.0              # força sem candidato ativo cobrindo
    categoria: str = "indefinido"          # "oportunidade" | "conflito" | "coberto" | "adverso"


@dataclass
class ZonaEleitoral:
    codigo_zona: str
    codigo_municipio: str
    nome_municipio: str
    secoes: list[str] = field(default_factory=list)
    bairros_abrangidos: list[str] = field(default_factory=list)


@dataclass
class Municipio:
    codigo_ibge: str
    nome: str
    uf: str
    poligono: Optional[Poligono] = None
    zonas: list[str] = field(default_factory=list)
    bairros: list[str] = field(default_factory=list)


@dataclass
class Estado:
    uf: str
    nome: str
    municipios: list[str] = field(default_factory=list)
