"""Synchronisation Pipedrive (FRS UC13-UC15, ISD §10 : ISD-T02 à ISD-T17)."""

import logging
from datetime import date

import httpx
from sqlalchemy import select

from app.db.base import get_session_factory
from app.db.models import JournalTechnique, ReferenceSynchro
from app.integrations.pipedrive.mappers import CHAMPS_AUTORISES
from tests.conftest import avancer_horloge, dossier_deces, vider_file
from tests.test_dossiers import API, creer, declarer_tout, transition


async def refs() -> list[ReferenceSynchro]:
    async with get_session_factory()() as session:
        return list(await session.scalars(select(ReferenceSynchro).order_by(ReferenceSynchro.cree_le)))


async def parcours_jusqua(client, agents, cible: str) -> dict:  # noqa: ANN001
    d = await creer(client, agents)
    await declarer_tout(client, agents, d)
    etapes = ["SOUMIS", "EN_INSTRUCTION", "EN_ATTENTE_DECISION"]
    qui = {"SOUMIS": "accueil", "EN_INSTRUCTION": "etat_civil", "EN_ATTENTE_DECISION": "etat_civil"}
    for statut in etapes:
        r = await transition(client, agents, d["id"], qui[statut], statut)
        assert r.status_code == 200, r.text
        if statut == cible:
            return d
    r = await client.post(f"{API}/{d['id']}/decision", headers=agents["responsable"], json={"issue": "APPROUVE"})
    assert r.status_code == 200
    if cible == "APPROUVE":
        return d
    assert (await transition(client, agents, d["id"], "accueil", "DELIVRE")).status_code == 200
    return d


async def test_cycle_complet_synchronise(client, agents, pipedrive, worker):
    """ISD-T03, T09, T10 : contact, deal, étapes successives, activités, deal gagné et activités closes."""
    d = await parcours_jusqua(client, agents, "DELIVRE")
    await vider_file(worker)

    assert all(r.etat == "SYNCHRONISE" for r in await refs())
    assert len(pipedrive.persons) == 1
    person = next(iter(pipedrive.persons.values()))
    assert person["name"] == "Jean MBALLA"
    assert len(pipedrive.pipelines) == 1 and len(pipedrive.stages) == 6
    (deal,) = pipedrive.deals.values()
    assert deal["title"] == f"{d['reference']} — Acte de décès"
    assert deal["status"] == "won"
    assert pipedrive.stages[deal["stage_id"]]["name"] == "Délivré"
    sujets = sorted(a["subject"] for a in pipedrive.activities.values())
    assert len(sujets) == 4  # SOUMIS, EN_INSTRUCTION, EN_ATTENTE_DECISION, APPROUVE
    assert all(s.startswith(f"[{d['reference']}·E") for s in sujets)
    assert all(a["done"] for a in pipedrive.activities.values())

    etat = (await client.get(f"{API}/{d['id']}/synchronisation", headers=agents["accueil"])).json()
    assert etat["etat"] == "SYNCHRONISE"
    activites = (await client.get(f"{API}/{d['id']}/activites", headers=agents["accueil"])).json()
    assert activites["disponible"] is True
    assert {a["intitule"] for a in activites["elements"]} >= {"Vérifier les pièces", "Instruire le dossier"}


async def test_rejet_deal_perdu_sans_motif_detaille(client, agents, pipedrive, worker):
    d = await parcours_jusqua(client, agents, "EN_ATTENTE_DECISION")
    await client.post(f"{API}/{d['id']}/decision", headers=agents["responsable"],
                      json={"issue": "REJETE", "motif": "Pièce d'identité du défunt falsifiée"})
    await vider_file(worker)
    (deal,) = pipedrive.deals.values()
    assert deal["status"] == "lost"
    assert deal["lost_reason"] == "Dossier rejeté"
    assert "falsifiée" not in str(pipedrive.requetes)


async def test_contact_existant_reutilise(client, agents, pipedrive, worker):
    """ISD-T04 : le demandeur existe déjà dans Pipedrive (même e-mail)."""
    pipedrive.persons[7] = {"id": 7, "name": "Jean Mballa",
                            "emails": [{"value": "jean.mballa@example.cm"}], "phones": []}
    await creer(client, agents)
    await vider_file(worker)
    assert list(pipedrive.persons) == [7]
    assert pipedrive.appels("persons.create") == []
    assert (await refs())[0].id_pipedrive == 7


async def test_relance_apres_indisponibilite(client, agents, pipedrive, worker):
    """ISD-T06 : 503 puis succès ; EN_ATTENTE entre-temps."""
    pipedrive.panne("persons.search", 503, 503)
    await creer(client, agents)
    assert await worker.traiter_lot() == 1
    (ref,) = await refs()
    assert ref.etat == "EN_ATTENTE" and ref.tentatives == 1 and ref.code_erreur == "ERREUR_SERVEUR"
    await vider_file(worker)
    (ref,) = await refs()
    assert ref.etat == "SYNCHRONISE"
    assert len(pipedrive.persons) == 1


