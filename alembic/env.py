"""Migrations Alembic (mode asynchrone) ; l'URL vient de DATABASE_URL."""

import asyncio
import os

from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context
from app.db import models  # noqa: F401  (enregistre les tables)
from app.db.base import Base

target_metadata = Base.metadata


def _url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL doit être défini pour exécuter les migrations")
    return url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _executer(connexion) -> None:  # noqa: ANN001
    context.configure(connection=connexion, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    moteur = create_async_engine(_url())
    async with moteur.connect() as connexion:
        await connexion.run_sync(_executer)
    await moteur.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
