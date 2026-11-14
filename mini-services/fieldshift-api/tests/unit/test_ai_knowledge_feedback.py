"""AI knowledge/feedback safety tests; no database fixtures or live provider calls."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from app.api.v1 import ai_core
from app.core.errors import ValidationFailed
from app.db.models import Base
from app.intelligence.orchestration import knowledge
from app.intelligence.orchestration.contracts import AIRequest
from app.intelligence.orchestration import retention


class FakeRows:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *, chunks=(), rows=(), scalar=None):
        self.chunks = list(chunks)
        self.rows = list(rows)
        self.scalar_value = scalar
        self.added = []
        self.deleted = []
        self.commits = 0
        self.flushes = 0
        self.closed = False
        self.last_statement = None

    def scalars(self, statement):
        self.last_statement = statement
        return FakeRows(self.chunks)

    def execute(self, statement):
        self.last_statement = statement
        return FakeRows(self.rows)

    def scalar(self, statement):
        self.last_statement = statement
        return self.scalar_value

    def add(self, item):
        self.added.append(item)

    def delete(self, item):
        self.deleted.append(item)

    def commit(self):
        self.commits += 1

    def refresh(self, _item):
        return None

    def flush(self):
        self.flushes += 1

    def close(self):
        self.closed = True


class FakeEmbeddingProvider:
    name = "mock-embedding"
    model = "mock-v1"

    def __init__(self, vectors=None):
        self.vectors = vectors
        self.calls = []

    async def embed(self, texts):
        self.calls.append(list(texts))
        if callable(self.vectors):
            return self.vectors(texts)
        return self.vectors or [[0.6, 0.8] for _ in texts]


def _chunk(text="safe text", *, organization_id=None, embedding=None, dimension=None, updated=None):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        document_id=uuid4(),
        chunk_index=0,
        text=text,
        embedding=embedding,
        embedding_dimension=dimension,
        embedding_updated_at=updated,
    )


def _document(organization_id, *, provider="mock-embedding", model="mock-v1", source_updated=None):
    return SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        source_title="Reviewed agronomy note",
        publisher="Test publisher",
        source_reference="https://example.invalid/reviewed-note",
        license_name="Internal permission",
        document_version="v1",
        language="en",
        jurisdiction="test-region",
        crop_codes=["maize"],
        topics=["soil"],
        published_at=date(2026, 1, 1),
        source_updated_at=source_updated,
        processing_status="ready",
        embedding_provider=provider,
        embedding_model=model,
    )


def test_chunking_hard_bounds_and_zero_overlap_makes_progress(monkeypatch):
    monkeypatch.setattr(knowledge, "MAX_DOCUMENT_CHARS", 2_000)
    monkeypatch.setattr(knowledge, "MAX_CHUNK_CHARS", 200)
    monkeypatch.setattr(knowledge, "CHUNK_OVERLAP_CHARS", 0)
    chunks = knowledge.chunk_document("x" * 503)
    assert [len(chunk) for chunk in chunks] == [200, 200, 103]
    assert "".join(chunks) == "x" * 503
    assert max(map(len, chunks)) <= 200


def test_chunking_keeps_hard_bounds_with_overlap_and_long_unbroken_text(monkeypatch):
    monkeypatch.setattr(knowledge, "MAX_DOCUMENT_CHARS", 2_000)
    monkeypatch.setattr(knowledge, "MAX_CHUNK_CHARS", 200)
    monkeypatch.setattr(knowledge, "CHUNK_OVERLAP_CHARS", 40)
    chunks = knowledge.chunk_document("y" * 503)
    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 200 for chunk in chunks)
    assert chunks[0] == "y" * 200


def test_embedding_validation_and_cosine_are_safe_from_numeric_overflow():
    score = knowledge.cosine_similarity([1e308, 1e308], [1e308, -1e308])
    assert abs(score) < 1e-12
    assert knowledge.cosine_similarity([1e308, 0.0], [1e308, 1e308]) == pytest.approx(2**-0.5)
    with pytest.raises(knowledge.KnowledgeError):
        knowledge.validate_embedding([10**10_000])
    with pytest.raises(knowledge.KnowledgeError):
        knowledge.validate_embedding([float("inf")])


def test_full_embedding_batches_validate_before_mutating_any_chunk():
    chunks = [
        _chunk("a", embedding=[9.0], dimension=1),
        _chunk("b", embedding=[8.0], dimension=1),
    ]
    provider = FakeEmbeddingProvider([[1.0, 0.0], [0.0, 1.0, 0.0]])
    document = SimpleNamespace(id=uuid4(), organization_id=uuid4(), processing_status="pending_embedding")
    db = FakeSession(chunks=chunks)

    with pytest.raises(knowledge.KnowledgeError, match="dimension"):
        asyncio.run(knowledge.embed_pending_document(db, document, provider=provider))

    assert [chunk.embedding for chunk in chunks] == [[9.0], [8.0]]
    assert [chunk.embedding_dimension for chunk in chunks] == [1, 1]
    assert all(chunk.embedding_updated_at is None for chunk in chunks)
    assert document.processing_status == "failed"
    assert document.failure_category == "embedding_contract_mismatch"


def test_embedding_calls_are_bounded_and_rows_change_only_after_all_batches_succeed():
    chunks = [_chunk("z" * 1000) for _ in range(40)]
    provider = FakeEmbeddingProvider()
    document = SimpleNamespace(id=uuid4(), organization_id=uuid4(), processing_status="pending_embedding")
    db = FakeSession(chunks=chunks)

    count = asyncio.run(knowledge.embed_pending_document(db, document, provider=provider))

    assert count == 40
    assert len(provider.calls) <= knowledge.MAX_EMBEDDING_PROVIDER_CALLS
    assert all(len(batch) <= knowledge.MAX_EMBEDDING_BATCH_SIZE for batch in provider.calls)
    assert all(sum(map(len, batch)) <= knowledge.MAX_EMBEDDING_BATCH_CHARS for batch in provider.calls)
    assert all(chunk.embedding == [0.6, 0.8] and chunk.embedding_dimension == 2 for chunk in chunks)
    assert all(chunk.embedding_updated_at is not None for chunk in chunks)
    assert document.processing_status == "ready"
    assert document.embedding_provider == provider.name
    assert document.embedding_model == provider.model


def test_embedding_provider_timeout_has_safe_error_and_no_row_mutation(monkeypatch):
    class SlowProvider(FakeEmbeddingProvider):
        async def embed(self, texts):
            self.calls.append(list(texts))
            await asyncio.sleep(0.05)
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(knowledge, "EMBEDDING_PROVIDER_TIMEOUT_SECONDS", 0.001)
    chunk = _chunk("slow", embedding=[5.0], dimension=1)
    document = SimpleNamespace(id=uuid4(), organization_id=uuid4(), processing_status="pending_embedding")
    db = FakeSession(chunks=[chunk])
    with pytest.raises(knowledge.KnowledgeError, match="provider failed") as exc:
        asyncio.run(knowledge.embed_pending_document(db, document, provider=SlowProvider()))
    assert "SlowProvider" not in str(exc.value)
    assert chunk.embedding == [5.0]
    assert chunk.embedding_dimension == 1
    assert chunk.embedding_updated_at is None
    assert document.failure_category == "embedding_provider_failure"


def test_query_embedding_hides_provider_exception_details():
    class SecretFailureProvider(FakeEmbeddingProvider):
        async def embed(self, texts):
            raise RuntimeError("credential=do-not-return-this")

    with pytest.raises(knowledge.EmbeddingProviderFailure) as exc:
        asyncio.run(knowledge.embed_query("bounded query", provider=SecretFailureProvider()))
    assert "credential" not in str(exc.value)
    assert "do-not-return-this" not in str(exc.value)


def test_retrieval_requires_tenant_model_dimension_and_fresh_source_metadata():
    organization_id = uuid4()
    foreign_org = uuid4()
    now = datetime(2026, 10, 1, tzinfo=UTC)
    good_chunk = _chunk(
        "current reviewed passage", organization_id=organization_id, embedding=[1.0, 0.0],
        dimension=2, updated=now - timedelta(days=1),
    )
    good_doc = _document(organization_id, source_updated=date(2026, 9, 1))
    rows = [(good_chunk, good_doc)]
    rows.extend([
        (_chunk(organization_id=organization_id, embedding=[1.0, 0.0], dimension=2, updated=now),
         _document(organization_id, provider="other-provider")),
        (_chunk(organization_id=organization_id, embedding=[1.0, 0.0], dimension=2, updated=now),
         _document(organization_id, model="other-model")),
        (_chunk(organization_id=foreign_org, embedding=[1.0, 0.0], dimension=2, updated=now),
         _document(foreign_org)),
        (_chunk(organization_id=organization_id, embedding=[1.0, 0.0], dimension=2,
                updated=now - timedelta(days=366)), _document(organization_id)),
        (_chunk(organization_id=organization_id, embedding=[1.0, 0.0], dimension=2, updated=now),
         _document(organization_id, source_updated=date(2026, 10, 2))),
        (_chunk(organization_id=organization_id, embedding=[1.0, 0.0], dimension=1, updated=now),
         _document(organization_id)),
    ])
    db = FakeSession(rows=rows)

    passages = knowledge.search_knowledge(
        db,
        organization_id=organization_id,
        query_embedding=[1.0, 0.0],
        embedding_provider="mock-embedding",
        embedding_model="mock-v1",
        now=now,
    )

    assert len(passages) == 1
    assert passages[0].document_id == good_doc.id
    rendered = passages[0].as_dict()
    assert rendered["source"]["version"] == "v1"
    assert rendered["source"]["license"] == "Internal permission"
    assert rendered["source"]["embedding_model"] == "mock-v1"
    assert rendered["source"]["source_updated_at"] == "2026-09-01"
    sql = str(db.last_statement.compile(dialect=postgresql.dialect()))
    assert "embedding_provider" in sql and "embedding_model" in sql
    assert "embedding_dimension" in sql and "embedding_updated_at" in sql


def test_default_embedding_registry_has_no_implicit_provider():
    registry = knowledge.EmbeddingProviderRegistry()
    assert registry.names() == ()
    assert registry.get("unreviewed") is None


def test_feedback_contract_keeps_legacy_ratings_and_requires_explicit_consent():
    for rating in ("helpful", "needs_improvement"):
        payload = ai_core.AIFeedbackRequest.model_validate({
            "trace_id": str(uuid4()), "rating": rating, "quality_review_consent": True,
        })
        assert payload.rating == rating
    with pytest.raises(ValidationError):
        ai_core.AIFeedbackRequest.model_validate({
            "trace_id": str(uuid4()), "rating": "helpful", "quality_review_consent": False,
        })


def test_initial_feedback_supports_each_lifecycle_state_and_requires_outcome_report(monkeypatch):
    for state in ("accepted", "rejected", "modified", "implemented", "outcome_reported"):
        payload = ai_core.AIFeedbackRequest.model_validate({
            "trace_id": str(uuid4()), "rating": "helpful", "lifecycle_state": state,
            "quality_review_consent": True,
        })
        assert payload.lifecycle_state == state
    payload = ai_core.AIFeedbackRequest.model_validate({
        "trace_id": str(uuid4()), "rating": "helpful", "lifecycle_state": "outcome_reported",
        "quality_review_consent": True,
    })
    monkeypatch.setattr(ai_core, "check_rate_limit", lambda *_args: None)
    with pytest.raises(ValidationFailed, match="outcome report"):
        ai_core.submit_ai_feedback(
            payload,
            SimpleNamespace(state=SimpleNamespace(request_id="request-test")),
            SimpleNamespace(id=uuid4()),
            None,
        )
    outcome = ai_core.AIFeedbackRequest.model_validate({
        "trace_id": str(uuid4()), "rating": "helpful", "lifecycle_state": "outcome_reported",
        "outcome": "improved", "quality_review_consent": True,
    })
    assert outcome.lifecycle_state == "outcome_reported" and outcome.outcome == "improved"


def test_feedback_submission_records_consent_and_unverified_user_outcome(monkeypatch):
    trace_id, user_id, organization_id = uuid4(), uuid4(), uuid4()
    trace = SimpleNamespace(
        id=trace_id, user_id=user_id, organization_id=organization_id, field_id=None,
        conversation_id=None, evidence_references=[{"label": "soil"}],
        provider="mock-provider", model="mock-model",
    )
    principal = SimpleNamespace(id=user_id, require_member_of=lambda org: org == organization_id)
    db = FakeSession(scalar=trace)
    monkeypatch.setattr(ai_core, "check_rate_limit", lambda *_args: None)
    request = SimpleNamespace(state=SimpleNamespace(request_id="test-request"))
    payload = ai_core.AIFeedbackRequest.model_validate({
        "trace_id": str(trace_id), "rating": "needs_improvement", "outcome": "improved",
        "quality_review_consent": True, "comment": "  reviewed  ",
    })

    response = ai_core.submit_ai_feedback(payload, request, principal, db)
    saved = db.added[0]

    assert response["status"] == "recorded"
    assert response["lifecycle_state"] == saved.lifecycle_state == "accepted"
    assert saved.quality_review_consent is True
    assert saved.consent_version == ai_core.FEEDBACK_CONSENT_VERSION
    assert saved.consented_at is not None
    assert saved.provenance["trace_id"] == str(trace_id)
    assert saved.outcome_verification_label == "unverified_user_reported"
    assert saved.rating == "needs_improvement"
    assert db.commits == 1


def test_owner_lifecycle_transition_is_timestamped_and_provenanced():
    feedback = SimpleNamespace(
        id=uuid4(), organization_id=uuid4(), lifecycle_state="accepted", outcome="improved",
        lifecycle_updated_at=None, lifecycle_updated_by=None,
        provenance={"lifecycle_events": [{"state": "accepted"}]},
        outcome_verification_label="unverified_user_reported", trace_id=uuid4(), rating="helpful",
        category=None, correction=None, comment=None, quality_review_consent=True,
        consent_version="ai-feedback-v1", consented_at=datetime.now(UTC), created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    manager_id = uuid4()
    manager = SimpleNamespace(
        id=manager_id,
        require_member_of=lambda organization_id: organization_id == feedback.organization_id,
    )
    db = FakeSession(scalar=feedback)
    payload = ai_core.AIFeedbackLifecycleRequest(lifecycle_state="modified", reason="Reviewed by agronomist")

    result = ai_core.update_ai_feedback_lifecycle(feedback.id, payload, manager, db)

    assert feedback.lifecycle_state == result["lifecycle_state"] == "modified"
    assert feedback.lifecycle_updated_at is not None
    assert feedback.lifecycle_updated_by == manager_id
    assert feedback.provenance["lifecycle_events"][-1]["from_state"] == "accepted"
    assert feedback.provenance["lifecycle_events"][-1]["actor_id"] == str(manager_id)
    assert feedback.provenance["lifecycle_events"][-1]["reason"] == "Reviewed by agronomist"
    assert result["outcome_verification_label"] == "unverified_user_reported"
    assert db.commits == 1
    statement = str(db.last_statement.compile(dialect=postgresql.dialect()))
    assert "ai_answer_feedback.user_id" in statement
    assert "FOR UPDATE" in statement


def test_feedback_list_and_delete_queries_are_scoped_to_authenticated_owner():
    user_id, other_user_id = uuid4(), uuid4()
    feedback = SimpleNamespace(
        id=uuid4(), trace_id=uuid4(), user_id=user_id, rating="helpful", category=None,
        correction=None, outcome=None, outcome_verification_label="unverified_user_reported",
        comment=None, lifecycle_state="accepted", lifecycle_updated_at=datetime.now(UTC),
        quality_review_consent=True, consent_version="ai-feedback-v1", consented_at=datetime.now(UTC),
        created_at=datetime.now(UTC), expires_at=datetime.now(UTC) + timedelta(days=10),
    )
    principal = SimpleNamespace(id=user_id)
    db = FakeSession(chunks=[feedback], scalar=feedback)
    listed = ai_core.list_own_ai_feedback(limit=50, offset=0, principal=principal, db=db)
    assert len(listed) == 1
    compiled = str(db.last_statement.compile(dialect=postgresql.dialect()))
    assert "ai_answer_feedback.user_id" in compiled
    assert "expires_at" in compiled

    ai_core.delete_own_ai_feedback(feedback.id, principal, db)
    compiled = str(db.last_statement.compile(dialect=postgresql.dialect()))
    assert "ai_answer_feedback.user_id" in compiled
    assert db.deleted == [feedback]
    assert db.commits == 1
    assert other_user_id != user_id


def test_conversation_history_exposes_trace_id_from_persisted_engine(monkeypatch):
    user_id, field_id, conversation_id, trace_id = uuid4(), uuid4(), uuid4(), uuid4()
    session = SimpleNamespace(
        id=conversation_id, owner_user_id=user_id, field_id=field_id, updated_at=datetime.now(UTC),
    )
    message = SimpleNamespace(
        id=uuid4(), role="assistant", answer="grounded", question=None,
        engine={"trace_id": str(trace_id), "mode": "rules"},
        evidence=[{"label": "soil", "claim": "stored"}], created_at=datetime.now(UTC),
    )
    db = FakeSession(chunks=[message], scalar=session)
    monkeypatch.setattr(ai_core, "get_field_for_principal", lambda *_args: None)
    result = ai_core.get_ai_conversation_messages(
        conversation_id, SimpleNamespace(id=user_id), db,
    )
    assert result[0].trace_id == trace_id
    assert result[0].engine["trace_id"] == str(trace_id)
    assert result[0].evidence[0]["trace_id"] == str(trace_id)


def test_stream_materializes_authorized_result_and_closes_db_before_response(monkeypatch):
    principal = SimpleNamespace(id=uuid4())
    db = FakeSession()
    async def execute(_db, _principal, _payload, *, request_id):
        assert request_id == "request-7"
        return SimpleNamespace(
            answer="answer",
            model_dump=lambda mode: {"status": "answered", "answer": "answer"},
        )
    monkeypatch.setattr(ai_core, "execute_ai_request", execute)
    monkeypatch.setattr(ai_core, "check_rate_limit", lambda *_args: None)
    request = SimpleNamespace(state=SimpleNamespace(request_id="request-7"))

    response = asyncio.run(ai_core.stream_ai_request(
        AIRequest(question="Summarize stored field evidence", field_id=None), request, principal, db,
    ))

    assert db.closed is True
    assert response.media_type == "text/event-stream"
    async def collect():
        return "".join([part async for part in response.body_iterator]).encode()
    body = asyncio.run(collect())
    assert b"event: meta" in body and b"event: chunk" in body and b"event: done" in body


def test_default_provider_registry_is_unmodified_by_import():
    # The application registry must stay empty until an explicitly reviewed
    # adapter is installed; this test never makes network calls.
    assert knowledge.embedding_provider_registry.names() == ()


def test_feedback_and_knowledge_orm_schema_has_migration_contract_columns():
    feedback = Base.metadata.tables["ai_answer_feedback"]
    chunks = Base.metadata.tables["ai_knowledge_chunks"]
    documents = Base.metadata.tables["ai_knowledge_documents"]
    assert {
        "consented_at", "lifecycle_state", "lifecycle_updated_at", "lifecycle_updated_by",
        "provenance", "outcome_verification_label",
    }.issubset(feedback.columns.keys())
    assert "embedding_updated_at" in chunks.columns
    assert "uq_ai_knowledge_document_org_id" in {item.name for item in documents.constraints}
    assert "fk_ai_knowledge_chunk_org_document" in {item.name for item in chunks.constraints}


def test_retention_is_batch_bounded_timezone_safe_and_does_not_commit(monkeypatch):
    class RetentionResult(FakeRows):
        rowcount = 1

    class RetentionSession:
        def __init__(self):
            self.selects = 0
            self.deletes = 0
            self.commits = 0

        def scalars(self, _statement):
            self.selects += 1
            return RetentionResult([uuid4()])

        def execute(self, _statement):
            self.deletes += 1
            return RetentionResult([])

    monkeypatch.setattr(retention.ai_settings, "ai_trace_retention_days", 90)
    monkeypatch.setattr(retention.ai_settings, "ai_conversation_retention_days", 365)
    db = RetentionSession()
    counts = retention.purge_expired_ai_data(db, now=datetime(2026, 10, 1), batch_size=10)
    assert counts == {"feedback_deleted": 1, "traces_deleted": 1, "conversations_deleted": 1}
    assert db.selects == 3 and db.deletes == 3 and db.commits == 0
    with pytest.raises(ValueError, match="batch_size"):
        retention.purge_expired_ai_data(db, batch_size=retention.MAX_PURGE_BATCH + 1)
