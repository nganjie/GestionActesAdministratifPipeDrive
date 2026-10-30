"""Formulaires des cinq démarches (FRS §6.2) et conversion formulaire → JSON de l'API.

Les noms de champs reprennent les chemins de l'API (ex. `donnees_specifiques.defunt.nom`) : une erreur de
validation renvoyée par l'API s'affiche donc directement sous le bon champ.
"""

from dataclasses import dataclass, field
from typing import Any

PREFIXE = "donnees_specifiques."


@dataclass(frozen=True)
class Champ:
    nom: str
    libelle: str
    type: str = "text"  # text | date | number | select
    requis: bool = True
    options: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    aide: str | None = None


def _personne(prefixe: str, qui: str, naissance: bool = True, requis_naissance: bool = False) -> list[Champ]:
    champs = [Champ(f"{prefixe}.nom", f"Nom {qui}"), Champ(f"{prefixe}.prenom", f"Prénom {qui}")]
    if naissance:
        champs.append(Champ(f"{prefixe}.date_naissance", f"Date de naissance {qui}", "date", requis_naissance))
    return champs


FORMULAIRES: dict[str, dict[str, Any]] = {
    "DECES": {
        "titre": "Informations sur le décès",
        "champs": [
            *_personne("defunt", "du défunt"),
            Champ("date_deces", "Date du décès", "date"),
            Champ("lieu_deces", "Lieu du décès"),
            Champ("lien_declarant", "Lien du déclarant avec le défunt", aide="Ex. fils, conjointe, neveu"),
        ],
    },
    "MARIAGE": {
        "titre": "Futurs époux et célébration",
        "champs": [
            *_personne("epoux_1", "de l'époux 1"),
            *_personne("epoux_2", "de l'époux 2"),
            Champ("date_celebration_prevue", "Date de célébration prévue", "date"),
            *[c for i in range(4) for c in (
                Champ(f"temoins.{i}.nom", f"Nom du témoin {i + 1}", requis=i < 2),
                Champ(f"temoins.{i}.prenom", f"Prénom du témoin {i + 1}", requis=i < 2),
            )],
        ],
    },
    "COPIE_ACTE": {
        "titre": "Acte à copier",
        "champs": [
            Champ("type_acte", "Type d'acte", "select", options=(("MARIAGE", "Acte de mariage"),
                                                                  ("DECES", "Acte de décès"))),
            Champ("numero_acte", "Numéro de l'acte"),
            Champ("annee", "Année de l'acte", "number"),
            Champ("centre_etat_civil", "Centre d'état civil"),
            Champ("nombre_copies", "Nombre de copies (1 à 10)", "number"),
            Champ("qualite_demandeur", "Qualité du demandeur", aide="Ex. conjoint, enfant, mandataire"),
        ],
    },
    "LEGALISATION": {
        "titre": "Document et signataire",
        "champs": [
            Champ("intitule_document", "Intitulé du document"),
            *_personne("signataire", "du signataire", naissance=False),
            Champ("qualite_signataire", "Qualité du signataire"),
            Champ("nombre_exemplaires", "Nombre d'exemplaires", "number"),
        ],
    },
    "CERTIFICATION_CONFORME": {
        "titre": "Document à certifier",
        "champs": [
            Champ("intitule_document", "Intitulé du document original"),
            Champ("nombre_copies", "Nombre de copies (1 à 20)", "number"),
        ],
    },
}


def _cle(segment: str) -> str | int:
    return int(segment) if segment.isdigit() else segment


def _poser(cible: dict, chemin: list[str], valeur: Any) -> None:
    for segment in chemin[:-1]:
        cible = cible.setdefault(_cle(segment), {})
    cible[_cle(chemin[-1])] = valeur


def _listes(objet: Any) -> Any:
    """Transforme les dictionnaires à clés entières en listes ordonnées, sans les éléments vides."""
    if isinstance(objet, dict):
        if objet and all(isinstance(k, int) for k in objet):
            return [_listes(objet[k]) for k in sorted(objet) if any(v for v in objet[k].values())]
        return {k: _listes(v) for k, v in objet.items()}
    return objet


def donnees_specifiques(code: str, formulaire: dict[str, str]) -> dict[str, Any]:
    resultat: dict[str, Any] = {}
    for champ in FORMULAIRES.get(code, {}).get("champs", []):
        brut = (formulaire.get(PREFIXE + champ.nom) or "").strip()
        if not brut:
            continue
        valeur: Any = brut
        if champ.type == "number":
            try:
                valeur = int(brut)
            except ValueError:
                valeur = brut  # l'API renverra une erreur de validation sur ce champ
        _poser(resultat, champ.nom.split("."), valeur)
    return _listes(resultat)


def aplatir(donnees: dict[str, Any], prefixe: str = PREFIXE) -> dict[str, str]:
    """Inverse de donnees_specifiques : pré-remplit le formulaire de modification."""
    plat: dict[str, str] = {}
    for cle, valeur in (donnees or {}).items():
        if isinstance(valeur, dict):
            plat.update(aplatir(valeur, f"{prefixe}{cle}."))
        elif isinstance(valeur, list):
            for i, element in enumerate(valeur):
                plat.update(aplatir(element, f"{prefixe}{cle}.{i}."))
        elif valeur is not None:
            plat[f"{prefixe}{cle}"] = str(valeur)
    return plat


def demandeur(formulaire: dict[str, str]) -> dict[str, Any]:
    d = {k: (formulaire.get(f"demandeur.{k}") or "").strip() for k in
         ("nom", "prenom", "telephone", "email", "date_naissance")}
    return {k: v for k, v in d.items() if v}


def lignes_resume(code: str, donnees: dict[str, Any]) -> list[tuple[str, str]]:
    """Données spécifiques en (libellé, valeur) pour l'onglet Résumé."""
    plat = aplatir(donnees)
    lignes = []
    for champ in FORMULAIRES.get(code, {}).get("champs", []):
        valeur = plat.get(PREFIXE + champ.nom)
        if valeur:
            if champ.type == "select":
                valeur = dict(champ.options).get(valeur, valeur)
            elif champ.type == "date" and len(valeur) == 10:
                valeur = f"{valeur[8:10]}/{valeur[5:7]}/{valeur[0:4]}"
            lignes.append((champ.libelle, valeur))
    return lignes
