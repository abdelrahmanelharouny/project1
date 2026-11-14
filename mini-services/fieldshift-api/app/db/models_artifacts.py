"""Durable private bytes shared by raster and report storage backends.

The table deliberately stores opaque bytes only. Domain rows retain their
existing contracts and point to an object key in ``file_path``/``storage_key``;
tenant ownership is enforced by the organization UUID embedded in the key and
by this table's organization_id column.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base, Organization, _uuid


class ArtifactObject(Base):
    """One private, content-addressed-by-key object owned by one organization."""

    __tablename__ = "artifact_objects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        # Keep created_at explicit so this module does not depend on mutable
        # domain model mixins; artifact rows are otherwise immutable metadata.
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        Index("uq_artifact_objects_org_key", "organization_id", "object_key", unique=True),
        Index("ix_artifact_objects_org_created", "organization_id", "created_at"),
        CheckConstraint("byte_size > 0", name="ck_artifact_objects_byte_size_positive"),
        CheckConstraint("length(checksum_sha256) = 64", name="ck_artifact_objects_checksum_length"),
    )


__all__ = ["ArtifactObject"]
