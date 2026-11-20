import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db.base import Base
from app.models.alerta import Alerta
from app.models.auditoria import EventoAuditoria
from app.models.campana import Campana, CampanaCanal, DestinatarioCampana
from app.models.destinatario import Destinatario
from app.models.grupo import Grupo
from app.models.historial import HistorialContrasenas
from app.models.instantanea import InstantaneaPhishing
from app.models.organizacion import Organizacion
from app.models.plantilla import Plantilla
from app.models.qr_zona import CampanaQrZona
from app.models.tracking import EventoTracking
from app.models.usuario import Usuario

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

if os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)

    def _do_run_migrations(connection):
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

    async def _run():
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
        await connectable.dispose()

    asyncio.run(_run())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
