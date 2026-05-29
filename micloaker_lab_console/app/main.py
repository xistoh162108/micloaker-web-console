from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .routes import analysis, compare, conversion, dashboard, exports, files, live, logs, mac_helper, ops, recording, runs, sessions
from .services.jobs import mark_unfinished_jobs_interrupted
from .services.metadata import rebuild_indexes
from .services.text_store import ensure_workspace


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def unjammed_label(value: str) -> str:
    return "Unjammed: true" if value == "uj1" else "Unjammed: false"


templates.env.filters["unjammed_label"] = unjammed_label


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_workspace(settings.workspace)
    mark_unfinished_jobs_interrupted(settings.workspace)
    rebuild_indexes(settings.workspace)
    app = FastAPI(title="MiCloaker Lab Console", version=settings.app_version)
    app.state.settings = settings
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    for router in [
        dashboard.router,
        sessions.router,
        runs.router,
        recording.router,
        conversion.router,
        analysis.router,
        compare.router,
        exports.router,
        files.router,
        live.router,
        logs.router,
        mac_helper.router,
        ops.router,
    ]:
        app.include_router(router)
    return app


def run_console() -> None:
    """Run the temporary local console using the configured localhost default."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port)


app = create_app()


if __name__ == "__main__":
    run_console()
