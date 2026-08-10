"""Alembic environment — B1-W1-04. Uses sync psycopg driver derived from DATABASE_URL."""
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all module models here so autogenerate sees them:
from app.patients import models  # noqa: F401
from app.common.db import Base  # noqa: E402

from app.users import models as users_models  # noqa: E402, F401
from app.allergies import models as allergies_models  # noqa: E402, F401
from app.billing import models as billing_models  # noqa: E402, F401

from app.inventory import models as inventory_models  # noqa: F401, E402
from app.pharmacy import models as pharmacy_models  # noqa: F401, E402

from app.ot import models as ot_models  # noqa: E402, F401

target_metadata = Base.metadata


def _sync_url() -> str:
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://healthdoc:change-me@localhost:5432/healthdoc",
    )
    return url.replace("+asyncpg", "")


def run_migrations_offline() -> None:
    context.configure(url=_sync_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()