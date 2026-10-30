"""UC01, UC02 : authentification, rôles, comptes."""

from tests.conftest import MOTS_DE_PASSE, jetons


async def test_connexion_et_profil(client, agents):
    r = await client.get("/api/v1/auth/me", headers=agents["accueil"])
    assert r.status_code == 200
    assert r.json()["role"] == "ACCUEIL"


async def test_identifiants_invalides_sans_preciser_le_champ(client, agents):
    r = await client.post("/api/v1/auth/login", json={"identifiant": "accueil", "mot_de_passe": "faux"})
    assert r.status_code == 401
    corps = r.json()
    assert corps["code"] == "NON_AUTHENTIFIE"
    assert corps["correlation_id"]
    r2 = await client.post("/api/v1/auth/login", json={"identifiant": "inconnu", "mot_de_passe": "faux"})
    assert r2.json()["message"] == corps["message"]


async def test_blocage_apres_cinq_echecs(client, agents):
    for _ in range(4):
        r = await client.post("/api/v1/auth/login", json={"identifiant": "accueil", "mot_de_passe": "faux"})
        assert r.status_code == 401
    r = await client.post("/api/v1/auth/login", json={"identifiant": "accueil", "mot_de_passe": "faux"})
    assert r.status_code == 429
    r = await client.post("/api/v1/auth/login", json={"identifiant": "accueil", "mot_de_passe": MOTS_DE_PASSE})
    assert r.status_code == 429


async def test_jeton_absent_ou_invalide(client, db):
    assert (await client.get("/api/v1/dossiers")).status_code == 401
    r = await client.get("/api/v1/dossiers", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 401
    assert r.json()["code"] == "NON_AUTHENTIFIE"


async def test_rafraichissement_a_usage_unique(client, agents):
    r = await client.post("/api/v1/auth/login", json={"identifiant": "accueil", "mot_de_passe": MOTS_DE_PASSE})
    refresh = r.json()["refresh_token"]
    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r2.status_code == 401


async def test_deconnexion_revoque_le_jeton(client, agents):
    entetes = await jetons(client, "accueil")
    assert (await client.post("/api/v1/auth/logout", headers=entetes)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=entetes)).status_code == 401


async def test_gestion_des_comptes_reservee_admin(client, agents):
    r = await client.get("/api/v1/utilisateurs", headers=agents["responsable"])
    assert r.status_code == 403
    r = await client.post("/api/v1/utilisateurs", headers=agents["admin"], json={
        "nom": "Doublon", "identifiant": "accueil", "mot_de_passe": MOTS_DE_PASSE, "role": "ACCUEIL",
    })
    assert r.status_code == 409


async def test_compte_desactive_ne_peut_plus_se_connecter(client, agents):
    comptes = (await client.get("/api/v1/utilisateurs", headers=agents["admin"])).json()
    accueil = next(c for c in comptes if c["identifiant"] == "accueil")
    r = await client.patch(f"/api/v1/utilisateurs/{accueil['id']}", headers=agents["admin"], json={"actif": False})
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/login", json={"identifiant": "accueil", "mot_de_passe": MOTS_DE_PASSE})
    assert r.status_code == 401


async def test_admin_ne_se_desactive_pas(client, agents):
    moi = (await client.get("/api/v1/auth/me", headers=agents["admin"])).json()
    r = await client.patch(f"/api/v1/utilisateurs/{moi['id']}", headers=agents["admin"], json={"actif": False})
    assert r.status_code == 422


async def test_sante_publique(client, db):
    r = await client.get("/api/v1/sante")
    assert r.status_code == 200
    assert r.headers["X-Correlation-Id"]


async def test_racine_redirige_vers_la_documentation(client, db):
    r = await client.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/docs"
