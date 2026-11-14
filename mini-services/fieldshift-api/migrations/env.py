"""Alembic environment for CropTwist migrations."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.db.models import Base

# Register the AI-layer tables on Base.metadata. models_ai is deliberately
# NOT imported by app/db/models.py (kept frozen for the AI pivot), so without
# this import alembic autogenerate/check treats ai_recommendations and
# ai_advisor_messages as unknown objects and would generate a migration
# DROPPING them. Import every model module here so target_metadata always
# mirrors the full schema.
import app.db.models_ai  # noqa: F401  (side-effect: registers AI tables)
import app.db.models_p2  # noqa: F401  (side-effect: registers P2 tables)
import app.db.models_p3  # noqa: F401  (side-effect: registers P3 commercial tables)
import app.db.models_api_rate  # noqa: F401  (side-effect: registers shared API rate windows)
import app.db.models_orchestration  # noqa: F401  (side-effect: registers AI Core traces)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS system tables must never be autodiffed into migrations.
    if type_ == "table" and name in ("spatial_ref_sys",):
        return False
    return True


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
