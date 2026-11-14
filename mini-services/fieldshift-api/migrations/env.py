"""Alembic environment for CropTwist migrations."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.core.database import get_database_connect_args
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
import app.db.models_artifacts  # noqa: F401  (side-effect: registers durable artifact bytes)

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
    # Offline migrations do not reflect extension-owned relations. Online
    # autogenerate uses the connection-aware filter below.
    return True


def _extension_owned_relations(connection):
    """Return relations owned by installed PostgreSQL extensions.

    PostGIS installs some support relations in the default schema. Alembic
    should not propose dropping those extension-managed objects, but must
    continue checking every application relation against model metadata.
    """
    result = connection.exec_driver_sql(
        """
        SELECT namespace.nspname, relation.relname,
               pg_catalog.pg_table_is_visible(relation.oid)
        FROM pg_depend AS dependency
        JOIN pg_extension AS ext
          ON dependency.refclassid = 'pg_extension'::regclass
         AND dependency.refobjid = ext.oid
        JOIN pg_class AS relation
          ON dependency.classid = 'pg_class'::regclass
         AND dependency.objid = relation.oid
        JOIN pg_namespace AS namespace
          ON relation.relnamespace = namespace.oid
        WHERE dependency.deptype = 'e'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
        """
    )
    relations: set[tuple[str | None, str]] = set()
    for schema, name, is_visible in result:
        relations.add((schema, name))
        # Alembic represents a visible relation reflected from the search path
        # with schema=None, even if it lives outside current_schema().
        if is_visible:
            relations.add((None, name))
    return relations


def _make_include_object(connection):
    # Resolve catalog metadata only when autogenerate invokes this callback.
    # Alembic also imports env.py for normal upgrades; an eager SELECT here
    # would autobegin a transaction before Alembic starts its migration txn.
    extension_relations: set[tuple[str | None, str]] | None = None

    def include_extension_aware_object(obj, name, type_, reflected, compare_to):
        nonlocal extension_relations
        relation = obj if type_ == "table" else getattr(obj, "table", None)
        if relation is not None:
            if extension_relations is None:
                extension_relations = _extension_owned_relations(connection)
            schema = getattr(relation, "schema", None)
            if (schema, relation.name) in extension_relations:
                return False
        return include_object(obj, name, type_, reflected, compare_to)

    return include_extension_aware_object


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args=get_database_connect_args(),
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_make_include_object(connection),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
