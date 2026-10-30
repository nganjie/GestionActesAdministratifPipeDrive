# Scénario de test complet — application web des agents

Ce document décrit, étape par étape, **qui se connecte**, **quelle page ouvrir**, **quoi saisir** et **ce qui doit
s'afficher**. Il couvre tous les cas d'utilisation (UC01 à UC17) et les critères de réception CR02, CR05, CR07, CR08
et CR09.

> Important : l'application ne reçoit **aucun fichier**. Les pièces (certificat, carte d'identité…) sont présentées
> au guichet et seulement **déclarées** dans l'application (cahier des charges RG10). Il n'y a donc pas de zone de
> dépôt : « déposer un dossier » veut dire **créer le dossier**, puis **déclarer ses pièces**.

---

## 0. Avant de commencer

Trois programmes doivent tourner, chacun dans son terminal, depuis le dossier du projet :

| Terminal | Commande | Rôle |
|---|---|---|
| 1 | `uv run uvicorn app.main:app --reload` | API (port 8000) |
| 2 | `uv run python -m app.workers.sync_worker` | Synchronisation Pipedrive |
| 3 | `uv run flask --app web.app run --port 5000` | Application web (port 5000) |

Ouvrir l'application : **http://127.0.0.1:5000**

Astuce : pour passer d'un rôle à l'autre sans vous déconnecter, ouvrez une **fenêtre de navigation privée** par
utilisateur (ou plusieurs navigateurs).

---

## 1. Les rôles et ce qu'ils peuvent faire

| Rôle | Ce qu'il fait | Menu visible |
|---|---|---|
| **Administrateur** | Crée les comptes, configure les démarches, surveille Pipedrive et les journaux. **Ne crée pas de dossier.** | Tableau de bord, Dossiers, Administration |
| **Agent d'accueil** | **Crée les dossiers**, déclare les pièces, soumet, enregistre la délivrance, annule | Tableau de bord, Dossiers, **Nouveau dossier** |
| **Agent d'état civil** | Instruit les dossiers *mariage, décès, copie d'acte* | Tableau de bord, Dossiers |
| **Agent de certification** | Instruit les dossiers *légalisation, certification conforme* | Tableau de bord, Dossiers |
| **Responsable** | Approuve ou rejette les dossiers, peut annuler | Tableau de bord, Dossiers |

---

## 2. Étape préalable — créer les comptes (administrateur)

1. Se connecter avec `admin` et le mot de passe `ADMIN_MOT_DE_PASSE` de votre fichier `.env`.
2. Menu **Administration → Comptes et rôles**.
3. Dans le formulaire **Créer un compte** (à droite), créer les 5 comptes suivants (« Catégorie » : laisser
   *Déduite du rôle*) :

| Nom complet | Identifiant | Mot de passe | Rôle |
|---|---|---|---|
| Léa Abena | `accueil` | `MotDePasse-Accueil1` | Agent d'accueil |
| Awa Ndzana | `civil` | `MotDePasse-Civil1` | Agent d'état civil |
| Eric Kamga | `certif` | `MotDePasse-Certif1` | Agent de certification |
| Paul Manga | `chef` | `MotDePasse-Chef1` | Officier / responsable |
| Rose Essomba | `chef2` | `MotDePasse-Chef2` | Officier / responsable |

**Résultat attendu** : message vert « Compte « accueil » créé. », le compte apparaît dans la liste.

**Test d'erreur** : créer un compte avec le mot de passe `court` → le champ est entouré de rouge avec le message
« Au moins 12 caractères. ».

---

## 3. Scénario A — parcours complet d'un acte de décès (CR08)

### A1. Créer le dossier — `accueil`

1. Se connecter avec `accueil` / `MotDePasse-Accueil1`.
2. Menu **Nouveau dossier** → choisir la carte **Acte de décès**.
3. Remplir :