async def test_echec_apres_cinq_tentatives_puis_relance_manuelle(client, agents, pipedrive, worker):
    """ISD-T06 et UC15 : 5 échecs → ECHEC ; relance par l'administrateur."""
    pipedrive.panne("persons.search", *([503] * 5))
    await creer(client, agents)
    await vider_file(worker)
    (ref,) = await refs()
    assert ref.etat == "ECHEC" and ref.tentatives == 5
    r = await client.post(f"/api/v1/synchronisations/{ref.id}/relance", headers=agents["admin"])
    assert r.status_code == 202
    await vider_file(worker)
    (ref,) = await refs()
    assert ref.etat == "SYNCHRONISE"


async def test_jeton_refuse_sans_relance(client, agents, pipedrive, worker, monkeypatch):
    """ISD-T02 : 401 → ECHEC immédiat, aucune nouvelle tentative."""
    pipedrive.panne("persons.search", 401)
    await creer(client, agents)
    await vider_file(worker)
    (ref,) = await refs()
    assert ref.etat == "ECHEC" and ref.code_erreur == "AUTHENTIFICATION_REFUSEE"
    assert len(pipedrive.appels("persons.search")) == 1


async def test_timeout_apres_creation_sans_doublon(client, agents, pipedrive, worker):
    """ISD-T07 : l'activité est créée mais la réponse est perdue ; la relance la retrouve par son marqueur."""
    d = await creer(client, agents)
    await declarer_tout(client, agents, d)
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    pipedrive.panne("activities.create", "apres:timeout")
    await vider_file(worker)
    assert len(pipedrive.activities) == 1
    assert len(pipedrive.appels("activities.create")) == 1
    assert all(r.etat == "SYNCHRONISE" for r in await refs())


async def test_timeout_creation_deal_sans_doublon(client, agents, pipedrive, worker):
    d = await creer(client, agents)
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    pipedrive.panne("deals.create", "apres:timeout")
    await vider_file(worker)
    assert len(pipedrive.deals) == 1
    assert len(pipedrive.appels("deals.search")) == 1


async def test_limite_de_debit_respecte_retry_after(client, agents, pipedrive, worker):
    """ISD-T08 : 429 avec Retry-After: 7 → prochaine tentative dans au moins 7 s."""
    pipedrive.panne("persons.search", (429, {"Retry-After": "7"}))
    await creer(client, agents)
    await worker.traiter_lot()
    (ref,) = await refs()
    assert ref.etat == "EN_ATTENTE" and ref.code_erreur == "LIMITE_DEBIT"
    ecart = (ref.prochaine_tentative - ref.maj_le).total_seconds()
    assert 6 <= ecart <= 8
    assert await worker.traiter_lot() == 0  # pas encore échue


async def test_deal_supprime_dans_pipedrive_est_recree(client, agents, pipedrive, worker):
    """ISD-T11 / RI08."""
    d = await creer(client, agents)
    await declarer_tout(client, agents, d)
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    await vider_file(worker)
    pipedrive.deals.clear()
    await transition(client, agents, d["id"], "etat_civil", "EN_INSTRUCTION")
    await vider_file(worker)
    (deal,) = pipedrive.deals.values()
    assert pipedrive.stages[deal["stage_id"]]["name"] == "En instruction"
    assert all(r.etat == "SYNCHRONISE" for r in await refs())


async def test_evenement_rejoue_une_seule_activite(client, agents, pipedrive, worker):
    """ISD-T12 / RM06 : retraiter la file ne recrée rien."""
    await parcours_jusqua(client, agents, "EN_INSTRUCTION")
    await vider_file(worker)
    avant = len(pipedrive.activities)
    async with get_session_factory()() as session:
        from app.db.models import EvenementOutbox

        for evt in await session.scalars(select(EvenementOutbox)):
            evt.traite = False
        for ref in await session.scalars(select(ReferenceSynchro)):
            ref.etat = "EN_ATTENTE"
            ref.indetermine = True
        await session.commit()
    await vider_file(worker)
    assert len(pipedrive.activities) == avant
    assert len(pipedrive.deals) == 1 and len(pipedrive.persons) == 1


async def test_minimisation_des_donnees(client, agents, pipedrive, worker):
    """ISD-T13 : aucun champ hors liste, aucune donnée spécifique transmise."""
    await parcours_jusqua(client, agents, "DELIVRE")
    await vider_file(worker)
    types = {"persons": "person", "deals": "deal", "activities": "activity"}
    for requete in pipedrive.requetes:
        if requete["methode"] in ("POST", "PATCH") and requete["json"]:
            objet = next((t for k, t in types.items() if f"/api/v2/{k}" in requete["url"]), None)
            if objet:
                assert set(requete["json"]) <= CHAMPS_AUTORISES[objet], requete
    tout = str(pipedrive.requetes)
    for interdit in ("Etienne", "1948-03-12", "Yaoundé", "Fils"):
        assert interdit not in tout


