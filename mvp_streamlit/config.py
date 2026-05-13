"""
config.py — Configurações centrais do MVP Moneyball Eleitoral
"""
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths dos bancos DuckDB
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent

DB_2024 = str(BASE_DIR / "db" / "meu_banco_local.duckdb")
DB_2022 = str(BASE_DIR / "db" / "eleicoes_2022.duckdb")

# Aliases usados no ATTACH — nunca mudar sem ajustar queries/conexao.py
ALIAS_2024 = "db2024"
ALIAS_2022 = "db2022"

# ---------------------------------------------------------------------------
# Mapeamento de cargos por ano
# ---------------------------------------------------------------------------
CARGOS_POR_ANO: dict[int, dict[int, str]] = {
    2024: {
        13: "Vereador",
        11: "Prefeito",
    },
    2022: {
        7: "Dep. Estadual",
        6: "Dep. Federal",
        3: "Governador",
    },
}

# ---------------------------------------------------------------------------
# UFs disponíveis
# ---------------------------------------------------------------------------
# 2024 = eleição municipal — DF não elege vereadores/prefeito pelo TSE padrão
UFS_2024: list[str] = [
    "AC", "AL", "AM", "AP", "BA", "CE", "ES", "GO",
    "MA", "MG", "MS", "MT", "PA", "PB", "PE", "PI",
    "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE",
    "SP", "TO",
]

# 2022 = eleição geral — todas as 27 UFs incluindo DF
UFS_2022: list[str] = UFS_2024 + ["DF"]

UFS_POR_ANO: dict[int, list[str]] = {
    2024: UFS_2024,
    2022: UFS_2022,
}

# ---------------------------------------------------------------------------
# Limites / defaults
# ---------------------------------------------------------------------------
TOP_N_DEFAULT: int = 10
TOP_N_MIN: int = 5
TOP_N_MAX: int = 30

# Votos mínimos no bairro para entrar na análise
MIN_VOTOS_BAIRRO: int = 50

# Bairros inválidos (após UPPER+TRIM)
BAIRROS_INVALIDOS: tuple[str, ...] = (
    "",
    "SEM INFORMAÇÃO",
    "SEM INFORMACAO",
    "NAO INFORMADO",
    "NÃO INFORMADO",
    "S/N",
    "SN",
)

# Status de conflito e suas cores (para column_config do Streamlit)
STATUS_COLORS: dict[str, str] = {
    "CRÍTICO": "#FF4B4B",
    "ALERTA": "#FFA500",
}

# Candidatos no mesmo partido/federação que configuram CRÍTICO (>= 3) ou ALERTA (== 2)
CRITICO_THRESHOLD: int = 3   # >= 3 candidatos → CRÍTICO
ALERTA_THRESHOLD: int = 2    # == 2 candidatos → ALERTA
