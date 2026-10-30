"""Application web Flask : tests de bout en bout contre la vraie API (processus séparé, base SQLite migrée)."""

import os
import re
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from web.app import create_app
from web.formulaires import aplatir, donnees_specifiques

RACINE = Path(__file__).resolve().parent.parent
ADMIN = ("admin", "admin-mot-de-passe-solide")
MDP = "mot-de-passe-web-1234"


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def api_url(tmp_path_factory):  # noqa: ANN001, ANN201
    dossier = tmp_path_factory.mktemp("api")
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{dossier}/web.db", "PIPEDRIVE_API_TOKEN": "",
           "SYNC_WORKER_EMBARQUE": "false", "ADMIN_IDENTIFIANT": ADMIN[0], "ADMIN_MOT_DE_PASSE": ADMIN[1],
           "MODE_DEMO": "true"}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=RACINE, env=env, check=True,
                   capture_output=True)
    port = _port_libre()
    processus = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)], cwd=RACINE,
                                 env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/api/v1"
    for _ in range(100):
        try:
            if httpx.get(f"{url}/sante", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.2)
    else:
        processus.kill()
        pytest.fail("l'API n'a pas démarré")
    jeton = httpx.post(f"{url}/auth/login", json={"identifiant": ADMIN[0], "mot_de_passe": ADMIN[1]}).json()
    entetes = {"Authorization": f"Bearer {jeton['access_token']}"}
    for ident, role in (("accueil", "ACCUEIL"), ("civil", "AGENT_ETAT_CIVIL"), ("certif", "AGENT_CERTIFICATION"),
                        ("chef", "RESPONSABLE")):
        r = httpx.post(f"{url}/utilisateurs", headers=entetes,
                       json={"nom": f"Agent {ident.title()}", "identifiant": ident, "mot_de_passe": MDP, "role": role})
        assert r.status_code == 201, r.text
    yield url
    processus.terminate()
    processus.wait(timeout=10)


@pytest.fixture
def app(api_url, tmp_path):  # noqa: ANN001, ANN201
    return create_app({"API_BASE_URL": api_url, "SESSIONS_DIR": str(tmp_path / "sessions"), "TESTING": True,
                       "SECRET_KEY": "cle-de-test"})


def _csrf(client) -> str:  # noqa: ANN001
    client.get("/connexion")
    with client.session_transaction() as s:
        return s["csrf"]


def poster(client, url: str, donnees: dict | None = None, **kwargs):  # noqa: ANN001, ANN003, ANN201
    return client.post(url, data={"csrf": _csrf(client), **(donnees or {})}, **kwargs)


def connecter(app, identifiant: str, mot_de_passe: str = MDP):  # noqa: ANN001, ANN201
    client = app.test_client()
    r = poster(client, "/connexion", {"identifiant": identifiant, "mot_de_passe": mot_de_passe})
    assert r.status_code == 302, r.get_data(as_text=True)
    return client


def texte(r) -> str:  # noqa: ANN001
    return r.get_data(as_text=True)


def deces(nom: str, **extra: str) -> dict:  # noqa: ANN003
    return {
        "type": "DECES", "objet": "Établissement de l'acte de décès",
        "demandeur.nom": "Mballa", "demandeur.prenom": "Jean", "demandeur.telephone": "690000000",
        "donnees_specifiques.defunt.nom": nom, "donnees_specifiques.defunt.prenom": "Etienne",
        "donnees_specifiques.date_deces": (date.today() - timedelta(days=3)).isoformat(),
        "donnees_specifiques.lieu_deces": "Yaoundé", "donnees_specifiques.lien_declarant": "Fils", **extra,
    }


def creer_dossier(client, nom: str) -> str:  # noqa: ANN001
    r = poster(client, "/dossiers/nouveau?type=DECES", deces(nom))
    assert r.status_code == 302, texte(r)
    return re.search(r"/dossiers/([0-9a-f-]{36})", r.headers["Location"]).group(1)


# --- UC01 Connexion et sécurité --------------------------------------------------------------------------

def test_connexion_refusee_puis_acceptee(app):
    client = app.test_client()
    assert client.get("/").status_code == 302
    r = poster(client, "/connexion", {"identifiant": "accueil", "mot_de_passe": "faux"})
    assert r.status_code == 200 and "Identifiant ou mot de passe incorrect" in texte(r)
    r = poster(client, "/connexion", {"identifiant": "accueil", "mot_de_passe": MDP}, follow_redirects=True)
    assert "Bonjour, Agent" in texte(r) and "Ma file de travail" in texte(r)


def test_jeton_jamais_envoye_au_navigateur(app):
    client = connecter(app, "accueil")
    with client.session_transaction() as s:
        assert set(s) <= {"csrf", "sid", "_flashes"}
        assert "access_token" not in str(dict(s))


