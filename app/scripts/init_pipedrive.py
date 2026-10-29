"""Initialisation de Pipedrive : jeton, types d'activités, pipeline et étapes (ISD OP-01, OP-05 à OP-08, OP-16).

Lancement : `python -m app.scripts.init_pipedrive`
"""

import asyncio
import sys

from app.core.config import get_settings
from app.core.logging import configurer_logging
from app.db.base import dispose_engine, init_engine
from app.integrations.pipedrive.adapter import PipedriveAdapter
from app.integrations.pipedrive.client import PipedriveClient
from app.integrations.pipedrive.errors import PipedriveErreur
from app.services import journal
from app.services.pipedrive_init import initialiser_pipeline, verifier_types_activite


async def main() -> int:
    settings = get_settings()
    configurer_logging()
    if not settings.pipedrive_configure:
        print("PIPEDRIVE_API_TOKEN n'est pas défini.", file=sys.stderr)
        return 2
    appels = []
    adapter = PipedriveAdapter(PipedriveClient(settings, on_appel=appels.append))
    session_factory = init_engine(settings.database_url)
    try:
        async with session_factory() as session:
            try:
                compte = await adapter.verifier_jeton()
                print(f"Jeton valide — compte {compte['id']} ({compte['company_domain']})")
                await verifier_types_activite(adapter)
                print("Types d'activités task, call, deadline : présents")
                params = await initialiser_pipeline(session, adapter, settings)
                print(f"Pipeline « {settings.pipedrive_pipeline_name} » : {params.pipeline_id}")
                for statut, stage_id in params.etapes.items():
                    print(f"  {statut:<22} -> étape {stage_id}")
                journal.ecrire(session, "INIT_PIPEDRIVE", "SUCCES")
                return_code = 0
            except PipedriveErreur as exc:
                print(f"Échec : {exc.code} — {exc.message}", file=sys.stderr)
                journal.ecrire(session, "INIT_PIPEDRIVE", "ECHEC", niveau="ERROR", code_erreur=exc.code)
                return_code = 1
            journal.ecrire_appels(session, appels)
            await session.commit()
            return return_code
    finally:
        await adapter.client.aclose()
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
