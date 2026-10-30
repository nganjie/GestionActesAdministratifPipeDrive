# API intermédiaire — actes administratifs / Pipedrive

API REST (FastAPI) qui orchestre la gestion des actes administratifs d'une mairie et les échanges avec
Pipedrive, et application web (Flask) utilisée par les agents. Projet académique ENSPD — Niveau 5 ·
Architecture Logicielle & Objets répartis.

```
Navigateur ──▶ Application web Flask (port 5000) ──▶ API FastAPI (port 8000) ──▶ Pipedrive
               pages HTML, session serveur          règles métier, base, worker
```

Références : [cahier des charges v3.0](docs/), [FRS v3.0](docs/FRS_Gestion_Actes_Administratifs_Pipedrive_v3.0.pdf),
[ISD-001 v2.1](docs/ISD-001_Pipedrive_v2.1.pdf).

## Principes

- **Le module métier est la source de vérité** (CDC RG03, RG11). Pipedrive reçoit une projection minimale :
  le contact du demandeur (Person), le dossier (Deal dans un pipeline miroir) et les actions de suivi (Activities).
- **Aucun fichier n'est transmis** (RG10) : les pièces sont déclarées au guichet.
- **Synchronisation asynchrone** par file transactionnelle (outbox) : une panne de Pipedrive ne bloque jamais
  le travail des agents ; chaque réponse indique l'état `SYNCHRONISE`, `EN_ATTENTE` ou `ECHEC`.
- **Idempotence** : une seule activité par événement (RM06) ; après un résultat indéterminé (timeout), l'objet
  est recherché dans Pipedrive avant toute nouvelle création.
- **Minimisation** : seuls nom, téléphone et e-mail du demandeur quittent la mairie.

## Architecture

```
app/
├── api/v1/            routes REST (auth, dossiers, démarches, synchronisations, journaux, santé)
├── core/              configuration, erreurs (format unique), journalisation, sécurité (argon2, JWT)
├── domain/            statuts, machine à états (FRS §4.2), projection vers Pipedrive (FRS §4.3)
├── demarches/         registre des 5 démarches : schéma, pièces, clé de doublon (EF17)
├── services/          cas d'utilisation (UC01 à UC17)
├── integrations/
│   └── pipedrive/     client HTTP, adaptateur OP-01 à OP-16, mappers (minimisation)
├── workers/           worker de synchronisation (outbox, relances, idempotence)
├── scripts/           initialisation de Pipedrive (pipeline, étapes, types d'activités)
└── db/                modèle SQLAlchemy (AF §10)
web/                   application web des agents (Flask + Jinja + htmx), cliente de l'API
├── routes/            connexion, tableau de bord, dossiers, administration
├── templates/         pages (charte de la maquette)
└── api.py             client de l'API (renouvellement de session, erreurs par champ)
alembic/               migrations PostgreSQL
tests/                 tests de l'API (faux Pipedrive) et tests de bout en bout de l'application web
```

## Démarrage rapide

### Avec Docker

```bash
cp .env.example .env
```

Renseigner au minimum `JWT_SECRET`, `ADMIN_MOT_DE_PASSE` et `PIPEDRIVE_API_TOKEN` dans `.env`, puis :

```bash
docker compose up --build
```

L'API écoute sur http://localhost:8000 ; la documentation OpenAPI est sur http://localhost:8000/docs.
Le service `worker` exécute la synchronisation.

### En local (uv + PostgreSQL)

```bash
uv sync
```

```bash
cp .env.example .env
```

```bash
uv run alembic upgrade head
```

```bash
uv run uvicorn app.main:app --reload
```

Dans un second terminal :

```bash
uv run python -m app.workers.sync_worker
```

Pour une démonstration en un seul processus, `SYNC_WORKER_EMBARQUE=true` lance le worker dans l'API.

Dans un troisième terminal, l'application web des agents :

```bash
uv run flask --app web.app run --port 5000
```

Puis ouvrir http://127.0.0.1:5000 et se connecter avec `ADMIN_IDENTIFIANT` / `ADMIN_MOT_DE_PASSE`.

### Initialiser Pipedrive

Vérifie le jeton, les types d'activités (`task`, `call`, `deadline`) et crée le pipeline « Actes administratifs »
et ses 6 étapes s'ils n'existent pas (le worker le fait aussi automatiquement au premier besoin) :

```bash
uv run python -m app.scripts.init_pipedrive
```

Un compte sandbox développeur Pipedrive est recommandé (ISD §9).

## Tests

```bash
uv run pytest
```

Sur PostgreSQL (comme la CI) :

```bash
TEST_DATABASE_URL=postgresql+asyncpg://actes:actes@localhost:5432/actes_test uv run pytest
```

```bash
uv run ruff check .
```

