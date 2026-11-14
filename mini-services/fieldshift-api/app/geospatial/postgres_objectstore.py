"""Private PostgreSQL bytea object storage for bounded free-tier deployments.

The adapter intentionally uses the existing object-store protocol while keeping
all durable bytes in the shared ``artifact_objects`` table.  It is suitable for
small raster/report artifacts only; callers must configure the application byte
and total budgets through Settings.
"""
from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import SessionLocal
from app.db.models_artifacts import ArtifactObject
from app.geospatial.objectstore import (
    AssetValidationError,
    KeyConflictError,
    NotFoundError,
    ObjectStat,
    StorageError,
    StoredObject,
    signed_local_key,
    validate_storage_key,
)

# A fixed, application-private advisory lock key.  No user input is interpolated
# into SQL; every writer to this shared budget serializes on this transaction
# lock before it reads or changes the aggregate byte count.
_BUDGET_LOCK_KEY = 817294631


class PostgresStorage:
    """Durable tenant-scoped object store backed by PostgreSQL BYTEA."""

    backend = "postgres"

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | Any = SessionLocal,
        max_object_bytes: int | None = None,
        total_budget_bytes: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._max_object_bytes = int(
            max_object_bytes
            if max_object_bytes is not None
            else getattr(settings, "artifact_max_object_bytes", 32_000_000)
        )
        self._total_budget_bytes = int(
            total_budget_bytes
            if total_budget_bytes is not None
            else getattr(settings, "artifact_total_budget_bytes", 256_000_000)
        )
        if self._max_object_bytes <= 0 or self._total_budget_bytes <= 0:
            raise StorageError("artifact storage budgets must be positive")
        if self._max_object_bytes > self._total_budget_bytes:
            raise StorageError("artifact object budget cannot exceed total budget")

    @contextmanager
    def _session(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
        except StorageError:
            session.rollback()
            raise
        except SQLAlchemyError as exc:
            session.rollback()
            raise StorageError("artifact storage is unavailable") from exc
        finally:
            session.close()

    @staticmethod
    def _organization_id(key: str) -> uuid.UUID:
        validate_storage_key(key, require_tenant=True)
        parts = key.split("/")
        try:
            return uuid.UUID(parts[1])
        except (IndexError, ValueError) as exc:
            raise StorageError("storage key has an invalid organization scope") from exc

    def _validate_blob(self, data: bytes, content_type: str) -> str:
        if not isinstance(data, bytes) or not data:
            raise AssetValidationError("artifact payload is empty")
        if len(data) > self._max_object_bytes:
            raise AssetValidationError(
                f"artifact payload exceeds the configured object limit of {self._max_object_bytes} bytes"
            )
        if not isinstance(content_type, str) or not content_type.strip() or len(content_type) > 255:
            raise AssetValidationError("artifact content type is invalid")
        if any(ord(char) < 32 for char in content_type):
            raise AssetValidationError("artifact content type is invalid")
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _lock_budget(session: Session) -> None:
        # func.pg_advisory_xact_lock compiles to a bound integer function call,
        # avoiding dynamic SQL identifiers and holding the lock until commit.
        session.execute(select(func.pg_advisory_xact_lock(_BUDGET_LOCK_KEY)))

    @staticmethod
    def _stored(row: ArtifactObject) -> StoredObject:
        return StoredObject(
            key=row.object_key,
            byte_size=int(row.byte_size),
            checksum_sha256=row.checksum_sha256,
            content_type=row.content_type,
            backend="postgres",
        )

    def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        overwrite: bool = False,
    ) -> StoredObject:
        organization_id = self._organization_id(key)
        checksum = self._validate_blob(data, content_type)
        with self._session() as session:
            self._lock_budget(session)
            row = session.scalar(
                select(ArtifactObject)
                .where(
                    ArtifactObject.organization_id == organization_id,
                    ArtifactObject.object_key == key,
                )
                .with_for_update()
            )
            current = int(
                session.scalar(select(func.coalesce(func.sum(ArtifactObject.byte_size), 0))) or 0
            )
            if row is not None:
                # Retries of an already committed identical write are safe and
                # idempotent.  A changed payload still requires explicit
                # overwrite=True, preserving the no-accidental-overwrite rule.
                if (
                    row.checksum_sha256 == checksum
                    and row.byte_size == len(data)
                    and row.content_type == content_type
                ):
                    session.commit()
                    return self._stored(row)
                if not overwrite:
                    raise KeyConflictError(f"object already exists: {key}")
                old_size = int(row.byte_size)
                row.content = data
                row.byte_size = len(data)
                row.checksum_sha256 = checksum
                row.content_type = content_type
            else:
                old_size = 0
                row = ArtifactObject(
                    organization_id=organization_id,
                    object_key=key,
                    content=data,
                    byte_size=len(data),
                    checksum_sha256=checksum,
                    content_type=content_type,
                )
                session.add(row)
            projected = current - old_size + len(data)
            if projected > self._total_budget_bytes:
                raise AssetValidationError(
                    "artifact storage total budget would be exceeded"
                )
            session.commit()
            return self._stored(row)

    def _get(self, session: Session, key: str) -> ArtifactObject:
        organization_id = self._organization_id(key)
        row = session.scalar(
            select(ArtifactObject).where(
                ArtifactObject.organization_id == organization_id,
                ArtifactObject.object_key == key,
            )
        )
        if row is None:
            raise NotFoundError("object not found")
        return row

    def exists(self, key: str) -> bool:
        validate_storage_key(key, require_tenant=True)
        try:
            with self._session() as session:
                return self._get(session, key) is not None
        except NotFoundError:
            return False

    def stat(self, key: str) -> ObjectStat:
        validate_storage_key(key, require_tenant=True)
        with self._session() as session:
            row = self._get(session, key)
            return ObjectStat(
                key=key,
                byte_size=int(row.byte_size),
                checksum_sha256=row.checksum_sha256,
                content_type=row.content_type,
                backend=self.backend,
            )

    def read_bytes(self, key: str) -> bytes:
        validate_storage_key(key, require_tenant=True)
        with self._session() as session:
            row = self._get(session, key)
            return bytes(row.content)

    def delete(self, key: str) -> None:
        validate_storage_key(key, require_tenant=True)
        with self._session() as session:
            self._lock_budget(session)
            row = self._get(session, key)
            session.delete(row)
            session.commit()

    def signed_url(self, key: str, *, ttl_seconds: int = 300) -> str:
        """Return only an expiring opaque token; bytes remain API-authenticated."""
        validate_storage_key(key, require_tenant=True)
        return signed_local_key(key, ttl_seconds=ttl_seconds)


__all__ = ["PostgresStorage"]
