"""
Aplicação FastAPI principal.

Monta:
  /           → dashboard HTML
  /api/       → endpoints de análise
  /api/demo/  → dados demo pré-carregados para o dashboard
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .routes.analise import router as analise_router

BASE = Path(__file__).parent.parent.parent
TEMPLATES = BASE / "frontend" / "templates"
STATIC = BASE / "frontend" / "static"
DATA = BASE / "data" / "processed"

app = FastAPI(
    title="Geopolítica de Precisão Eleitoral — Moneyball 3.0",
    description="Sistema de inteligência geográfica para alocação de recursos eleitorais.",
    version="1.0.0",
)

# Static files
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

# API routes
app.include_router(analise_router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html = (TEMPLATES / "dashboard.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


# ── Demo data endpoints ────────────────────────────────────────────────────────

@app.get("/api/demo/bairros")
async def demo_bairros():
    """Retorna bairros com coordenadas para o mapa."""
    from data.gerar_demo import BAIRROS  # type: ignore
    return {"bairros": BAIRROS}


@app.get("/api/demo/analise-completa")
async def demo_analise_completa():
    """
    Executa análise completa com dados demo pré-gerados e retorna resultado
    enriquecido com a chapa raw para uso no simulador.
    """
    payload_path = DATA / "analise_demo.json"
    if not payload_path.exists():
        return {"error": "Dados demo não gerados. Execute: python data/gerar_demo.py"}

    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    from .schemas import AnaliseCompletaRequest
    from .routes.analise import analise_completa

    req = AnaliseCompletaRequest(**payload)
    resultado = analise_completa(req)

    # Enriquecer com chapa raw para o simulador JS
    result_dict = resultado.model_dump()
    result_dict["_chapa_raw"] = payload["chapa"]
    return result_dict


@app.get("/api/demo/chapa")
async def demo_chapa():
    chapa_path = DATA / "chapa_demo.json"
    if not chapa_path.exists():
        return {"error": "Execute python data/gerar_demo.py primeiro"}
    return json.loads(chapa_path.read_text(encoding="utf-8"))


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "version": app.version}
