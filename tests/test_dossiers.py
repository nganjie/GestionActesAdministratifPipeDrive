"""UC03 à UC12 : dossiers, pièces, cycle de vie, décision (FRS §4, §5 ; critères CR02, CR08, CR09)."""

from datetime import date, timedelta

from tests.conftest import dossier_deces

API = "/api/v1/dossiers"


async def creer(client, agents, **surcharge) -> dict:  # noqa: ANN001, ANN003
    r = await client.post(API, headers=agents["accueil"], json=dossier_deces(**surcharge))
    assert r.status_code == 201, r.text
    return r.json()


async def declarer_tout(client, agents, dossier: dict, qui: str = "accueil") -> None:  # noqa: ANN001
    for piece in dossier["pieces_requises"]:
        r = await client.post(f"{API}/{dossier['id']}/pieces", headers=agents[qui], json={
            "code_piece": piece["code"], "date_reception": date.today().isoformat(), "etat": "CONFORME",
        })
        assert r.status_code == 201, r.text


async def transition(client, agents, dossier_id: str, qui: str, cible: str, **extra):  # noqa: ANN001, ANN003, ANN201
    return await client.post(f"{API}/{dossier_id}/transitions", headers=agents[qui],
                             json={"statut_cible": cible, **extra})


# --- UC03 Création ---------------------------------------------------------------------------------------

async def test_creation_dossier_deces(client, agents):
    d = await creer(client, agents)
    assert d["statut"] == "BROUILLON"
    assert d["reference"].startswith(f"ACT-{date.today().year}-")
    assert d["categorie"] == "ETAT_CIVIL"
    assert [p["code"] for p in d["pieces_requises"]] == ["CERTIFICAT_DECES", "IDENTITE_DEFUNT", "IDENTITE_DECLARANT"]
    assert d["demandeur"]["telephone"] == "+237690000000"
    assert d["synchronisation"]["etat"] == "EN_ATTENTE"
    assert d["synchronisation"]["objets"][0]["type"] == "person"


async def test_validation_detaillee_par_champ(client, agents):
    corps = dossier_deces()
    corps["demandeur"]["telephone"] = "12"
    corps["donnees_specifiques"]["date_deces"] = (date.today() + timedelta(days=3)).isoformat()
    r = await client.post(API, headers=agents["accueil"], json=corps)
    assert r.status_code == 400
    champs = {d["champ"] for d in r.json()["details"]}
    assert "demandeur.telephone" in champs


async def test_donnees_specifiques_invalides(client, agents):
    corps = dossier_deces()
    corps["donnees_specifiques"]["date_deces"] = (date.today() + timedelta(days=3)).isoformat()
    r = await client.post(API, headers=agents["accueil"], json=corps)
    assert r.status_code == 400
    assert r.json()["details"][0]["champ"] == "donnees_specifiques.date_deces"


async def test_acte_de_naissance_hors_perimetre(client, agents):
    r = await client.post(API, headers=agents["accueil"], json=dossier_deces(type_demarche="NAISSANCE"))
    assert r.status_code == 422
    assert r.json()["code"] == "DEMARCHE_HORS_PERIMETRE"
    copie = dossier_deces(type_demarche="COPIE_ACTE", donnees_specifiques={
        "type_acte": "NAISSANCE", "numero_acte": "123", "annee": 2001, "centre_etat_civil": "Centre 1",
        "qualite_demandeur": "Lui-même",
    })
    r = await client.post(API, headers=agents["accueil"], json=copie)
    assert r.status_code == 422
    assert r.json()["code"] == "DEMARCHE_HORS_PERIMETRE"


async def test_doublon_detecte_puis_confirme(client, agents):
    premier = await creer(client, agents)
    r = await client.post(API, headers=agents["accueil"], json=dossier_deces())
    assert r.status_code == 409
    assert r.json()["code"] == "DOUBLON_DETECTE"
    assert r.json()["reference_existante"] == premier["reference"]
    r = await client.post(API, headers=agents["accueil"], json=dossier_deces(confirmer_doublon=True))
    assert r.status_code == 422
    r = await client.post(API, headers=agents["accueil"], json=dossier_deces(
        confirmer_doublon=True, motif_doublon="Erreur de saisie sur le premier dossier"))
    assert r.status_code == 201


