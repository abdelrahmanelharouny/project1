"""AI knowledge readiness contract tests; no database or live provider calls."""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.api.v1 import ai_core


@pytest.mark.parametrize(
    ("overrides", "expected_blocker"),
    [
        ({"compatible_adapter_registered": False}, "embedding_provider_unavailable"),
        ({"compatible_ready_vector_available": False}, "no_compatible_ready_vector"),
        ({"documents_to_provider_allowed": False}, "document_embedding_sharing_disabled"),
        ({"queries_to_provider_allowed": False}, "query_embedding_sharing_disabled"),
    ],
)
def test_semantic_readiness_reports_each_single_missing_condition(overrides, expected_blocker):
    conditions = {
        "compatible_adapter_registered": True,
        "compatible_ready_vector_available": True,
        "documents_to_provider_allowed": True,
        "queries_to_provider_allowed": True,
    }
    conditions.update(overrides)

    available, blockers = ai_core._semantic_retrieval_readiness(**conditions)

    assert available is False
    assert blockers == [expected_blocker]


def test_semantic_readiness_is_available_when_every_condition_is_met():
    available, blockers = ai_core._semantic_retrieval_readiness(
        compatible_adapter_registered=True,
        compatible_ready_vector_available=True,
        documents_to_provider_allowed=True,
        queries_to_provider_allowed=True,
    )

    assert available is True
    assert blockers == []


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeStatusSession:
    def __init__(self, vector_row):
        self._counts = iter((3, 2, 5))
        self.vector_row = vector_row
        self.statements = []

    def scalar(self, statement):
        self.statements.append(statement)
        return next(self._counts)

    def execute(self, statement):
        self.statements.append(statement)
        return _FakeResult([self.vector_row])


class _Manager:
    def __init__(self):
        self.authorized_organization = None

    def require_org_role(self, organization_id, role):
        assert role == "manager"
        self.authorized_organization = organization_id


class _Registry:
    def __init__(self, provider):
        self.provider = provider

    def names(self):
        return (self.provider.name,)

    def get(self, name):
        return self.provider if name == self.provider.name else None


def test_knowledge_status_route_checks_a_tenant_scoped_searchable_vector(monkeypatch):
    organization_id = uuid4()
    provider = SimpleNamespace(name="reviewed-embedder", model="embed-v3")
    now = datetime.now(UTC)
    session = _FakeStatusSession(([0.4, 0.6], 2, now, None))
    principal = _Manager()
    monkeypatch.setattr(ai_core, "embedding_provider_registry", _Registry(provider))
    monkeypatch.setattr(ai_core.ai_settings, "ai_knowledge_allow_documents_to_embedding_provider", True)
    monkeypatch.setattr(ai_core.ai_settings, "ai_knowledge_allow_queries_to_embedding_provider", True)

    result = ai_core.get_ai_knowledge_status(organization_id, principal, session)

    assert principal.authorized_organization == organization_id
    assert result["documents"] == 3
    assert result["ready_documents"] == 2
    assert result["chunks"] == 5
    assert result["semantic_retrieval_available"] is True
    assert result["semantic_retrieval_blockers"] == []
    assert result["embedding_providers_registered"] == [provider.name]
    assert "text" not in result
    assert "source_title" not in result

    vector_query = session.statements[-1]
    compiled = vector_query.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "ai_knowledge_chunks.organization_id" in sql
    assert "ai_knowledge_documents.organization_id" in sql
    assert "ai_knowledge_documents.processing_status" in sql
    assert "ai_knowledge_documents.embedding_provider" in sql
    assert "ai_knowledge_documents.embedding_model" in sql
    assert list(compiled.params.values()).count(organization_id) == 2
