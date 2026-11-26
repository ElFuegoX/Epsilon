"""Point d'entrée FastAPI de WÉMA (`python -m api.app`).

Prêt pour :
- exécution locale (`http://localhost:8000`) et `docker compose up` ;
- déploiement tout-en-un sur Hugging Face Spaces (port `$PORT` / `7860`,
  service du build React `web/dist` s'il est présent).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router
from config import VERSION, settings
from db import ensure_dirs, initialize


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    initialize()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="WÉMA — Facturation assistée",
        version=VERSION,
        description="API déterministe de facturation assistée (Hackathon BWAI 2026 — SIMULATION).",
        lifespan=lifespan,
    )

    origins_env = os.getenv("CORS_ORIGINS", "*")
    allow_origins = [o.strip() for o in origins_env.split(",") if o.strip()] or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    # Si le frontend React est compilé dans web/dist (déploiement Hugging Face Spaces),
    # FastAPI sert directement l'interface sur la même URL (zéro souci CORS).
    web_dist = Path(__file__).resolve().parent.parent / "web" / "dist"
    if web_dist.is_dir():
        assets_dir = web_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        index_html = web_dist / "index.html"
        if index_html.is_file():
            @app.get("/", include_in_schema=False)
            def serve_index():
                return FileResponse(str(index_html))

    return app


app = create_app()


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