async def test_demandeur_reutilise(client, agents):
    a = await creer(client, agents)
    b = await creer(client, agents, donnees_specifiques={
        "defunt": {"nom": "Ngono", "prenom": "Marie"}, "date_deces": "2026-10-20",
        "lieu_deces": "Douala", "lien_declarant": "Neveu",
    })
    assert a["demandeur"]["id"] == b["demandeur"]["id"]


async def test_seul_l_accueil_cree(client, agents):
    r = await client.post(API, headers=agents["etat_civil"], json=dossier_deces())
    assert r.status_code == 403


async def test_cinq_demarches(client, agents):
    futur = (date.today() + timedelta(days=30)).isoformat()
    exemples = {
        "MARIAGE": {
            "epoux_1": {"nom": "Ngo Biyong", "prenom": "Clarisse"}, "epoux_2": {"nom": "Essomba", "prenom": "Paul"},
            "date_celebration_prevue": futur,
            "temoins": [{"nom": "Abena", "prenom": "Luc"}, {"nom": "Manga", "prenom": "Rose"}],
        },
        "COPIE_ACTE": {"type_acte": "MARIAGE", "numero_acte": "456", "annee": 2015, "centre_etat_civil": "Centre 2",
                       "qualite_demandeur": "Conjoint"},
        "LEGALISATION": {"intitule_document": "Attestation", "signataire": {"nom": "Kamga", "prenom": "Eric"},
                         "qualite_signataire": "Gérant"},
        "CERTIFICATION_CONFORME": {"intitule_document": "Diplôme de licence", "nombre_copies": 3},
    }
    for code, donnees in exemples.items():
        r = await client.post(API, headers=agents["accueil"],
                              json=dossier_deces(type_demarche=code, donnees_specifiques=donnees))
        assert r.status_code == 201, (code, r.text)


# --- UC05 / UC04 Consultation et périmètre -------------------------------------------------------------------

async def test_perimetre_par_categorie(client, agents):
    d = await creer(client, agents)
    assert (await client.get(f"{API}/{d['id']}", headers=agents["etat_civil"])).status_code == 200
    r = await client.get(f"{API}/{d['id']}", headers=agents["certification"])
    assert r.status_code == 404
    liste = (await client.get(API, headers=agents["certification"])).json()
    assert liste["total"] == 0
    liste = (await client.get(API, headers=agents["etat_civil"], params={"statut": "BROUILLON"})).json()
    assert liste["total"] == 1
    assert liste["elements"][0]["synchronisation"] == "EN_ATTENTE"


async def test_recherche_par_demandeur(client, agents):
    await creer(client, agents)
    r = await client.get(API, headers=agents["accueil"], params={"demandeur": "mball"})
    assert r.json()["total"] == 1
    r = await client.get(API, headers=agents["accueil"], params={"demandeur": "inconnu"})
    assert r.json()["total"] == 0


# --- UC06 Modification ----------------------------------------------------------------------------------------

async def test_modification_brouillon(client, agents):
    d = await creer(client, agents)
    r = await client.patch(f"{API}/{d['id']}", headers=agents["accueil"], json={"objet": "Objet corrigé"})
    assert r.status_code == 200
    assert r.json()["objet"] == "Objet corrigé"
    r = await client.patch(f"{API}/{d['id']}", headers=agents["accueil"], json={"type_demarche": "MARIAGE"})
    assert r.status_code == 400


async def test_modification_refusee_apres_soumission(client, agents):
    d = await creer(client, agents)
    assert (await transition(client, agents, d["id"], "accueil", "SOUMIS")).status_code == 200
    r = await client.patch(f"{API}/{d['id']}", headers=agents["accueil"], json={"objet": "Trop tard"})
    assert r.status_code == 409
    assert r.json()["code"] == "ETAT_INCOMPATIBLE"