| Champ | Valeur |
|---|---|
| Nom | `Mballa` |
| Prénom | `Jean` |
| Téléphone | `690000000` (l'application le transforme en `+237690000000`) |
| Objet de la demande | `Établissement de l'acte de décès` |
| Nom du défunt | `Mballa` |
| Prénom du défunt | `Etienne` |
| Date de naissance du défunt | `12/03/1948` |
| Date du décès | une date **passée** (ex. il y a 3 jours) |
| Lieu du décès | `Yaoundé` |
| Lien du déclarant | `Fils` |

4. Cliquer **Créer le brouillon**.

**Résultat attendu** : message vert « Dossier ACT-2026-00000X créé en brouillon… », ouverture de la fiche du
dossier sur l'onglet **Pièces**, statut **Brouillon**.

### A2. Déclarer les pièces — `accueil`

1. Onglet **Pièces** : trois lignes (Certificat de décès, Pièce d'identité du défunt, Pièce d'identité du déclarant).
2. Sur chaque ligne : laisser la date du jour et l'état **Conforme**, cliquer **Déclarer**.

**Résultat attendu** : bandeau vert « Dossier complet : toutes les pièces obligatoires sont conformes ».

### A3. Soumettre — `accueil`

1. En haut à droite de la fiche : bouton **Soumettre le dossier**.

**Résultat attendu** : statut **Soumis**, la frise affiche « Brouillon ✓ → Soumis ». Le dossier n'est plus modifiable
(le bouton **Modifier** a disparu).

### A4. Instruire — `civil`

1. Se connecter avec `civil` / `MotDePasse-Civil1` (fenêtre privée).
2. Le **Tableau de bord** affiche le dossier dans **Ma file de travail** → cliquer sa référence.
3. Cliquer **Vérifier la complétude** → message « Dossier complet… vous pouvez passer en instruction ».
4. Cliquer **Passer en instruction** → statut **En instruction**, « instruit par Awa Ndzana ».
5. Cliquer **Terminer l'instruction** → statut **Attente décision**.

### A5. Décider — `chef`

1. Se connecter avec `chef` / `MotDePasse-Chef1`.
2. Tableau de bord → **Ma file de travail** → ouvrir le dossier → bouton **Décider**.
3. Choisir **Approuver** → **Enregistrer la décision**.

**Résultat attendu** : « Décision enregistrée : Approuvé ». Dans l'onglet **Résumé**, encadré vert
« Décision : Approuvé … par Paul Manga ».

### A6. Délivrer — `accueil`

1. Revenir sur la fenêtre `accueil`, ouvrir le dossier (Tableau de bord → Ma file de travail).
2. Cliquer **Enregistrer la délivrance**.

**Résultat attendu** : statut **Délivré** (pastille verte pleine), la frise est entièrement cochée.

### A7. Vérifier la traçabilité (CR07)

1. Onglet **Historique** : les événements E1 à E9 dans l'ordre (création, 3 pièces, soumission, instruction,
   fin d'instruction, décision, délivrance) avec date et auteur. Aucune entrée n'est modifiable.
2. Onglet **Pipedrive** : la liste des objets synchronisés (contact, deal, étapes, activités) et leur état.
   - Sans jeton Pipedrive : état **En échec** avec le code `PIPEDRIVE_NON_CONFIGURE` (normal).
   - Avec jeton : état **Synchronisé** et les activités Pipedrive s'affichent (voir scénario H).

---

## 4. Scénario B — erreurs de saisie et doublon (CR02, RM02)

Connecté en `accueil`, menu **Nouveau dossier → Acte de décès** :

| Action | Résultat attendu |
|---|---|
| Téléphone `12`, puis **Créer le brouillon** | Bandeau rouge + champ Téléphone en rouge « format attendu : +237 suivi de 9 chiffres ». Les autres champs restent remplis. |
| Date du décès dans le futur | Message sous « Date du décès » : « la date ne peut pas être dans le futur ». |
| Ni téléphone ni e-mail | Message « le téléphone ou l'e-mail est obligatoire ». |
| Ressaisir **exactement** le défunt du scénario A (Mballa Etienne, même date de décès) alors que le dossier A est encore ouvert | Encadré orange « Un dossier ouvert existe déjà… » avec le lien vers le dossier existant. |
| Cocher « Créer quand même » sans justification | Message « obligatoire » sous **Justification**. |
| Cocher + justification trop courte (`erreur`) | Message « Au moins 10 caractères. » sous **Justification** ; l'encadré reste affiché. |
| Cocher + justification de 10 caractères minimum | Dossier créé (le doublon est tracé dans l'historique). |

La carte **Acte de naissance** est grisée : « Hors périmètre de la version 1 » (RM08).

---

## 5. Scénario C — dossier incomplet puis complété (UC08, RM03)

1. `accueil` : créer un dossier de décès (autre défunt, ex. `Ngono Marie`), **ne déclarer qu'une seule pièce**,
   puis **Soumettre le dossier**.
2. `civil` : ouvrir le dossier → **Passer en instruction**.
   - **Attendu** : bandeau rouge « Toutes les pièces requises doivent être présentes et conformes ».
3. `civil` : **Vérifier la complétude**.
   - **Attendu** : bandeau orange « Pièces manquantes ou à corriger : … » et statut **Incomplet**
     (une activité « Relancer le demandeur » est programmée dans Pipedrive).
4. `accueil` : onglet **Pièces** → déclarer les pièces manquantes.
5. `civil` : **Vérifier la complétude** → « Dossier complet », puis **Passer en instruction** → **En instruction**.

Variante « blocage manuel » : sur un dossier **Soumis**, `civil` peut ouvrir le volet **Bloquer : pièces à
compléter**, saisir un motif (10 caractères minimum) et **Confirmer** → statut **Incomplet**.

Variante « pièce à corriger » : onglet **Pièces** → **Modifier** sur une pièce → état **À corriger** → elle redevient
manquante.

---

## 6. Scénario D — rejet motivé (UC10, RM05)

1. Amener un nouveau dossier jusqu'à **Attente décision** (étapes A1 à A4).
2. `chef` : **Décider** → choisir **Rejeter**, laisser le motif vide → **Enregistrer la décision**.
   - **Attendu** : message rouge sous **Motif** « obligatoire ».
3. Saisir `Délai de déclaration dépassé de plus de 30 jours` → **Enregistrer la décision**.
   - **Attendu** : statut **Rejeté** (terminal). Plus aucune action possible.
4. Essayer de décider à nouveau (URL `/dossiers/<id>/decision`) → refus « Une décision est déjà enregistrée ».

---

## 7. Scénario E — modification et annulation (UC06, UC12)

1. `accueil` : créer un brouillon → bouton **Modifier** → changer l'objet → **Enregistrer les modifications**
   → « Brouillon mis à jour ».
2. `accueil` : bouton **Annuler le dossier** → laisser le motif vide → **Confirmer l'annulation** → erreur
   « obligatoire ».
3. Saisir `Demande retirée par le déclarant` → **Confirmer l'annulation** → statut **Annulé**.
4. Le même défunt peut de nouveau faire l'objet d'un dossier (la règle anti-doublon ne s'applique qu'aux dossiers
   ouverts).

---

## 8. Scénario F — périmètre et droits (RM09, matrice des droits)

| Test | Résultat attendu |
|---|---|
| `certif` ouvre **Dossiers** | Ne voit **aucun** dossier de décès ou de mariage (catégorie État civil). |
| `certif` ouvre l'URL d'un dossier de décès | Page « Introuvable … ne fait pas partie de votre périmètre ». |
| `accueil` crée une **Légalisation de signature** (document `Attestation`, signataire `Kamga Eric`, qualité `Gérant`), déclare les 2 pièces, soumet | `certif` voit ce dossier et peut l'instruire ; `civil` ne le voit pas. |
| `civil` ouvre `/dossiers/nouveau` | Redirection avec « Vous n'avez pas les droits nécessaires ». |
| `civil` ouvre `/admin/utilisateurs` | Redirection vers le tableau de bord. |
| Un agent clique deux fois sur une action déjà faite | Message rouge « Transition interdite… Statut actuel : … » (CR09). |

---

## 9. Scénario G — administration (UC02, UC15, UC16, UC17)

Connecté en `admin` :

| Page | Action | Résultat attendu |
|---|---|---|
| **Comptes et rôles** | **Gérer** → **Désactiver** le compte `chef2` | Pastille « Désactivé » ; `chef2` ne peut plus se connecter. **Réactiver** le rétablit. |
| **Comptes et rôles** | **Gérer** → nouveau mot de passe → **Réinitialiser** | Le compte se connecte avec le nouveau mot de passe. |
| **Démarches et pièces** | Sur *Acte de décès*, ajouter la pièce code `ACTE_NAISSANCE_DEFUNT`, libellé `Acte de naissance du défunt` | « Pièce requise ajoutée ». Les **nouveaux** dossiers de décès demandent 4 pièces ; les anciens en gardent 3. |
| **Démarches et pièces** | **Désactiver** une démarche | Elle disparaît de **Nouveau dossier** pour l'accueil. |
| **Synchronisation Pipedrive** | Lire les cartes | Jeton (Valide / Non configuré / Refusé), pipeline, types d'activités, compteurs Synchronisé / En attente / En échec. |
| **Synchronisation Pipedrive** | **Relancer** sur une ligne en échec, ou **Relancer tous les échecs** | « Relance programmée » ; le worker retente dans les secondes qui suivent. |
| **Journaux techniques** | Filtrer `Opération = AUTH_CONNEXION` puis cliquer un identifiant de corrélation | Les connexions apparaissent ; le clic filtre tous les événements d'une même requête. Aucun mot de passe, jeton ou numéro de téléphone n'apparaît. |

---

## 10. Scénario H — vérification dans Pipedrive (si `PIPEDRIVE_API_TOKEN` est renseigné)

1. Avant tout, lancer une fois : `uv run python -m app.scripts.init_pipedrive` (crée le pipeline « Actes
   administratifs » et ses 6 étapes).
2. Rejouer le scénario A en regardant Pipedrive à chaque étape :

| Étape dans l'application | Ce qui apparaît dans Pipedrive (quelques secondes après) |
|---|---|
| A1 Création du brouillon | Un **contact** « Jean MBALLA » (nom, téléphone, e-mail uniquement) |
| A3 Soumission | Un **deal** « ACT-2026-… — Acte de décès » à l'étape **Reçu** + activité « Vérifier les pièces » |
| A4 Instruction | Deal à l'étape **En instruction** + activité « Instruire le dossier » |
| A4 Fin d'instruction | Étape **En attente de décision** + activité « Décision attendue » |
| A5 Approbation | Étape **Approuvé** + activité « Préparer la remise au demandeur » |
| A6 Délivrance | Étape **Délivré**, deal **gagné**, toutes les activités **terminées** |
| Scénario D (rejet) | Deal **perdu**, raison « Dossier rejeté » (le motif détaillé n'est **pas** envoyé) |

3. Dans l'application, onglet **Pipedrive** du dossier : tous les objets sont **Synchronisé** et la liste des
   activités Pipedrive s'affiche.
4. **Test de panne (CR05)** : arrêter le worker (terminal 2), faire avancer un dossier → l'application continue de
   fonctionner, l'onglet Pipedrive indique **En attente**. Relancer le worker → tout repasse **Synchronisé**.

Aucune donnée du défunt, aucune pièce et aucun motif n'est envoyé à Pipedrive : seul le contact du demandeur et
l'avancement du dossier le sont.

---

## 11. Récapitulatif : qui fait quoi, sur quelle page

| Étape | Utilisateur | Page / bouton |
|---|---|---|
| Créer les comptes | admin | Administration → Comptes et rôles |
| Créer un dossier | accueil | Nouveau dossier |
| Déclarer les pièces | accueil (ou instructeur) | Fiche du dossier → onglet Pièces → Déclarer |
| Soumettre | accueil | Fiche du dossier → Soumettre le dossier |
| Vérifier la complétude | civil / certif | Fiche du dossier → Vérifier la complétude |
| Instruire | civil / certif | Passer en instruction → Terminer l'instruction |
| Décider | chef | Fiche du dossier → Décider |
| Délivrer | accueil, instructeur ou chef | Fiche du dossier → Enregistrer la délivrance |
| Annuler | accueil ou chef | Fiche du dossier → Annuler le dossier |
| Suivre Pipedrive | admin | Administration → Synchronisation Pipedrive |

---

## 12. Dépannage

| Situation | Explication / solution |
|---|---|
| « Je ne vois pas Nouveau dossier » | Vous n'êtes pas connecté avec un compte **Agent d'accueil**. |
| « Jeton de sécurité invalide : rechargez la page » | Le formulaire est resté ouvert pendant une reconnexion : rechargez la page (F5). |
| « Votre session a expiré » | Session de 8 h dépassée ou application web redémarrée sans `WEB_SECRET_KEY` dans `.env`. |
| Page « Service indisponible … API injoignable » | L'API (terminal 1) n'est pas démarrée ou `WEB_API_URL` est incorrect. |
| Onglet Pipedrive « En échec PIPEDRIVE_NON_CONFIGURE » | `PIPEDRIVE_API_TOKEN` est vide dans `.env` : normal sans compte Pipedrive. |
| Onglet Pipedrive reste « En attente » | Le worker (terminal 2) n'est pas démarré. |
