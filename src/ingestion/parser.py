"""
Parser de arquivos brutos do TSE.

Formato de referência: votacao_secao_<ano>_<UF>.csv
Colunas-padrão TSE (colunas relevantes extraídas):
  - NR_TURNO, NR_ZONA, NR_SECAO, CD_MUNICIPIO, NM_MUNICIPIO
  - NR_CANDIDATO, NM_CANDIDATO, NR_PARTIDO, SG_PARTIDO
  - QT_VOTOS_NOMINAIS, QT_VOTOS_LEGENDA, QT_COMPARECIMENTO
  - DS_CARGO_PERGUNTA (cargo)
  - NM_BAIRRO (quando disponível — arquivo de locais de votação)
"""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Iterator

from ..models.electoral import CargoEnum, ResultadoSecao, TipoEleicaoEnum

logger = logging.getLogger(__name__)

# Mapeamento dos rótulos de cargo TSE → enum interno
_CARGO_MAP: dict[str, CargoEnum] = {
    "PREFEITO": CargoEnum.PREFEITO,
    "VEREADOR": CargoEnum.VEREADOR,
    "DEPUTADO ESTADUAL": CargoEnum.DEPUTADO_ESTADUAL,
    "DEPUTADO FEDERAL": CargoEnum.DEPUTADO_FEDERAL,
    "SENADOR": CargoEnum.SENADOR,
    "GOVERNADOR": CargoEnum.GOVERNADOR,
    "PRESIDENTE": CargoEnum.PRESIDENTE,
}

_CARGO_TIPO: dict[CargoEnum, TipoEleicaoEnum] = {
    CargoEnum.PREFEITO: TipoEleicaoEnum.MUNICIPAL,
    CargoEnum.VEREADOR: TipoEleicaoEnum.MUNICIPAL,
    CargoEnum.DEPUTADO_ESTADUAL: TipoEleicaoEnum.ESTADUAL_FEDERAL,
    CargoEnum.DEPUTADO_FEDERAL: TipoEleicaoEnum.ESTADUAL_FEDERAL,
    CargoEnum.SENADOR: TipoEleicaoEnum.ESTADUAL_FEDERAL,
    CargoEnum.GOVERNADOR: TipoEleicaoEnum.ESTADUAL_FEDERAL,
    CargoEnum.PRESIDENTE: TipoEleicaoEnum.ESTADUAL_FEDERAL,
}


def _parse_int(val: str) -> int:
    try:
        return int(str(val).strip().replace(".", ""))
    except (ValueError, AttributeError):
        return 0


def _parse_float(val: str) -> float:
    try:
        return float(str(val).strip().replace(",", "."))
    except (ValueError, AttributeError):
        return 0.0


def _map_cargo(raw: str) -> CargoEnum | None:
    normalized = raw.strip().upper()
    for key, value in _CARGO_MAP.items():
        if key in normalized:
            return value
    return None


def parse_csv_tse(
    source: str | Path | io.StringIO,
    ano_eleicao: int,
    encoding: str = "latin-1",
    delimiter: str = ";",
    cargo_filtro: CargoEnum | None = None,
    partido_filtro: str | None = None,
) -> Iterator[ResultadoSecao]:
    """
    Lê um CSV no formato TSE e emite ResultadoSecao para cada linha válida.

    Aceita arquivo em disco (Path/str) ou objeto StringIO (útil em testes e API).
    """
    if isinstance(source, (str, Path)):
        fh = open(source, encoding=encoding, newline="")
        should_close = True
    else:
        fh = source
        should_close = False

    try:
        reader = csv.DictReader(fh, delimiter=delimiter)
        skipped = 0
        yielded = 0

        for row in reader:
            cargo_raw = row.get("DS_CARGO_PERGUNTA") or row.get("DS_CARGO") or ""
            cargo = _map_cargo(cargo_raw)
            if cargo is None:
                skipped += 1
                continue

            if cargo_filtro and cargo != cargo_filtro:
                continue

            sigla = (row.get("SG_PARTIDO") or "").strip()
            if partido_filtro and sigla.upper() != partido_filtro.upper():
                continue

            nr_candidato = (row.get("NR_CANDIDATO") or "").strip()
            # Voto de legenda tem número do candidato como "95" ou "#NULO#" no TSE
            is_legenda = nr_candidato in ("#NULO#", "95", "96", "97", "98", "")

            votos_nom = _parse_int(row.get("QT_VOTOS_NOMINAIS") or "0")
            votos_leg = _parse_int(row.get("QT_VOTOS_LEGENDA") or "0")

            resultado = ResultadoSecao(
                ano_eleicao=ano_eleicao,
                turno=_parse_int(row.get("NR_TURNO") or "1"),
                tipo_eleicao=_CARGO_TIPO[cargo],
                cargo=cargo,
                codigo_municipio=(row.get("CD_MUNICIPIO") or "").strip(),
                codigo_zona=(row.get("NR_ZONA") or "").strip().zfill(3),
                codigo_secao=(row.get("NR_SECAO") or "").strip().zfill(4),
                codigo_bairro=(row.get("CD_BAIRRO") or None),
                numero_candidato=None if is_legenda else nr_candidato,
                nome_candidato=(row.get("NM_CANDIDATO") or "").strip() or None,
                numero_partido=(row.get("NR_PARTIDO") or "").strip(),
                sigla_partido=sigla,
                votos=0 if is_legenda else votos_nom,
                votos_legenda=votos_leg if is_legenda else 0,
                votos_validos_secao=_parse_int(row.get("QT_VOTOS_VALIDOS") or "0"),
                total_comparecimento=_parse_int(row.get("QT_COMPARECIMENTO") or "0"),
            )

            yielded += 1
            yield resultado

        logger.info("TSE parse concluído: %d registros emitidos, %d ignorados.", yielded, skipped)

    finally:
        if should_close:
            fh.close()
