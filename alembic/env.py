import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db.base import Base
from app.models.auditoria import EventoAuditoria  # noqa: F401
from app.models.historial import HistorialContrasenas  # noqa: F401
from app.models.organizacion import Organizacion  # noqa: F401
from app.models.usuario import Usuario  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    async def _run():
        async with connectable.connect() as connection:
            await connection.run_sync(lambda sync_conn: context.configure(connection=sync_conn, target_metadata=target_metadata))
            async with connection.begin():
                await connection.run_sync(context.run_migrations)
    asyncio.run(_run())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
