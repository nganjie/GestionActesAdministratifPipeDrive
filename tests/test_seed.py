"""Données de démonstration : comptes utilisables et dossiers dans tous les statuts, sans doublon au second passage."""

from collections import Counter

from app.db.base import get_session_factory
from app.scripts.seed_demo import COMPTES, DOSSIERS, peupler
from tests.conftest import jetons


async def test_peupler_puis_relancer(client, db):
    resultat = await peupler(get_session_factory())
    assert len(resultat["dossiers"]) == len(DOSSIERS)
    statuts = Counter(str(s) for _, _, s in resultat["dossiers"])
    assert set(statuts) == {"BROUILLON", "SOUMIS", "INCOMPLET", "EN_INSTRUCTION", "EN_ATTENTE_DECISION",
                            "APPROUVE", "DELIVRE", "REJETE", "ANNULE"}

    second = await peupler(get_session_factory())
    assert second["dossiers"] == [] and second["dossiers_existants"] == len(DOSSIERS)

    for compte in COMPTES:
        await jetons(client, compte.identifiant, compte.mot_de_passe)

    entetes = await jetons(client, "civil", "MotDePasse-Civil1")
    liste = (await client.get("/api/v1/dossiers", headers=entetes, params={"taille": 100})).json()
    assert {d["categorie"] for d in liste["elements"]} == {"ETAT_CIVIL"}

    entetes = await jetons(client, "accueil", "MotDePasse-Accueil1")
    delivre = next(d for d in (await client.get("/api/v1/dossiers", headers=entetes,
                                                 params={"statut": "DELIVRE", "taille": 100})).json()["elements"])
    historique = (await client.get(f"/api/v1/dossiers/{delivre['id']}/historique", headers=entetes)).json()
    assert historique[-1]["nouveau_statut"] == "DELIVRE" and historique[0]["auteur_nom"] == "Léa Abena"