def test_csrf_obligatoire(app):
    client = connecter(app, "accueil")
    r = client.post("/dossiers/nouveau?type=DECES", data=deces("Sans-Jeton"))
    assert r.status_code == 400 and "Jeton de sécurité invalide" in texte(r)


def test_redirection_ouverte_bloquee(app):
    client = app.test_client()
    r = poster(client, "/connexion?suivant=https://exemple.org", {"identifiant": "accueil", "mot_de_passe": MDP})
    assert r.headers["Location"] == "/"


def test_session_expiree_renvoie_a_la_connexion(app):
    client = connecter(app, "accueil")
    with client.session_transaction() as s:
        sid = s["sid"]
    app.extensions["stockage_sessions"].supprimer(sid)
    r = client.get("/dossiers/")
    assert r.status_code == 302 and "/connexion" in r.headers["Location"]


def test_deconnexion(app):
    client = connecter(app, "accueil")
    assert poster(client, "/deconnexion").status_code == 302
    assert client.get("/").status_code == 302


# --- UC03 Création, validation, doublon ------------------------------------------------------------------

def test_formulaire_erreurs_par_champ(app):
    client = connecter(app, "accueil")
    r = poster(client, "/dossiers/nouveau?type=DECES", deces("Erreur", **{"demandeur.telephone": "12"}))
    page = texte(r)
    assert r.status_code == 200
    assert 'id="demandeur.telephone-err"' in page and "+237" in page
    assert 'value="Erreur"' in page  # la saisie est conservée


def test_doublon_puis_confirmation(app):
    client = connecter(app, "accueil")
    creer_dossier(client, "Doublon")
    r = poster(client, "/dossiers/nouveau?type=DECES", deces("Doublon"))
    assert "Un dossier ouvert existe déjà" in texte(r)
    r = poster(client, "/dossiers/nouveau?type=DECES", deces("Doublon", confirmer_doublon="1"))
    assert "obligatoire" in texte(r)
    r = poster(client, "/dossiers/nouveau?type=DECES",
               deces("Doublon", confirmer_doublon="1", motif_doublon="Premier dossier saisi avec erreur"))
    assert r.status_code == 302


def test_formulaire_mariage_et_temoins():
    futur = (date.today() + timedelta(days=30)).isoformat()
    f = {"donnees_specifiques.epoux_1.nom": "Ngo", "donnees_specifiques.epoux_1.prenom": "Clarisse",
         "donnees_specifiques.epoux_2.nom": "Essomba", "donnees_specifiques.epoux_2.prenom": "Paul",
         "donnees_specifiques.date_celebration_prevue": futur,
         "donnees_specifiques.temoins.0.nom": "Abena", "donnees_specifiques.temoins.0.prenom": "Luc",
         "donnees_specifiques.temoins.1.nom": "Manga", "donnees_specifiques.temoins.1.prenom": "Rose",
         "donnees_specifiques.temoins.2.nom": "", "donnees_specifiques.temoins.2.prenom": ""}
    d = donnees_specifiques("MARIAGE", f)
    assert d["temoins"] == [{"nom": "Abena", "prenom": "Luc"}, {"nom": "Manga", "prenom": "Rose"}]
    assert aplatir(d)["donnees_specifiques.temoins.1.prenom"] == "Rose"
    assert donnees_specifiques("COPIE_ACTE", {"donnees_specifiques.annee": "2015"}) == {"annee": 2015}


def test_cinq_demarches_creables(app):
    client = connecter(app, "accueil")
    for code in ("DECES", "MARIAGE", "COPIE_ACTE", "LEGALISATION", "CERTIFICATION_CONFORME"):
        r = client.get(f"/dossiers/nouveau?type={code}")
        assert r.status_code == 200 and 'name="donnees_specifiques.' in texte(r)
    r = poster(client, "/dossiers/nouveau?type=CERTIFICATION_CONFORME", {
        "type": "CERTIFICATION_CONFORME", "objet": "Certification de diplôme",
        "demandeur.nom": "Essomba", "demandeur.prenom": "Rose", "demandeur.email": "rose@example.cm",
        "donnees_specifiques.intitule_document": "Diplôme de licence", "donnees_specifiques.nombre_copies": "2"})
    assert r.status_code == 302


# --- Parcours complet (CR08) -------------------------------------------------------------------------------

