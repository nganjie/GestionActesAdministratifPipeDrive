"""Faux Pipedrive en mémoire (API v2 + v1 users/me, activityTypes) pour les tests, via respx."""

import json
from collections import defaultdict
from typing import Any

import httpx
import respx

BASE = "https://pd.test"
JETON = "test-token"


class FakePipedrive:
    def __init__(self) -> None:
        self.persons: dict[int, dict] = {}
        self.deals: dict[int, dict] = {}
        self.activities: dict[int, dict] = {}
        self.pipelines: dict[int, dict] = {}
        self.stages: dict[int, dict] = {}
        self.activity_types = [
            {"key_string": k, "active_flag": True} for k in ("call", "meeting", "task", "deadline", "email")
        ]
        self.requetes: list[dict[str, Any]] = []
        self.pannes: dict[str, list[Any]] = defaultdict(list)
        self.taille_page = 100
        self._id = 1000

    # --- Pilotage des tests -----------------------------------------------------------------------

    def panne(self, operation: str, *reponses: Any) -> None:
        """Programme des réponses : un int (code HTTP), un tuple (code, entêtes), une exception httpx,
        ou "apres:<exception>" pour exécuter l'opération puis lever l'exception (création effective + timeout)."""
        self.pannes[operation].extend(reponses)

    def appels(self, operation: str) -> list[dict[str, Any]]:
        return [r for r in self.requetes if r["operation"] == operation]

    def _nouvel_id(self) -> int:
        self._id += 1
        return self._id

    # --- Installation -------------------------------------------------------------------------------

    def installer(self, router: respx.MockRouter) -> None:
        routes = [
            ("GET", r"/v1/users/me$", "users.me", self._me),
            ("GET", r"/v1/activityTypes$", "activityTypes.list", self._types),
            ("GET", r"/api/v2/persons/search$", "persons.search", self._persons_search),
            ("POST", r"/api/v2/persons$", "persons.create", self._persons_create),
            ("PATCH", r"/api/v2/persons/(?P<id>\d+)$", "persons.update", self._persons_update),
            ("GET", r"/api/v2/pipelines$", "pipelines.list", self._pipelines_list),
            ("POST", r"/api/v2/pipelines$", "pipelines.create", self._pipelines_create),
            ("GET", r"/api/v2/stages$", "stages.list", self._stages_list),
            ("POST", r"/api/v2/stages$", "stages.create", self._stages_create),
            ("GET", r"/api/v2/deals/search$", "deals.search", self._deals_search),
            ("POST", r"/api/v2/deals$", "deals.create", self._deals_create),
            ("PATCH", r"/api/v2/deals/(?P<id>\d+)$", "deals.update", self._deals_update),
            ("GET", r"/api/v2/deals$", "deals.list", self._deals_list),
            ("DELETE", r"/api/v2/deals/(?P<id>\d+)$", "deals.delete", self._deals_delete),
            ("DELETE", r"/api/v2/activities/(?P<id>\d+)$", "activities.delete", self._activities_delete),
            ("GET", r"/api/v2/activities$", "activities.list", self._activities_list),
            ("POST", r"/api/v2/activities$", "activities.create", self._activities_create),
            ("GET", r"/api/v2/activities/(?P<id>\d+)$", "activities.get", self._activities_get),
            ("PATCH", r"/api/v2/activities/(?P<id>\d+)$", "activities.update", self._activities_update),
        ]
        for methode, motif, operation, gestionnaire in routes:
            router.route(method=methode, host="pd.test", path__regex="^" + motif).mock(
                side_effect=self._envelopper(operation, gestionnaire)
            )

    def _envelopper(self, operation: str, gestionnaire):  # noqa: ANN001, ANN202
        def _repondre(request: httpx.Request, **params: str) -> httpx.Response:
            corps = json.loads(request.content) if request.content else None
            self.requetes.append({
                "operation": operation, "methode": request.method, "url": str(request.url), "json": corps,
                "entetes": dict(request.headers), "params": dict(request.url.params),
            })
            if request.headers.get("x-api-token") != JETON:
                return httpx.Response(401, json={"success": False, "error": "unauthorized"})
            apres = None
            if self.pannes[operation]:
                panne = self.pannes[operation].pop(0)
                if isinstance(panne, str) and panne.startswith("apres:"):
                    apres = panne
                elif isinstance(panne, Exception):
                    raise panne
                else:
                    code, entetes = panne if isinstance(panne, tuple) else (panne, {})
                    return httpx.Response(code, headers=entetes, json={"success": False, "error": f"panne {code}"})
            reponse = gestionnaire(request, corps, **params)
            if apres:
                raise httpx.ReadTimeout("timeout simulé après traitement", request=request)
            return reponse
        return _repondre

    @staticmethod
    def _ok(data: Any, code: int = 200, curseur: str | None = None) -> httpx.Response:
        return httpx.Response(code, json={"success": True, "data": data, "additional_data": {"next_cursor": curseur}})

    def _paginer(self, request: httpx.Request, elements: list[dict]) -> httpx.Response:
        debut = int(request.url.params.get("cursor", "0"))
        page = elements[debut:debut + self.taille_page]
        suivant = debut + self.taille_page
        return self._ok(page, curseur=str(suivant) if suivant < len(elements) else None)

    # --- Gestionnaires -------------------------------------------------------------------------------

    def _me(self, request, corps):  # noqa: ANN001, ANN202
        return self._ok({"id": 42, "company_domain": "mairie-demo", "active_flag": True})

    def _types(self, request, corps):  # noqa: ANN001, ANN202
        return self._ok(self.activity_types)

    def _persons_search(self, request, corps):  # noqa: ANN001, ANN202
        terme = request.url.params["term"].lower()
        champ = request.url.params["fields"]
        trouves = []
        for p in self.persons.values():
            valeurs = [e["value"].lower() for e in p.get("emails" if champ == "email" else "phones", [])]
            if terme in valeurs:
                trouves.append({"result_score": 1, "item": {"id": p["id"], "type": "person", "name": p["name"]}})
        return self._ok({"items": trouves})

    def _persons_create(self, request, corps):  # noqa: ANN001, ANN202
        pid = self._nouvel_id()
        self.persons[pid] = {"id": pid, **corps}
        return self._ok(self.persons[pid], 201)

    def _persons_update(self, request, corps, id):  # noqa: ANN001, ANN202, A002
        if int(id) not in self.persons:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        self.persons[int(id)].update(corps)
        return self._ok(self.persons[int(id)])

    def _pipelines_list(self, request, corps):  # noqa: ANN001, ANN202
        return self._paginer(request, list(self.pipelines.values()))

    def _pipelines_create(self, request, corps):  # noqa: ANN001, ANN202
        pid = self._nouvel_id()
        self.pipelines[pid] = {"id": pid, **corps}
        return self._ok(self.pipelines[pid], 201)

    def _stages_list(self, request, corps):  # noqa: ANN001, ANN202
        pipeline_id = int(request.url.params["pipeline_id"])
        return self._paginer(request, [s for s in self.stages.values() if s["pipeline_id"] == pipeline_id])

    def _stages_create(self, request, corps):  # noqa: ANN001, ANN202
        sid = self._nouvel_id()
        self.stages[sid] = {"id": sid, **corps}
        return self._ok(self.stages[sid], 201)

    def _deals_search(self, request, corps):  # noqa: ANN001, ANN202
        terme = request.url.params["term"]
        items = [{"item": {"id": d["id"], "title": d["title"]}} for d in self.deals.values() if terme in d["title"]]
        return self._ok({"items": items})

    def _deals_create(self, request, corps):  # noqa: ANN001, ANN202
        did = self._nouvel_id()
        self.deals[did] = {"id": did, "status": "open", **corps}
        return self._ok(self.deals[did], 201)

    def _deals_update(self, request, corps, id):  # noqa: ANN001, ANN202, A002
        if int(id) not in self.deals:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        self.deals[int(id)].update(corps)
        return self._ok(self.deals[int(id)])

    def _deals_list(self, request, corps):  # noqa: ANN001, ANN202
        pipeline_id = int(request.url.params["pipeline_id"])
        return self._paginer(request, [d for d in self.deals.values() if d.get("pipeline_id") == pipeline_id])

    def _deals_delete(self, request, corps, id):  # noqa: ANN001, ANN202, A002
        if self.deals.pop(int(id), None) is None:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        return self._ok({"id": int(id)})

    def _activities_delete(self, request, corps, id):  # noqa: ANN001, ANN202, A002
        if self.activities.pop(int(id), None) is None:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        return self._ok({"id": int(id)})

    def _activities_list(self, request, corps):  # noqa: ANN001, ANN202
        deal_id = int(request.url.params["deal_id"])
        return self._paginer(request, [a for a in self.activities.values() if a["deal_id"] == deal_id])

    def _activities_create(self, request, corps):  # noqa: ANN001, ANN202
        aid = self._nouvel_id()
        self.activities[aid] = {"id": aid, "done": False, **corps}
        return self._ok(self.activities[aid], 201)

    def _activities_get(self, request, corps, id):  # noqa: ANN001, ANN202, A002
        if int(id) not in self.activities:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        return self._ok(self.activities[int(id)])

    def _activities_update(self, request, corps, id):  # noqa: ANN001, ANN202, A002
        if int(id) not in self.activities:
            return httpx.Response(404, json={"success": False, "error": "not found"})
        self.activities[int(id)].update(corps)
        return self._ok(self.activities[int(id)])