# --- UC07 / UC08 Pièces et complétude ------------------------------------------------------------------------

async def test_pieces_et_completude(client, agents):
    d = await creer(client, agents)
    r = await client.post(f"{API}/{d['id']}/pieces", headers=agents["accueil"], json={
        "code_piece": "INCONNUE", "date_reception": date.today().isoformat(), "etat": "CONFORME"})
    assert r.status_code == 422
    assert r.json()["code"] == "PIECE_TYPE_INCONNU"
    r = await client.post(f"{API}/{d['id']}/pieces", headers=agents["accueil"], json={
        "code_piece": "CERTIFICAT_DECES", "date_reception": date.today().isoformat(), "etat": "CONFORME"})
    assert r.status_code == 201
    r = await client.post(f"{API}/{d['id']}/pieces", headers=agents["accueil"], json={
        "code_piece": "CERTIFICAT_DECES", "date_reception": date.today().isoformat(), "etat": "CONFORME"})
    assert r.status_code == 409
    await transition(client, agents, d["id"], "accueil", "SOUMIS")

    v = await client.post(f"{API}/{d['id']}/verification-completude", headers=agents["etat_civil"])
    assert v.status_code == 200
    assert v.json()["complet"] is False
    assert v.json()["statut"] == "INCOMPLET"
    assert len(v.json()["pieces_manquantes"]) == 2

    for code in ("IDENTITE_DEFUNT", "IDENTITE_DECLARANT"):
        await client.post(f"{API}/{d['id']}/pieces", headers=agents["accueil"], json={
            "code_piece": code, "date_reception": date.today().isoformat(), "etat": "CONFORME"})
    v = await client.post(f"{API}/{d['id']}/verification-completude", headers=agents["etat_civil"])
    assert v.json() | {"pieces_manquantes": []} == {
        "complet": True, "pieces_manquantes": [], "statut": "INCOMPLET", "transition_proposee": "EN_INSTRUCTION"}


async def test_piece_a_corriger_bloque_l_instruction(client, agents):
    d = await creer(client, agents)
    await declarer_tout(client, agents, d)
    pieces = (await client.get(f"{API}/{d['id']}/pieces", headers=agents["accueil"])).json()
    r = await client.patch(f"{API}/{d['id']}/pieces/{pieces[0]['id']}", headers=agents["accueil"],
                           json={"etat": "A_CORRIGER", "observation": "illisible"})
    assert r.status_code == 200
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    r = await transition(client, agents, d["id"], "etat_civil", "EN_INSTRUCTION")
    assert r.status_code == 422
    assert r.json()["code"] == "PIECES_INCOMPLETES"


# --- UC09 à UC12 Cycle de vie ----------------------------------------------------------------------------------

async def test_parcours_complet_deces(client, agents):
    """CR08 : UC03 → UC07 → UC09 → UC08 → UC09 → UC10 → UC09."""
    d = await creer(client, agents)
    await declarer_tout(client, agents, d)
    assert (await transition(client, agents, d["id"], "accueil", "SOUMIS")).json()["statut"] == "SOUMIS"
    v = await client.post(f"{API}/{d['id']}/verification-completude", headers=agents["etat_civil"])
    assert v.json()["complet"] is True
    r = await transition(client, agents, d["id"], "etat_civil", "EN_INSTRUCTION")
    assert r.json()["statut"] == "EN_INSTRUCTION"
    assert r.json()["instructeur_id"]
    r = await transition(client, agents, d["id"], "etat_civil", "EN_ATTENTE_DECISION", commentaire="RAS")
    assert r.json()["statut"] == "EN_ATTENTE_DECISION"
    r = await client.post(f"{API}/{d['id']}/decision", headers=agents["responsable"], json={"issue": "APPROUVE"})
    assert r.status_code == 200
    assert r.json()["decision"]["issue"] == "APPROUVE"
    r = await transition(client, agents, d["id"], "accueil", "DELIVRE")
    assert r.json()["statut"] == "DELIVRE"

    historique = (await client.get(f"{API}/{d['id']}/historique", headers=agents["accueil"])).json()
    assert [e["numero"] for e in historique] == list(range(1, len(historique) + 1))
    assert [e["nouveau_statut"] for e in historique if e["nouveau_statut"]] == [
        "BROUILLON", "SOUMIS", "EN_INSTRUCTION", "EN_ATTENTE_DECISION", "APPROUVE", "DELIVRE"]

    r = await client.post(f"{API}/{d['id']}/annulation", headers=agents["accueil"],
                          json={"motif": "Annulation impossible car terminal"})
    assert r.status_code == 409