def test_parcours_complet_par_l_interface(app):
    accueil = connecter(app, "accueil")
    dossier_id = creer_dossier(accueil, "Parcours")
    page = texte(accueil.get(f"/dossiers/{dossier_id}?onglet=pieces"))
    assert "Brouillon" in page and "Soumettre le dossier" in page
    for code in ("CERTIFICAT_DECES", "IDENTITE_DEFUNT", "IDENTITE_DECLARANT"):
        r = poster(accueil, f"/dossiers/{dossier_id}/pieces", {"code_piece": code, "etat": "CONFORME"})
        assert r.status_code == 302
    assert "Dossier complet" in texte(accueil.get(f"/dossiers/{dossier_id}?onglet=pieces"))
    poster(accueil, f"/dossiers/{dossier_id}/transition", {"cible": "SOUMIS"})

    civil = connecter(app, "civil")
    r = poster(civil, f"/dossiers/{dossier_id}/verification", follow_redirects=True)
    assert "Dossier complet" in texte(r)
    poster(civil, f"/dossiers/{dossier_id}/transition", {"cible": "EN_INSTRUCTION"})
    r = poster(civil, f"/dossiers/{dossier_id}/transition", {"cible": "EN_ATTENTE_DECISION"}, follow_redirects=True)
    assert "Attente décision" in texte(r)

    chef = connecter(app, "chef")
    assert "Décider" in texte(chef.get(f"/dossiers/{dossier_id}"))
    r = poster(chef, f"/dossiers/{dossier_id}/decision", {"issue": "REJETE", "motif": ""})
    assert 'id="motif-err"' in texte(r)
    r = poster(chef, f"/dossiers/{dossier_id}/decision", {"issue": "APPROUVE"}, follow_redirects=True)
    assert "Décision enregistrée : Approuvé" in texte(r)

    r = poster(accueil, f"/dossiers/{dossier_id}/transition", {"cible": "DELIVRE"}, follow_redirects=True)
    assert "Délivré" in texte(r)
    historique = texte(accueil.get(f"/dossiers/{dossier_id}?onglet=historique"))
    assert "E1" in historique and "Agent Chef" in historique and "Décision" in historique
    pipedrive = texte(accueil.get(f"/dossiers/{dossier_id}?onglet=pipedrive"))
    assert "Objets synchronisés" in pipedrive and "hx-get" in pipedrive
    partiel = accueil.get(f"/dossiers/{dossier_id}/activites", headers={"HX-Request": "true"})
    assert "pas encore présent dans Pipedrive" in texte(partiel) and "<html" not in texte(partiel)


def test_blocage_incomplet_avec_motif(app):
    accueil = connecter(app, "accueil")
    dossier_id = creer_dossier(accueil, "Incomplet")
    poster(accueil, f"/dossiers/{dossier_id}/transition", {"cible": "SOUMIS"})
    civil = connecter(app, "civil")
    r = poster(civil, f"/dossiers/{dossier_id}/transition", {"cible": "EN_INSTRUCTION"}, follow_redirects=True)
    assert "Toutes les pièces requises" in texte(r)
    r = poster(civil, f"/dossiers/{dossier_id}/verification", follow_redirects=True)
    assert "Pièces manquantes" in texte(r) and "Incomplet" in texte(r)


def test_modification_et_annulation(app):
    accueil = connecter(app, "accueil")
    dossier_id = creer_dossier(accueil, "Modifiable")
    page = texte(accueil.get(f"/dossiers/{dossier_id}/modifier"))
    assert 'value="Modifiable"' in page
    r = poster(accueil, f"/dossiers/{dossier_id}/modifier", deces("Modifiable", objet="Objet corrigé"),
               follow_redirects=True)
    assert "Brouillon mis à jour" in texte(r) and "Objet corrigé" in texte(r)
    r = poster(accueil, f"/dossiers/{dossier_id}/annulation", {"motif": ""})
    assert 'id="motif-err"' in texte(r)
    r = poster(accueil, f"/dossiers/{dossier_id}/annulation", {"motif": "Demande retirée par le déclarant"},
               follow_redirects=True)
    assert "Dossier annulé" in texte(r)


# --- Rôles et périmètre -------------------------------------------------------------------------------------

def test_droits_par_role(app):
    accueil = connecter(app, "accueil")
    dossier_id = creer_dossier(accueil, "Perimetre")
    civil = connecter(app, "civil")
    r = civil.get("/dossiers/nouveau", follow_redirects=True)
    assert "droits nécessaires" in texte(r)
    assert civil.get("/admin/utilisateurs").status_code == 302
    certif = connecter(app, "certif")
    r = certif.get(f"/dossiers/{dossier_id}")
    assert r.status_code == 404 and "périmètre" in texte(r)


def test_liste_et_filtres(app):
    accueil = connecter(app, "accueil")
    creer_dossier(accueil, "Filtrable")
    r = accueil.get("/dossiers/?statut=BROUILLON&demandeur=Mballa")
    assert r.status_code == 200 and "ACT-" in texte(r)
    r = accueil.get("/dossiers/?cree_du=pas-une-date")
    assert "Filtre invalide" in texte(r)


# --- Administration (UC02, UC15, UC16, UC17) -------------------------------------------------------------

