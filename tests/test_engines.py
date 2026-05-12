"""
Testes dos motores de conflito, oportunidade e otimização.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engines.conflict import detectar_conflitos, resumo_conflitos
from src.engines.opportunity import analisar_bairros, mapa_oportunidade_conflito
from src.engines.optimizer import otimizar_alocacao, simular_acordo_territorial
from src.models.candidates import Candidato, Chapa, TerritorioCandidato
from src.models.electoral import CargoEnum, ResultadoBairro, ResultadoMunicipio
from src.models.spatial import Bairro


def _make_candidato(numero, nome, bairro_votos: dict) -> Candidato:
    cand = Candidato(
        numero=numero,
        nome=nome,
        cargo=CargoEnum.DEPUTADO_ESTADUAL,
        sigla_partido="PXL",
        codigo_municipio="355030",
        ano_eleicao=2022,
    )
    total = sum(bairro_votos.values())
    cand.total_votos_historicos = total
    cand.territorios = [
        TerritorioCandidato(
            codigo_bairro=b,
            nome_bairro=b,
            votos_historicos=v,
            percentual_do_candidato=v / total if total else 0,
        )
        for b, v in bairro_votos.items()
    ]
    if total > 0:
        cand.indice_concentracao = sum((v / total) ** 2 for v in bairro_votos.values())
    return cand


def _make_chapa(*candidatos) -> Chapa:
    return Chapa(
        sigla_partido="PXL",
        numero_partido="13",
        codigo_municipio="355030",
        ano_eleicao=2022,
        cargo=CargoEnum.DEPUTADO_ESTADUAL,
        candidatos=list(candidatos),
        total_vagas_disputa=70,
    )


# ── Testes de Conflito ────────────────────────────────────────────────────────

def test_sem_conflito():
    a = _make_candidato("01", "Ana", {"B01": 500, "B02": 300})
    b = _make_candidato("02", "Bruno", {"B03": 400, "B04": 200})
    chapa = _make_chapa(a, b)
    alertas = detectar_conflitos(chapa)
    assert len(alertas) == 0, "Territórios disjuntos não devem gerar conflito"


def test_conflito_alto():
    a = _make_candidato("01", "Ana",   {"B01": 500, "B02": 300, "B03": 200})
    b = _make_candidato("02", "Bruno", {"B01": 400, "B02": 250, "B04": 100})
    chapa = _make_chapa(a, b)
    alertas = detectar_conflitos(chapa, limiar_sobreposicao=0.10)
    assert len(alertas) >= 1
    assert alertas[0].nivel_alerta in ("alto", "crítico", "médio")
    assert "B01" in alertas[0].bairros_conflito
    assert "B02" in alertas[0].bairros_conflito


def test_favorecido_correto():
    """O candidato com maior elasticidade no bairro deve ser o favorecido."""
    # Ana muito concentrada em B01 (HHI alto → baixa elasticidade)
    a = _make_candidato("01", "Ana",   {"B01": 900, "B02": 50})
    # Bruno disperso (HHI baixo → mais elástico)
    b = _make_candidato("02", "Bruno", {"B01": 400, "B02": 400, "B03": 200})
    chapa = _make_chapa(a, b)
    alertas = detectar_conflitos(chapa, limiar_sobreposicao=0.05)
    assert len(alertas) >= 1
    # Bruno deve ser favorecido em B01 por ter menor concentração
    fav = alertas[0].favorecido_por_bairro.get("B01")
    assert fav == "02", f"Esperado Bruno (02), obtido {fav}"


def test_resumo_conflitos():
    a = _make_candidato("01", "Ana",   {"B01": 500, "B02": 300})
    b = _make_candidato("02", "Bruno", {"B01": 400, "B02": 200})
    c = _make_candidato("03", "Carlos",{"B01": 300, "B02": 250})
    chapa = _make_chapa(a, b, c)
    alertas = detectar_conflitos(chapa, limiar_sobreposicao=0.05)
    resumo = resumo_conflitos(alertas)
    assert resumo["total_pares_conflito"] >= 2
    assert resumo["bairros_conflito_unicos"] >= 1
    assert resumo["total_votos_risco"] > 0


# ── Testes de Oportunidade ────────────────────────────────────────────────────

def _make_bairros_e_resultados(config: list[dict], sigla="PXL"):
    bairros = []
    resultados = []
    for c in config:
        b = Bairro(
            codigo_bairro=c["codigo"],
            nome_bairro=c["nome"],
            codigo_municipio="355030",
            nome_municipio="SP",
            total_eleitores=c["eleitores"],
        )
        bairros.append(b)
        rb = ResultadoBairro(
            ano_eleicao=2022,
            cargo=CargoEnum.DEPUTADO_ESTADUAL,
            codigo_bairro=c["codigo"],
            nome_bairro=c["nome"],
            codigo_municipio="355030",
            sigla_partido=sigla,
            votos_por_candidato=c.get("votos_cands", {}),
            votos_legenda=c.get("votos_legenda", 0),
            votos_validos_bairro=c["eleitores"],
        )
        resultados.append(rb)
    return bairros, resultados


def test_vacuo_detectado():
    """Bairro com legenda forte mas sem candidato deve ser 'oportunidade'."""
    config = [
        {"codigo": "B01", "nome": "Centro", "eleitores": 10000, "votos_legenda": 2500},
        {"codigo": "B02", "nome": "Subúrbio", "eleitores": 8000, "votos_legenda": 200},
    ]
    bairros, resultados = _make_bairros_e_resultados(config)
    cand = _make_candidato("01", "Ana", {"B02": 100})  # não cobre B01
    chapa = _make_chapa(cand)

    analisados = analisar_bairros(bairros, resultados, chapa, {})
    b01 = next(a for a in analisados if a.codigo_bairro == "B01")
    assert b01.categoria == "oportunidade", f"Esperado 'oportunidade', obtido '{b01.categoria}'"
    assert b01.indice_vacuo > 0


def test_mapa_estrutura():
    config = [{"codigo": f"B{i:02d}", "nome": f"Bairro {i}", "eleitores": 5000, "votos_legenda": 500}
              for i in range(1, 6)]
    bairros, resultados = _make_bairros_e_resultados(config)
    cand = _make_candidato("01", "Ana", {"B01": 200, "B02": 150})
    chapa = _make_chapa(cand)
    analisados = analisar_bairros(bairros, resultados, chapa, {})
    mapa = mapa_oportunidade_conflito(analisados)
    assert mapa["total_bairros"] == 5
    assert "por_categoria" in mapa
    assert "bairros" in mapa


# ── Testes de Otimização ──────────────────────────────────────────────────────

def _make_resultado_municipio(votos_partido=50000, total=200000, vagas=70):
    return ResultadoMunicipio(
        ano_eleicao=2022,
        cargo=CargoEnum.DEPUTADO_ESTADUAL,
        codigo_municipio="355030",
        nome_municipio="SP",
        sigla_partido="PXL",
        total_votos_partido=votos_partido,
        total_votos_validos=total,
        total_vagas=vagas,
    )


def test_otimizacao_soma_100():
    candidatos = [
        _make_candidato("01", "Ana",    {"B01": 5000, "B02": 2000}),
        _make_candidato("02", "Bruno",  {"B03": 4000, "B04": 1500}),
        _make_candidato("03", "Carlos", {"B05": 3000, "B06": 1000}),
    ]
    chapa = _make_chapa(*candidatos)
    rm = _make_resultado_municipio()

    config = [{"codigo": f"B{i:02d}", "nome": f"Bairro {i}", "eleitores": 5000, "votos_legenda": 500}
              for i in range(1, 7)]
    bairros, resultados = _make_bairros_e_resultados(config)
    analisados = analisar_bairros(bairros, resultados, chapa, {})

    resultado = otimizar_alocacao(chapa, rm, analisados, [])
    total_pct = sum(a.percentual_otimizado for a in resultado.alocacoes)
    assert abs(total_pct - 1.0) < 0.01, f"Soma dos percentuais = {total_pct:.4f}, esperado ~1.0"


def test_simulacao_acordo():
    a = _make_candidato("01", "Ana",   {"B01": 5000, "B02": 3000})
    b = _make_candidato("02", "Bruno", {"B01": 4000, "B03": 2000})
    chapa = _make_chapa(a, b)
    rm = _make_resultado_municipio()

    config = [{"codigo": f"B{i:02d}", "nome": f"B{i}", "eleitores": 8000, "votos_legenda": 1000}
              for i in range(1, 4)]
    bairros, resultados = _make_bairros_e_resultados(config)
    analisados = analisar_bairros(bairros, resultados, chapa, {})

    cenario = simular_acordo_territorial(
        chapa,
        {"01": ["B01", "B02"], "02": ["B03"]},
        rm,
        analisados,
        "Teste de Acordo",
    )
    assert cenario.total_votos_chapa > 0
    assert cenario.qp_projetado > 0
    assert "01" in cenario.votos_projetados_por_candidato


if __name__ == "__main__":
    tests = [
        test_sem_conflito,
        test_conflito_alto,
        test_favorecido_correto,
        test_resumo_conflitos,
        test_vacuo_detectado,
        test_mapa_estrutura,
        test_otimizacao_soma_100,
        test_simulacao_acordo,
    ]
    falhas = 0
    for t in tests:
        try:
            t()
            print(f"  ✓  {t.__name__}")
        except Exception as e:
            print(f"  ✗  {t.__name__}: {e}")
            falhas += 1
    print(f"\n{'Todos os testes passaram!' if falhas == 0 else f'{falhas} falha(s)'}")
