"""Shared PostgreSQL-backed rolling-window state for public API keys.

Kept separate from the frozen P3 model module so rate-state schema and its
retention policy can evolve independently from usage accounting.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.models import Base


class ApiKeyRateWindow(Base):
    """One row-locked rolling-window event array shared by all API workers."""

    __tablename__ = "api_key_rate_windows"

    api_key_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        primary_key=True,
    )
    timestamps: Mapped[list[float]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(timestamps) = 'array' AND jsonb_array_length(timestamps) <= 10000",
            name="ck_api_key_rate_window_bound",
        ),
        Index("ix_api_key_rate_windows_updated", updated_at),
    )
