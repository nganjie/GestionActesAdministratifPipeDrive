"""Point d'entrée de l'API intermédiaire (CDC §3.1)."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1 import admin, auth, dossiers
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import (
    configurer_logging,
    correlation_id_var,
    get_correlation_id,
    nouvel_identifiant_correlation,
)
from app.db.base import dispose_engine, get_session_factory, init_engine
from app.services import auth as auth_service
from app.services import demarches
from app.workers.sync_worker import SyncWorker

logger = logging.getLogger("app")

ENTETE_CORRELATION = "X-Correlation-Id"

DESCRIPTION = """
API intermédiaire entre les applications clientes de la mairie et Pipedrive.

* Le module métier est la **source de vérité** des dossiers ; Pipedrive en reçoit une projection minimale.
* Toutes les erreurs suivent le format `{code, message, details, correlation_id}` (FRS §7.2).
* Les synchronisations sont asynchrones : chaque réponse indique leur état (`SYNCHRONISE`, `EN_ATTENTE`, `ECHEC`).
"""


def _reponse_erreur(status_code: int, code: str, message: str, details: list | None = None,
                    extra: dict | None = None) -> JSONResponse:
    corps = {"code": code, "message": message, "details": details or [], "correlation_id": get_correlation_id()}
    corps.update(extra or {})
    return JSONResponse(status_code=status_code, content=corps)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configurer_logging()
    session_factory = init_engine(settings.database_url)
    async with session_factory() as session:
        await demarches.initialiser_catalogue(session)
        await auth_service.creer_admin_initial(session, settings)
    tache = arret = None
    if settings.sync_worker_embarque:
        arret = asyncio.Event()
        tache = asyncio.create_task(SyncWorker(get_session_factory(), settings).executer(arret))
    yield
    if tache and arret:
        arret.set()
        await tache
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="API intermédiaire — actes administratifs / Pipedrive",
        version="0.1.0", description=DESCRIPTION, lifespan=lifespan,
        docs_url="/docs", openapi_url="/openapi.json",
    )
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                           allow_methods=["*"], allow_headers=["*"], expose_headers=[ENTETE_CORRELATION])

    @app.middleware("http")
    async def correlation(request: Request, call_next):  # noqa: ANN001, ANN202
        valeur = request.headers.get(ENTETE_CORRELATION) or nouvel_identifiant_correlation()
        jeton = correlation_id_var.set(valeur[:64])
        try:
            reponse = await call_next(request)
        finally:
            correlation_id_var.reset(jeton)
        reponse.headers[ENTETE_CORRELATION] = valeur[:64]
        return reponse

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("%s : %s", exc.code, exc.message)
        return _reponse_erreur(exc.status_code, exc.code, exc.message, exc.details, exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"champ": ".".join(str(p) for p in e["loc"] if p != "body"),
             "erreur": str(e["msg"]).removeprefix("Value error, ")}
            for e in exc.errors()
        ]
        return _reponse_erreur(400, "VALIDATION_ECHOUEE", "Certains champs sont invalides.", details)

    @app.exception_handler(StaleDataError)
    async def _version(_: Request, __: StaleDataError) -> JSONResponse:
        return _reponse_erreur(409, "CONFLIT_DE_VERSION",
                               "Le dossier a été modifié entre-temps : rechargez-le puis recommencez.")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "RESSOURCE_INTROUVABLE", 405: "METHODE_NON_AUTORISEE", 401: "NON_AUTHENTIFIE"}
        return _reponse_erreur(exc.status_code, codes.get(exc.status_code, "ERREUR_HTTP"), str(exc.detail))

    @app.exception_handler(Exception)
    async def _inattendue(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("erreur inattendue", exc_info=exc)
        return _reponse_erreur(500, "ERREUR_INTERNE", "Une erreur inattendue est survenue.")

    for routeur in (auth.router, dossiers.router, admin.router):
        app.include_router(routeur, prefix="/api/v1")

    @app.get("/", include_in_schema=False)
    async def accueil() -> RedirectResponse:
        return RedirectResponse("/docs")

    return app


app = create_app()