async def test_journaux_sans_jeton(client, agents, pipedrive, worker, caplog):
    """ISD-T14 : ni jeton ni coordonnées dans les journaux."""
    caplog.set_level(logging.INFO)
    await creer(client, agents)
    await vider_file(worker)
    async with get_session_factory()() as session:
        lignes = list(await session.scalars(select(JournalTechnique)))
    assert any(j.operation == "OP-02" for j in lignes)
    texte = str([(j.detail, j.code_erreur) for j in lignes]) + caplog.text
    assert "test-token" not in texte
    assert "jean.mballa" not in texte and "690000000" not in texte
    r = await client.get("/api/v1/admin/journaux", headers=agents["admin"], params={"operation": "OP-03"})
    assert r.json()["total"] == 1


async def test_route_retiree_alerte(client, agents, pipedrive, worker):
    """ISD-T15 : 410 → ECHEC sans relance."""
    pipedrive.panne("persons.search", 410)
    await creer(client, agents)
    await vider_file(worker)
    (ref,) = await refs()
    assert ref.etat == "ECHEC" and ref.code_erreur == "ROUTE_RETIREE"


async def test_pagination_par_curseur(client, agents, pipedrive, worker):
    """ISD-T16."""
    pipedrive.taille_page = 2
    d = await parcours_jusqua(client, agents, "APPROUVE")
    await vider_file(worker)
    r = (await client.get(f"{API}/{d['id']}/activites", headers=agents["accueil"])).json()
    assert len(r["elements"]) == 4
    assert len(pipedrive.appels("activities.list")) >= 2


async def test_activites_indisponibles_sans_bloquer(client, agents, pipedrive, worker):
    """UC04 : Pipedrive en panne → données métier servies, activités signalées indisponibles."""
    d = await creer(client, agents)
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    await vider_file(worker)
    pipedrive.panne("activities.list", httpx.ConnectError("refusé"))
    r = await client.get(f"{API}/{d['id']}/activites", headers=agents["accueil"])
    assert r.status_code == 200
    assert r.json() == {"disponible": False, "raison": "ERREUR_RESEAU", "elements": []}


async def test_metier_non_bloque_par_panne(client, agents, pipedrive, worker):
    """RI10 : Pipedrive indisponible, le parcours métier continue."""
    pipedrive.panne("persons.search", *([httpx.ConnectError("hors ligne")] * 3))
    d = await creer(client, agents)
    await worker.traiter_lot()
    r = await transition(client, agents, d["id"], "accueil", "SOUMIS")
    assert r.status_code == 200
    assert r.json()["synchronisation"]["etat"] == "EN_ATTENTE"


async def test_sante_pipedrive(client, agents, pipedrive, worker):
    r = await client.get("/api/v1/admin/sante/pipedrive", headers=agents["admin"])
    corps = r.json()
    assert corps["configure"] is True and corps["jeton_valide"] is True
    assert corps["company_domain"] == "mairie-demo"
    assert corps["types_activite_manquants"] == []
    assert corps["pipeline_initialise"] is False


async def test_types_activite_manquants(client, agents, pipedrive):
    """ISD-T17."""
    pipedrive.activity_types = [{"key_string": "call", "active_flag": True}]
    r = await client.get("/api/v1/admin/sante/pipedrive", headers=agents["admin"])
    assert r.json()["types_activite_manquants"] == ["deadline", "task"]


async def test_relance_globale_et_liste(client, agents, pipedrive, worker):
    pipedrive.panne("persons.search", 403)
    await creer(client, agents)
    await vider_file(worker)
    r = await client.get("/api/v1/synchronisations", headers=agents["admin"], params={"etat": "ECHEC"})
    assert r.json()["total"] == 1
    r = await client.post("/api/v1/synchronisations/relance-globale", headers=agents["admin"])
    assert r.json() == {"relancees": 1}
    await vider_file(worker)
    assert (await refs())[0].etat == "SYNCHRONISE"


async def test_maj_demandeur_propagee(client, agents, pipedrive, worker):
    await creer(client, agents)
    await vider_file(worker)
    autre = dossier_deces(donnees_specifiques={
        "defunt": {"nom": "Ngono", "prenom": "Marie"}, "date_deces": date.today().isoformat(),
        "lieu_deces": "Douala", "lien_declarant": "Neveu",
    })
    autre["demandeur"]["telephone"] = "+237677000000"
    assert (await client.post(API, headers=agents["accueil"], json=autre)).status_code == 201
    await avancer_horloge()
    await vider_file(worker)
    (person,) = pipedrive.persons.values()
    assert person["phones"][0]["value"] == "+237677000000"

