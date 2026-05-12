"""
Ponto de entrada da aplicação.

Uso:
    python run.py
    python run.py --host 0.0.0.0 --port 8080 --reload
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Moneyball 3.0 — Servidor")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    # Gerar dados demo se não existirem
    demo_path = Path("data/processed/analise_demo.json")
    if not demo_path.exists():
        print("⚙ Gerando dados demo...")
        subprocess.run([sys.executable, "data/gerar_demo.py"], check=True)

    import uvicorn
    uvicorn.run(
        "src.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
