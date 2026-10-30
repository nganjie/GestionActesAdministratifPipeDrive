"""Réinitialisation de la démonstration : base et Pipedrive repartent ensemble, sans toucher au reste."""

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.base import get_session_factory
from app.db.models import Dossier, JournalTechnique, ReferenceSynchro
from app.domain.enums import EtatSynchro
from app.scripts.seed_demo import DOSSIERS, peupler
from tests.conftest import jetons, vider_file

URL = "/api/v1/admin/demo/reinitialiser"


@pytest.fixture
def mode_demo(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(get_settings(), "mode_demo", True)


async def _compter(modele, *conditions) -> int:  # noqa: ANN001
    async with get_session_factory()() as session:
        return int(await session.scalar(select(func.count()).select_from(modele).where(*conditions)))


def _deals_act(pipedrive) -> list[dict]:  # noqa: ANN001
    return [d for d in pipedrive.deals.values() if d["title"].startswith("ACT-")]


async def test_refusee_hors_mode_demo(client, admin, agents):  # noqa: ANN001
    assert (await client.get("/api/v1/admin/demo", headers=admin)).json()["actif"] is False
    r = await client.post(URL, headers=admin, json={"confirmation": "REINITIALISER"})
    assert r.status_code == 403 and r.json()["code"] == "MODE_DEMO_INACTIF"
    r = await client.post(URL, headers=agents["responsable"], json={"confirmation": "REINITIALISER"})
    assert r.status_code == 403


async def test_confirmation_exigee(client, admin, mode_demo):  # noqa: ANN001
    await peupler(get_session_factory())
    r = await client.post(URL, headers=admin, json={"confirmation": "oui"})
    assert r.status_code == 422 and r.json()["code"] == "CONFIRMATION_INVALIDE"
    assert await _compter(Dossier) == len(DOSSIERS)


async def test_reinitialisation_complete(client, admin, pipedrive, worker, mode_demo):  # noqa: ANN001
    await peupler(get_session_factory())
    await vider_file(worker)
    anciens = {d["id"] for d in _deals_act(pipedrive)}
    activites = sum(1 for a in pipedrive.activities.values() if a["deal_id"] in anciens)
    assert anciens and activites
    pipeline_id = next(iter(pipedrive.pipelines))
    # Ce qui ne relève pas de l'application, ou d'un autre pipeline, ne doit pas être touché.
    pipedrive.deals[1] = {"id": 1, "title": "Prospect sans rapport", "pipeline_id": pipeline_id}
    pipedrive.deals[2] = {"id": 2, "title": "ACT-2026-000001 — autre pipeline", "pipeline_id": 999}
    contacts = dict(pipedrive.persons)

    r = await client.post(URL, headers=admin, json={"confirmation": "REINITIALISER"})
    assert r.status_code == 200, r.text
    assert r.json() == {"dossiers_supprimes": len(DOSSIERS), "deals_supprimes": len(anciens),
                        "activites_supprimees": activites, "dossiers_crees": len(DOSSIERS), "pipedrive": True}
    assert set(pipedrive.deals) == {1, 2}
    assert not any(a["deal_id"] in anciens for a in pipedrive.activities.values())
    assert pipedrive.persons == contacts

    # Les dossiers rechargés repartent de ACT-AAAA-000001 et attendent le worker.
    liste = (await client.get("/api/v1/dossiers", headers=await jetons(client, "accueil", "MotDePasse-Accueil1"),
                              params={"taille": 100})).json()
    assert liste["total"] == len(DOSSIERS)
    assert min(d["reference"] for d in liste["elements"]).endswith("-000001")
    assert await _compter(ReferenceSynchro, ReferenceSynchro.etat != EtatSynchro.EN_ATTENTE) == 0

    await vider_file(worker)
    nouveaux = [d for d in _deals_act(pipedrive) if d["pipeline_id"] == pipeline_id]
    assert len(nouveaux) == len(anciens)
    assert len({d["title"] for d in nouveaux}) == len(nouveaux)
    assert pipedrive.persons.keys() == contacts.keys()
    assert await _compter(JournalTechnique, JournalTechnique.operation == "DEMO_REINITIALISATION",
                          JournalTechnique.resultat == "SUCCES") == 1


async def test_rien_n_est_efface_si_pipedrive_refuse_le_jeton(client, admin, pipedrive, mode_demo):  # noqa: ANN001
    await peupler(get_session_factory())
    pipedrive.panne("users.me", 401)
    r = await client.post(URL, headers=admin, json={"confirmation": "REINITIALISER"})
    assert r.status_code == 502 and r.json()["code"] == "PIPEDRIVE_AUTHENTIFICATION_REFUSEE"
    assert await _compter(Dossier) == len(DOSSIERS)
    assert await _compter(JournalTechnique, JournalTechnique.operation == "DEMO_REINITIALISATION",
                          JournalTechnique.resultat == "ECHEC") == 1


async def test_sans_pipedrive_seule_la_base_est_reinitialisee(client, admin, mode_demo, monkeypatch):  # noqa: ANN001
    monkeypatch.setattr(get_settings(), "pipedrive_api_token", None)
    await peupler(get_session_factory())
    r = await client.post(URL, headers=admin, json={"confirmation": " REINITIALISER "})
    assert r.status_code == 200, r.text
    assert r.json()["pipedrive"] is False and r.json()["dossiers_crees"] == len(DOSSIERS)