async def test_transitions_interdites_et_roles(client, agents):
    """CR09 : transition interdite (409), rôle insuffisant (403), motif obligatoire (422)."""
    d = await creer(client, agents)
    r = await transition(client, agents, d["id"], "accueil", "EN_INSTRUCTION")
    assert r.status_code == 409
    assert r.json() | {"message": ""} == {"code": "TRANSITION_INTERDITE", "message": "", "details": [],
                                          "correlation_id": r.json()["correlation_id"], "statut_courant": "BROUILLON"}
    assert (await transition(client, agents, d["id"], "etat_civil", "SOUMIS")).status_code == 403
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    r = await transition(client, agents, d["id"], "etat_civil", "INCOMPLET")
    assert r.json()["code"] == "MOTIF_OBLIGATOIRE"
    r = await transition(client, agents, d["id"], "etat_civil", "APPROUVE")
    assert r.status_code == 422


async def _jusqu_a_decision(client, agents, instructeur: str = "etat_civil") -> dict:  # noqa: ANN001
    d = await creer(client, agents)
    await declarer_tout(client, agents, d)
    await transition(client, agents, d["id"], "accueil", "SOUMIS")
    await transition(client, agents, d["id"], instructeur, "EN_INSTRUCTION")
    await transition(client, agents, d["id"], instructeur, "EN_ATTENTE_DECISION")
    return d


async def test_regles_de_decision(client, agents):
    d = await _jusqu_a_decision(client, agents)
    r = await client.post(f"{API}/{d['id']}/decision", headers=agents["etat_civil"], json={"issue": "APPROUVE"})
    assert r.status_code == 403
    r = await client.post(f"{API}/{d['id']}/decision", headers=agents["responsable"], json={"issue": "REJETE"})
    assert r.status_code == 422
    assert r.json()["code"] == "MOTIF_OBLIGATOIRE"
    r = await client.post(f"{API}/{d['id']}/decision", headers=agents["responsable"],
                          json={"issue": "REJETE", "motif": "Délai de déclaration dépassé"})
    assert r.status_code == 200
    assert r.json()["statut"] == "REJETE"
    r = await client.post(f"{API}/{d['id']}/decision", headers=agents["responsable"], json={"issue": "APPROUVE"})
    assert r.status_code == 409
    assert r.json()["code"] == "DECISION_EXISTANTE"


async def test_annulation(client, agents):
    d = await creer(client, agents)
    r = await client.post(f"{API}/{d['id']}/annulation", headers=agents["accueil"], json={})
    assert r.json()["code"] == "MOTIF_OBLIGATOIRE"
    r = await client.post(f"{API}/{d['id']}/annulation", headers=agents["etat_civil"],
                          json={"motif": "Demande retirée par le déclarant"})
    assert r.status_code == 403
    r = await client.post(f"{API}/{d['id']}/annulation", headers=agents["accueil"],
                          json={"motif": "Demande retirée par le déclarant"})
    assert r.json()["statut"] == "ANNULE"
    # la clé de doublon est libérée
    assert (await client.post(API, headers=agents["accueil"], json=dossier_deces())).status_code == 201