def test_administration(app):
    admin = connecter(app, *ADMIN)
    r = poster(admin, "/admin/utilisateurs", {"nom": "Nouvel Agent", "identifiant": "nouvel.agent",
                                               "mot_de_passe": "court", "role": "ACCUEIL", "categorie": ""})
    assert 'id="mot_de_passe-err"' in texte(r)
    r = poster(admin, "/admin/utilisateurs", {"nom": "Nouvel Agent", "identifiant": "nouvel.agent",
                                               "mot_de_passe": MDP, "role": "ACCUEIL", "categorie": ""},
               follow_redirects=True)
    assert "Compte « nouvel.agent » créé" in texte(r)

    page = texte(admin.get("/admin/demarches"))
    assert "Acte de décès" in page
    piece = {"code": "ACTE_NAISSANCE_DEFUNT", "libelle": "Acte de naissance du défunt", "obligatoire": "true"}
    r = poster(admin, "/admin/demarches/DECES/pieces", piece, follow_redirects=True)
    assert "Pièce requise ajoutée" in texte(r)

    page = texte(admin.get("/admin/synchronisations"))
    assert "Non configuré" in page and "Synchronisations" in page
    r = poster(admin, "/admin/synchronisations/relance-globale", follow_redirects=True)
    assert "relancée(s)" in texte(r)
    r = admin.get("/admin/journaux?operation=AUTH_CONNEXION")
    assert r.status_code == 200 and "AUTH_CONNEXION" in texte(r)
    assert "Intégration Pipedrive" in texte(admin.get("/"))


def test_api_injoignable(tmp_path):
    app = create_app({"API_BASE_URL": f"http://127.0.0.1:{_port_libre()}/api/v1", "TESTING": True,
                      "SESSIONS_DIR": str(tmp_path), "SECRET_KEY": "x"})
    client = app.test_client()
    r = poster(client, "/connexion", {"identifiant": "a", "mot_de_passe": "b"})
    assert "injoignable" in texte(r)
    assert client.get("/sante").status_code == 503


def test_jeton_csrf_present_dans_les_formulaires(app):
    """Le jeton réellement inclus dans la page doit être accepté (pas seulement celui de la session)."""
    client = app.test_client()
    page = texte(client.get("/connexion"))
    jeton = re.search(r'name="csrf" value="([^"]+)"', page).group(1)
    r = client.post("/connexion", data={"csrf": jeton, "identifiant": "accueil", "mot_de_passe": MDP})
    assert r.status_code == 302
    page = texte(client.get("/dossiers/nouveau?type=DECES"))
    with client.session_transaction() as s:
        jeton_session = s["csrf"]
    assert jeton_session != jeton  # session régénérée à la connexion
    assert set(re.findall(r'name="csrf" value="([^"]*)"', page)) == {jeton_session}
    assert f'"X-CSRF-Token": "{jeton_session}"' in page


def test_resume_dates_au_format_francais():
    from web.formulaires import lignes_resume

    lignes = dict(lignes_resume("DECES", {"date_deces": "2026-10-24", "lieu_deces": "Yaoundé"}))
    assert lignes["Date du décès"] == "24/10/2026"


def test_justification_de_doublon_trop_courte(app):
    client = connecter(app, "accueil")
    creer_dossier(client, "Courte")
    r = poster(client, "/dossiers/nouveau?type=DECES", deces("Courte"))
    reference = re.search(r'name="reference_doublon" value="([^"]+)"', texte(r)).group(1)
    r = poster(client, "/dossiers/nouveau?type=DECES",
               deces("Courte", confirmer_doublon="1", motif_doublon="erreur", reference_doublon=reference))
    page = texte(r)
    assert "Un dossier ouvert existe déjà" in page
    assert 'id="motif_doublon-err"' in page and "Au moins 10 caractères." in page


def test_messages_de_validation_en_francais(app):
    admin = connecter(app, *ADMIN)
    r = poster(admin, "/admin/utilisateurs", {"nom": "X Y", "identifiant": "court.mdp", "mot_de_passe": "court",
                                               "role": "ACCUEIL", "categorie": ""})
    assert "Au moins 12 caractères." in texte(r)


def test_page_reinitialisation_demo(app):  # noqa: ANN001
    admin = connecter(app, *ADMIN)
    assert "Réinitialiser la démo" in texte(admin.get("/"))
    page = texte(admin.get("/admin/demo"))
    assert "Pipedrive n'est pas configuré" in page and 'name="confirmation"' in page
    # Une confirmation erronée n'efface rien (la réinitialisation elle-même est couverte par tests/test_demo.py).
    r = poster(admin, "/admin/demo", {"confirmation": "oui"})
    assert r.status_code == 200 and "Saisissez exactement" in texte(r)
    assert "Réinitialiser la démo" not in texte(connecter(app, "chef").get("/"))
    assert connecter(app, "chef").get("/admin/demo").status_code == 302
