from contextlib import asynccontextmanager
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.books import curated_router, local_library_router, reading_router as book_reading_router, router as books_router
from app.api.routes.analyses import reading_router as analysis_reading_router, router as analyses_router
from app.api.routes.settings import router as settings_router
from app.api.routes.study import router as study_router
from app.runtime import RuntimeSettings


# Without this, logger.exception() calls in the service layer are discarded and
# genuine failures leave no trace. Level is overridable for quieter local runs.
logging.basicConfig(
    level=os.environ.get("BOOKTHINKING_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

def create_app(settings: RuntimeSettings | None = None) -> FastAPI:
    resolved = settings or RuntimeSettings.from_environment()
    @asynccontextmanager
    async def lifespan(application):
        from app.services.storage import ApplicationPaths, BookRepository
        from app.services.analysis_job_store import AnalysisJobStore
        paths = ApplicationPaths.from_environment()
        paths.ensure_exists()
        BookRepository(paths.database_path)
        if resolved.deployment_mode == "local":
            AnalysisJobStore(paths.database_path).recover_interrupted()
        yield

    application = FastAPI(title="BookThinking API", lifespan=lifespan)
    application.state.runtime_settings = resolved
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type"],
    )
    if resolved.deployment_mode == "local":
        application.include_router(settings_router)
        application.include_router(books_router)
        application.include_router(local_library_router)
        application.include_router(study_router)
        application.include_router(analyses_router)
    application.include_router(curated_router)
    application.include_router(book_reading_router)
    application.include_router(analysis_reading_router)

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/health/ready")
    def ready() -> dict[str, str]:
        return {"status": "ready", "deployment_mode": resolved.deployment_mode}

    return application


app = create_app()
