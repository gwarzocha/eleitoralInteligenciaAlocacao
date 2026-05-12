"""
Gerador de dados sintéticos que simulam uma eleição estadual/federal
num município fictício de médio porte (~300k eleitores, 30 bairros).

Produz:
  - bairros.json       : 30 bairros com coordenadas aproximadas
  - chapa_demo.json    : chapa com 8 candidatos a deputado estadual
  - analise_demo.json  : payload completo para POST /analise/completa
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

random.seed(42)

ROOT = Path(__file__).parent

# ── Bairros ───────────────────────────────────────────────────────────────────

BAIRROS = [
    {"codigo": f"B{i:02d}", "nome": nome, "total_eleitores": eleitores, "lat": lat, "lon": lon}
    for i, (nome, eleitores, lat, lon) in enumerate([
        ("Centro",              18_000, -23.5505, -46.6333),
        ("Bela Vista",          12_000, -23.5600, -46.6400),
        ("Jardim Paulista",     14_500, -23.5650, -46.6600),
        ("Vila Mariana",        16_000, -23.5880, -46.6320),
        ("Moema",               11_000, -23.6050, -46.6620),
        ("Itaim Bibi",           9_000, -23.5878, -46.6780),
        ("Pinheiros",           13_000, -23.5630, -46.6960),
        ("Lapa",                10_500, -23.5220, -46.7050),
        ("Santana",              8_000, -23.4960, -46.6240),
        ("Tatuapé",             11_000, -23.5410, -46.5790),
        ("Penha",                9_500, -23.5270, -46.5280),
        ("São Miguel",           7_800, -23.4940, -46.4430),
        ("Itaquera",            12_000, -23.5393, -46.4540),
        ("Cidade Tiradentes",   15_000, -23.5900, -46.3930),
        ("Sapopemba",           13_500, -23.5790, -46.4660),
        ("Santo André Norte",   10_000, -23.6534, -46.5362),
        ("Santo André Sul",      8_500, -23.6800, -46.5400),
        ("São Bernardo Centro",  9_200, -23.6938, -46.5650),
        ("São Caetano",          7_600, -23.6224, -46.5500),
        ("Diadema",             11_800, -23.6860, -46.6210),
        ("Mauá",                 9_000, -23.6678, -46.4613),
        ("Ribeirão Pires",       6_500, -23.7120, -46.4100),
        ("Guarulhos Centro",    14_000, -23.4629, -46.5329),
        ("Guarulhos Norte",     10_000, -23.4400, -46.5100),
        ("Cumbica",              8_000, -23.4288, -46.4680),
        ("Osasco Centro",       13_000, -23.5325, -46.7919),
        ("Osasco Norte",         9_500, -23.5100, -46.7800),
        ("Carapicuíba",         11_000, -23.5213, -46.8355),
        ("Barueri",             10_500, -23.5055, -46.8768),
        ("Cotia",                7_000, -23.6027, -46.9193),
    ], 1)
]

SIGLA_PARTIDO = "PXL"
CODIGO_MUNICIPIO = "355030"  # São Paulo fictício

# ── Candidatos ────────────────────────────────────────────────────────────────

CANDIDATOS_BASE = [
    {"numero": "1301", "nome": "Ana Carvalho",     "base_bairros": ["B01","B02","B03","B04","B05"]},
    {"numero": "1302", "nome": "Bruno Fonseca",    "base_bairros": ["B03","B04","B05","B06","B07"]},
    {"numero": "1303", "nome": "Carla Mendes",     "base_bairros": ["B08","B09","B10","B11"]},
    {"numero": "1304", "nome": "Daniel Rocha",     "base_bairros": ["B12","B13","B14","B15"]},
    {"numero": "1305", "nome": "Eduarda Lima",     "base_bairros": ["B16","B17","B18","B19"]},
    {"numero": "1306", "nome": "Felipe Souza",     "base_bairros": ["B01","B02","B20","B21"]},  # conflito com Ana
    {"numero": "1307", "nome": "Gabriela Nunes",   "base_bairros": ["B22","B23","B24","B25"]},
    {"numero": "1308", "nome": "Henrique Costa",   "base_bairros": ["B26","B27","B28","B29"]},
]

# Bairros "órfãos" (partido forte, sem candidato): B30 (Cotia)
# O partido tem ~22% de legenda em Cotia mas nenhum candidato cobre

def _votos_para_bairro(base: list[str], bairro_cod: str, total_base: int) -> int:
    """
    Distribui votos entre bairros com decaimento exponencial para a base
    e derramamento limitado a bairros imediatamente adjacentes (±1 índice).
    Bairros distantes recebem 0, evitando sobreposição espúria.
    """
    if bairro_cod in base:
        idx = base.index(bairro_cod)
        peso = math.exp(-0.4 * idx)
        return int(total_base * peso / sum(math.exp(-0.4 * i) for i in range(len(base))))

    # Derramamento apenas para bairros vizinhos imediatos na lista de bairros
    # (simula geograficamente próximos), não para todos
    todos_codigos = [f"B{i:02d}" for i in range(1, 31)]
    try:
        idx_bairro = todos_codigos.index(bairro_cod)
    except ValueError:
        return 0

    # Verificar se algum bairro da base é adjacente (distância ≤ 1 no índice)
    adjacente = any(
        abs(todos_codigos.index(b) - idx_bairro) <= 1
        for b in base
        if b in todos_codigos
    )
    if adjacente:
        return random.randint(80, 200)   # derramamento adjacente real
    return 0   # sem presença em bairros distantes


def gerar_territorios(candidatos: list[dict], bairros: list[dict]) -> list[dict]:
    territorios = []
    for cand in candidatos:
        total_votos = random.randint(8_000, 25_000)
        base = cand["base_bairros"]
        for b in bairros:
            v = _votos_para_bairro(base, b["codigo"], total_votos)
            if v > 15:
                territorios.append({
                    "numero_candidato": cand["numero"],
                    "codigo_bairro": b["codigo"],
                    "votos_historicos": v,
                })
    return territorios


def gerar_chapa(territorios: list[dict]) -> dict:
    # Total de votos por candidato (soma dos territórios)
    votos_por_cand: dict[str, int] = {}
    for t in territorios:
        n = t["numero_candidato"]
        votos_por_cand[n] = votos_por_cand.get(n, 0) + t["votos_historicos"]

    candidatos = [
        {
            "numero": c["numero"],
            "nome": c["nome"],
            "cargo": "deputado_estadual",
            "sigla_partido": SIGLA_PARTIDO,
            "codigo_municipio": CODIGO_MUNICIPIO,
            "ano_eleicao": 2022,
            "total_votos_historicos": votos_por_cand.get(c["numero"], 0),
        }
        for c in CANDIDATOS_BASE
    ]

    return {
        "sigla_partido": SIGLA_PARTIDO,
        "numero_partido": "13",
        "codigo_municipio": CODIGO_MUNICIPIO,
        "ano_eleicao": 2022,
        "cargo": "deputado_estadual",
        "candidatos": candidatos,
        "total_vagas_disputa": 70,
        "fundo_total_reais": 2_500_000.0,
        "meta_quociente_partidario": 3.0,
        "territorios": territorios,
    }


def gerar_analise_completa(chapa: dict, bairros: list[dict]) -> dict:
    bairros_info = [
        {"codigo": b["codigo"], "nome": b["nome"], "total_eleitores": b["total_eleitores"]}
        for b in bairros
    ]
    return {
        "chapa": chapa,
        "bairros_info": bairros_info,
        "total_votos_validos": sum(b["total_eleitores"] for b in bairros),
        "total_vagas": 70,
        "limiar_sobreposicao": 0.15,
    }


if __name__ == "__main__":
    bairros_info = [{"codigo": b["codigo"], "nome": b["nome"], "total_eleitores": b["total_eleitores"]} for b in BAIRROS]

    territorios = gerar_territorios(CANDIDATOS_BASE, BAIRROS)
    chapa = gerar_chapa(territorios)
    analise = gerar_analise_completa(chapa, BAIRROS)

    out = ROOT / "processed"
    out.mkdir(parents=True, exist_ok=True)

    (out / "bairros.json").write_text(json.dumps({"bairros": bairros_info}, ensure_ascii=False, indent=2))
    (out / "chapa_demo.json").write_text(json.dumps(chapa, ensure_ascii=False, indent=2))
    (out / "analise_demo.json").write_text(json.dumps(analise, ensure_ascii=False, indent=2))

    print("✓ Dados demo gerados em data/processed/")
    print(f"  - {len(BAIRROS)} bairros")
    print(f"  - {len(chapa['candidatos'])} candidatos")
    print(f"  - {len(territorios)} registros de território")