Les tests de synchronisation remplacent Pipedrive par un faux serveur en mémoire et couvrent les scénarios de
l'ISD §10 : jeton refusé (T02), réutilisation de contact (T04), indisponibilité et relances (T06), timeout après
création sans doublon (T07), `Retry-After` (T08), deal supprimé puis recréé (T11), rejeu sans doublon (T12),
minimisation (T13), journaux sans secret (T14), route retirée (T15), pagination (T16), types d'activités (T17).

## Endpoints principaux

Tous préfixés par `/api/v1`, protégés par `Authorization: Bearer <jeton>` sauf `/auth/login`, `/auth/refresh`
et `/sante`.

| Méthode et route | Cas d'utilisation |
|---|---|
| `POST /auth/login`, `/auth/refresh`, `/auth/logout`, `GET /auth/me` | UC01 |
| `GET/POST /utilisateurs`, `PATCH /utilisateurs/{id}` | UC02 (admin) |
| `POST /dossiers`, `GET /dossiers`, `GET/PATCH /dossiers/{id}` | UC03 à UC06 |
| `GET/POST /dossiers/{id}/pieces`, `PATCH /dossiers/{id}/pieces/{piece_id}` | UC07 |
| `POST /dossiers/{id}/verification-completude` | UC08 |
| `POST /dossiers/{id}/transitions` | UC09 |
| `POST /dossiers/{id}/decision` | UC10 |
| `GET /dossiers/{id}/historique` | UC11 |
| `POST /dossiers/{id}/annulation` | UC12 |
| `GET /dossiers/{id}/synchronisation`, `GET /dossiers/{id}/activites` | UC04, UC13, UC14 |
| `GET /synchronisations`, `POST /synchronisations/{id}/relance`, `POST /synchronisations/relance-globale` | UC15 |
| `GET /demarches`, `PATCH /admin/demarches/{code}`, `POST/PATCH /admin/demarches/{code}/pieces` | UC16 |
| `GET /admin/journaux`, `GET /admin/sante/pipedrive`, `GET /sante` | UC17 |

Format d'erreur unique (FRS §7.2) :

```json
{"code": "TRANSITION_INTERDITE", "message": "…", "details": [], "correlation_id": "…", "statut_courant": "BROUILLON"}
```

## Scénario de démonstration (CR08)

1. L'administrateur crée les comptes `ACCUEIL`, `AGENT_ETAT_CIVIL` et `RESPONSABLE` (`POST /utilisateurs`).
2. L'accueil crée un dossier de décès (`POST /dossiers`) et déclare les 3 pièces.
3. L'accueil soumet (`transitions` → `SOUMIS`) : le contact et le deal apparaissent dans Pipedrive.
4. L'agent d'état civil vérifie la complétude, instruit, termine l'instruction.
5. Le responsable approuve (`/decision`), l'accueil délivre (`DELIVRE`) : le deal passe à « gagné » et les
   activités sont closes.
6. `/dossiers/{id}/historique` et `/dossiers/{id}/synchronisation` montrent la traçabilité (CR07).

## Limites connues

- Les contrats de l'API Pipedrive v2 sont établis d'après la documentation publique : ils restent à confirmer
  par les tests de contrat sur un compte sandbox (ISD point P9).
- Le choix de Python/FastAPI à la place de Spring Boot (CDC §7.3) doit être validé par l'encadrant (P8).
- Les pièces requises par démarche sont des hypothèses de travail, modifiables par l'administrateur (P2).

## Application web des agents

| Écran | Rôles | Cas d'utilisation |
|---|---|---|
| Connexion, déconnexion, renouvellement automatique de session | tous | UC01 |
| Tableau de bord : file de travail du rôle, répartition par statut, état de Pipedrive (admin) | tous | — |
| Liste des dossiers : filtres (statut, démarche, catégorie, référence, demandeur, dates), pagination | tous | UC05 |
| Nouveau dossier : formulaire propre à chaque démarche, erreurs par champ, alerte de doublon | accueil | UC03 |
| Fiche du dossier : frise du cycle de vie, actions permises au rôle, onglets résumé, pièces, historique, Pipedrive | tous | UC04, UC11 |
| Modification du brouillon | accueil | UC06 |
| Déclaration et mise à jour des pièces, vérification de complétude | accueil, instructeurs | UC07, UC08 |
| Soumission, blocage motivé, instruction, délivrance | selon le rôle | UC09 |
| Décision (approbation ou rejet motivé) | responsable | UC10 |
| Annulation motivée | accueil, responsable | UC12 |
| Comptes et rôles | admin | UC02 |
| Démarches et pièces requises | admin | UC16 |
| Synchronisation Pipedrive : santé, liste, relances | admin | UC13 à UC15 |
| Journaux techniques | admin | UC17 |

Sécurité : les jetons de l'API restent côté serveur (le navigateur ne reçoit qu'un identifiant de session),
protection CSRF sur tous les formulaires, cookies `HttpOnly` et `SameSite=Lax`, redirections internes uniquement.
