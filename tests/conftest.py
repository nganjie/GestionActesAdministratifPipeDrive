import os

os.environ.setdefault("JWT_SECRET", "secret-de-test-suffisamment-long-pour-hs256-0123456789")
os.environ["PIPEDRIVE_API_TOKEN"] = "test-token"
os.environ["PIPEDRIVE_BASE_URL"] = "https://pd.test"
os.environ["PIPEDRIVE_OWNER_ID"] = "42"
os.environ["ADMIN_IDENTIFIANT"] = "admin"
os.environ["ADMIN_MOT_DE_PASSE"] = "admin-mot-de-passe-solide"
os.environ["SYNC_WORKER_EMBARQUE"] = "false"
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

from collections.abc import AsyncIterator  # noqa: E402
from datetime import timedelta  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from sqlalchemy import update  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base, dispose_engine, get_engine, get_session_factory, init_engine, maintenant  # noqa: E402
from app.db.models import ReferenceSynchro  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services import auth as auth_service  # noqa: E402
from app.services import demarches  # noqa: E402
from app.workers.sync_worker import SyncWorker  # noqa: E402
from tests.fake_pipedrive import FakePipedrive  # noqa: E402

MOTS_DE_PASSE = "mot-de-passe-de-test-123"


@pytest.fixture
async def db(tmp_path) -> AsyncIterator[None]:  # noqa: ANN001
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path}/test.db"
    init_engine(url)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with get_session_factory()() as session:
        await demarches.initialiser_catalogue(session)
        await auth_service.creer_admin_initial(session, get_settings())
    yield
    await dispose_engine()


@pytest.fixture
async def client(db) -> AsyncIterator[httpx.AsyncClient]:  # noqa: ANN001
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def pipedrive() -> FakePipedrive:
    faux = FakePipedrive()
    with respx.mock(assert_all_called=False) as router:
        router.route(host="test").pass_through()
        faux.installer(router)
        yield faux


@pytest.fixture
def worker(db) -> SyncWorker:  # noqa: ANN001
    return SyncWorker(get_session_factory(), get_settings())


async def jetons(client: httpx.AsyncClient, identifiant: str, mot_de_passe: str = MOTS_DE_PASSE) -> dict[str, str]:
    r = await client.post("/api/v1/auth/login", json={"identifiant": identifiant, "mot_de_passe": mot_de_passe})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def admin(client) -> dict[str, str]:  # noqa: ANN001
    return await jetons(client, "admin", "admin-mot-de-passe-solide")


@pytest.fixture
async def agents(client, admin) -> dict[str, dict[str, str]]:  # noqa: ANN001
    comptes = {
        "accueil": ("ACCUEIL", None),
        "etat_civil": ("AGENT_ETAT_CIVIL", None),
        "etat_civil_2": ("AGENT_ETAT_CIVIL", None),
        "certification": ("AGENT_CERTIFICATION", None),
        "responsable": ("RESPONSABLE", None),
    }
    entetes = {}
    for identifiant, (role, categorie) in comptes.items():
        r = await client.post("/api/v1/utilisateurs", headers=admin, json={
            "nom": identifiant.replace("_", " ").title(), "identifiant": identifiant, "mot_de_passe": MOTS_DE_PASSE,
            "role": role, "categorie": categorie,
        })
        assert r.status_code == 201, r.text
        entetes[identifiant] = await jetons(client, identifiant)
    entetes["admin"] = admin
    return entetes


async def avancer_horloge(secondes: int = 3600) -> None:
    """Rend échues toutes les synchronisations programmées (évite d'attendre les délais de relance)."""
    async with get_session_factory()() as session:
        await session.execute(update(ReferenceSynchro).values(
            prochaine_tentative=maintenant() - timedelta(seconds=1)
        ))
        await session.commit()


async def vider_file(worker: SyncWorker, tours: int = 20) -> None:
    for _ in range(tours):
        if await worker.traiter_lot() == 0:
            await avancer_horloge()
            if await worker.traiter_lot() == 0:
                return


def dossier_deces(**surcharge) -> dict:  # noqa: ANN003
    corps = {
        "type_demarche": "DECES",
        "objet": "Établissement de l'acte de décès",
        "demandeur": {"nom": "Mballa", "prenom": "Jean", "telephone": "+237 690 00 00 00",
                      "email": "jean.mballa@example.cm"},
        "donnees_specifiques": {
            "defunt": {"nom": "Mballa", "prenom": "Etienne", "date_naissance": "1948-03-12"},
            "date_deces": "2026-10-24", "lieu_deces": "Yaoundé", "lien_declarant": "Fils",
        },
    }
    corps.update(surcharge)
    return corps
