"""Adaptateur Pipedrive : une méthode par opération de l'ISD (OP-01 à OP-16)."""

from typing import Any

from app.integrations.pipedrive.client import PipedriveClient
from app.integrations.pipedrive.errors import ErreurDefinitive


def _id(corps: dict[str, Any]) -> int:
    data = corps.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        raise ErreurDefinitive("REPONSE_INATTENDUE", "identifiant absent de la réponse")
    return data["id"]


def _items_recherche(corps: dict[str, Any]) -> list[dict[str, Any]]:
    data = corps.get("data")
    if isinstance(data, dict):
        data = data.get("items", [])
    resultats = []
    for entree in data or []:
        item = entree.get("item", entree) if isinstance(entree, dict) else None
        if isinstance(item, dict) and isinstance(item.get("id"), int):
            resultats.append(item)
    return resultats


class PipedriveAdapter:
    def __init__(self, client: PipedriveClient):
        self.client = client

    async def _paginer(self, operation: str, route: str, params: dict[str, Any] | None = None,
                       chemin: str | None = None) -> list[dict[str, Any]]:
        resultats: list[dict[str, Any]] = []
        curseur: str | None = None
        while True:
            p = dict(params or {}, limit=100)
            if curseur:
                p["cursor"] = curseur
            corps = await self.client.requete(operation, "GET", route, chemin=chemin, params=p)
            resultats.extend(corps.get("data") or [])
            curseur = (corps.get("additional_data") or {}).get("next_cursor")
            if not curseur:
                return resultats

    # OP-01
    async def verifier_jeton(self) -> dict[str, Any]:
        corps = await self.client.requete("OP-01", "GET", "/v1/users/me")
        data = corps.get("data") or {}
        return {"id": data.get("id"), "company_domain": data.get("company_domain"),
                "actif": bool(data.get("active_flag", True))}

    # OP-16
    async def types_activite(self) -> list[dict[str, Any]]:
        corps = await self.client.requete("OP-16", "GET", "/v1/activityTypes")
        return [{"key_string": t.get("key_string"), "active_flag": t.get("active_flag", True)}
                for t in corps.get("data") or []]

    # OP-02
    async def rechercher_personne(self, terme: str, champ: str) -> list[int]:
        corps = await self.client.requete(
            "OP-02", "GET", "/api/v2/persons/search",
            params={"term": terme, "fields": champ, "exact_match": "true", "limit": 10},
        )
        return sorted(item["id"] for item in _items_recherche(corps))

    # OP-03
    async def creer_personne(self, charge: dict[str, Any]) -> int:
        return _id(await self.client.requete("OP-03", "POST", "/api/v2/persons", json=charge))

    # OP-04
    async def maj_personne(self, person_id: int, charge: dict[str, Any]) -> None:
        await self.client.requete("OP-04", "PATCH", "/api/v2/persons/{id}",
                                  chemin=f"/api/v2/persons/{person_id}", json=charge)

    # OP-05 / OP-06
    async def lister_pipelines(self) -> list[dict[str, Any]]:
        return await self._paginer("OP-05", "/api/v2/pipelines")

    async def creer_pipeline(self, nom: str) -> int:
        return _id(await self.client.requete("OP-06", "POST", "/api/v2/pipelines", json={"name": nom}))

    # OP-07 / OP-08
    async def lister_etapes(self, pipeline_id: int) -> list[dict[str, Any]]:
        return await self._paginer("OP-07", "/api/v2/stages", params={"pipeline_id": pipeline_id})

    async def creer_etape(self, nom: str, pipeline_id: int) -> int:
        return _id(await self.client.requete("OP-08", "POST", "/api/v2/stages",
                                             json={"name": nom, "pipeline_id": pipeline_id}))

    # OP-09
    async def creer_deal(self, charge: dict[str, Any]) -> int:
        return _id(await self.client.requete("OP-09", "POST", "/api/v2/deals", json=charge))

    # OP-10
    async def rechercher_deal(self, reference: str) -> int | None:
        corps = await self.client.requete("OP-10", "GET", "/api/v2/deals/search",
                                          params={"term": reference, "fields": "title"})
        ids = sorted(i["id"] for i in _items_recherche(corps) if str(i.get("title", "")).startswith(reference))
        return ids[0] if ids else None

    # OP-11
    async def maj_deal(self, deal_id: int, charge: dict[str, Any]) -> None:
        await self.client.requete("OP-11", "PATCH", "/api/v2/deals/{id}",
                                  chemin=f"/api/v2/deals/{deal_id}", json=charge)

    # OP-12
    async def creer_activite(self, charge: dict[str, Any]) -> int:
        return _id(await self.client.requete("OP-12", "POST", "/api/v2/activities", json=charge))

    # OP-13
    async def lister_activites_deal(self, deal_id: int) -> list[dict[str, Any]]:
        return await self._paginer("OP-13", "/api/v2/activities", params={"deal_id": deal_id})

    # OP-14
    async def maj_activite(self, activite_id: int, charge: dict[str, Any]) -> None:
        await self.client.requete("OP-14", "PATCH", "/api/v2/activities/{id}",
                                  chemin=f"/api/v2/activities/{activite_id}", json=charge)

    # OP-15
    async def lire_activite(self, activite_id: int) -> dict[str, Any]:
        corps = await self.client.requete("OP-15", "GET", "/api/v2/activities/{id}",
                                          chemin=f"/api/v2/activities/{activite_id}")
        return corps.get("data") or {}
