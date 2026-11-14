"""Permission-aware context resolution for authenticated AI requests."""
from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import Forbidden, NotFound
from app.db.models import Farm
from app.db.models_ai import AIAdvisorSession
from app.domains.identity.service import get_field_for_principal
from app.intelligence import sessions as session_service
from app.intelligence.orchestration.provider import LLMProvider


@dataclass
class AuthorizedAIContext:
    db: Session
    principal: Any
    field: Any | None = None
    farm: Farm | None = None
    organization_id: UUID | None = None
    role: str | None = None
    permissions: frozenset[str] = frozenset()
    selected_domains: tuple[str, ...] = ()
    locale: str = "en"
    session: AIAdvisorSession | None = None
    history: list[dict[str, str]] = dataclass_field(default_factory=list)
    prior_tool_results: list[dict[str, Any]] = dataclass_field(default_factory=list)
    provider: LLMProvider | None = None
    request_id: str | None = None

    @property
    def user_id(self) -> UUID:
        return self.principal.id

    @property
    def field_id(self) -> UUID | None:
        return self.field.id if self.field is not None else None

    @property
    def farm_id(self) -> UUID | None:
        return self.farm.id if self.farm is not None else None


def resolve_authorized_context(
    db: Session,
    principal: Any,
    *,
    field_id: UUID | None,
    conversation_id: UUID | None,
    locale: str,
    selected_domains: tuple[str, ...],
    history_turns: int,
    retention_days: int,
) -> AuthorizedAIContext:
    """Authorize client-selected field IDs before any farm data is retrieved."""
    context = AuthorizedAIContext(
        db=db,
        principal=principal,
        selected_domains=selected_domains,
        locale=locale,
    )
    if field_id is None:
        if conversation_id is not None:
            raise NotFound("AI conversation not found.")
        return context

    authorized_field = get_field_for_principal(db, principal, field_id)
    farm = db.get(Farm, authorized_field.farm_id)
    if farm is None:
        raise NotFound("Field not found.")
    membership = principal.membership_in(farm.organization_id)
    if membership is None:
        # Re-check the derived tenant boundary; never trust request organization IDs.
        raise Forbidden("You do not have access to this organization's resources.")
    context.field = authorized_field
    context.farm = farm
    context.organization_id = farm.organization_id
    context.role = membership.role_code
    # Existing tenancy grants field reads to active members; there is no
    # domain-specific ACL in the repository, so do not claim otherwise.
    context.permissions = frozenset({"field.read", "field.analysis.read"})

    if conversation_id is not None:
        session = session_service.get_or_404_for_field(db, conversation_id, authorized_field.id)
        if session is None or session.owner_user_id != principal.id:
            # Same response for absent, cross-field, legacy-unowned and
            # other-user conversations avoids a session-existence oracle.
            raise NotFound("AI conversation not found.")
        if retention_days > 0 and session.updated_at is not None:
            updated_at = session.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            if updated_at < datetime.now(UTC) - timedelta(days=retention_days):
                raise NotFound("AI conversation not found.")
        context.session = session
        context.history = session_service.recent_history(db, session.id, history_turns)
    return context
