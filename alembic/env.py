"""Ambiente de migrations do Alembic.

Duas decisoes deliberadas aqui:

1. A URL do banco vem das MESMAS settings da aplicacao, nao do alembic.ini. Assim existe
   uma unica fonte de verdade de credencial, ela vive so no ambiente, e nunca ha um DSN
   com senha dentro de um arquivo versionado.
2. `target_metadata` aponta para o `Base.metadata` da aplicacao -- que ja carrega a
   naming convention do Postgres (ver app/core/database.py). E isso que faz o autogenerate
   produzir nomes de indice e constraint deterministicos, e portanto migrations
   reversiveis: um `DROP CONSTRAINT` so funciona se o nome for previsivel.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Importar o pacote de models registra as tabelas no metadata. Sem isso o autogenerate
# nao "enxerga" nenhuma tabela e geraria uma migration vazia -- ou pior, um DROP de tudo.
import app.models  # noqa: F401
from alembic import context
from app.core.config import get_settings
from app.core.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar no banco (`alembic upgrade head --sql`).

    Util para revisar o SQL antes de aplicar em producao, ou para entregar o script
    a um DBA em ambientes onde a aplicacao nao tem permissao de DDL.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # compare_type: detecta mudanca de tipo de coluna no autogenerate.
        # Vem desligado por padrao, o que silenciosamente ignora, por exemplo,
        # um NUMERIC(10,2) que virou NUMERIC(12,2).
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
