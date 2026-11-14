"""Rights-aware, tenant-scoped knowledge ingestion and retrieval primitives.

No embedding vendor is assumed. Documents remain pending until a reviewed
EmbeddingProvider populates vectors; retrieval never silently falls back to
model memory or claims keyword matching is semantic search.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models_orchestration import AIKnowledgeChunk, AIKnowledgeDocument
from app.intelligence.config import ai_settings

MAX_DOCUMENT_CHARS = ai_settings.ai_knowledge_max_document_chars
MAX_CHUNK_CHARS = ai_settings.ai_knowledge_chunk_chars
CHUNK_OVERLAP_CHARS = ai_settings.ai_knowledge_chunk_overlap_chars
MAX_DOCUMENT_CHUNKS = 300
MAX_SEARCH_CANDIDATES = 500
MAX_EMBEDDING_DIMENSIONS = 4096
MAX_EMBEDDING_BATCH_SIZE = 32
MAX_EMBEDDING_BATCH_CHARS = 16_000
MAX_EMBEDDING_PROVIDER_CALLS = 16
EMBEDDING_PROVIDER_TIMEOUT_SECONDS = 30
MAX_DOCUMENT_EMBEDDING_SECONDS = 120
MAX_EMBEDDING_AGE = timedelta(days=365)


class KnowledgeError(ValueError):
    """Expected ingestion/retrieval policy or input failure."""


class EmbeddingProviderFailure(KnowledgeError):
    """A normalized provider timeout or call failure with no vendor details."""


class _EmbeddingProviderCallFailed(Exception):
    """Private sentinel that prevents provider exception details from escaping."""


class EmbeddingProvider(Protocol):
    name: str
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingProviderRegistry:
    """Explicit allowlist; empty by default until an embedding adapter is reviewed."""

    def __init__(self) -> None:
        self._providers: dict[str, EmbeddingProvider] = {}

    def register(self, provider: EmbeddingProvider) -> None:
        if (
            not isinstance(provider.name, str)
            or not provider.name.strip()
            or len(provider.name) > 100
            or not isinstance(provider.model, str)
            or not provider.model.strip()
            or len(provider.model) > 160
            or provider.name in self._providers
        ):
            raise ValueError("embedding provider metadata is invalid or its name is already registered")
        self._providers[provider.name] = provider

    def get(self, name: str) -> EmbeddingProvider | None:
        return self._providers.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))


embedding_provider_registry = EmbeddingProviderRegistry()


@dataclass(frozen=True)
class KnowledgePassage:
    citation_id: str
    chunk_id: UUID
    document_id: UUID
    text: str
    title: str
    publisher: str
    source_reference: str
    license_name: str
    document_version: str
    language: str
    jurisdiction: str
    crop_codes: tuple[str, ...]
    topics: tuple[str, ...]
    cosine_similarity: float
    published_at: date | None = None
    source_updated_at: date | None = None
    embedding_provider: str = ""
    embedding_model: str = ""
    embedding_updated_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "chunk_id": str(self.chunk_id),
            "document_id": str(self.document_id),
            "text": self.text,
            "source": {
                "title": self.title,
                "publisher": self.publisher,
                "reference": self.source_reference,
                "license": self.license_name,
                "version": self.document_version,
                "language": self.language,
                "jurisdiction": self.jurisdiction,
                "published_at": self.published_at.isoformat() if self.published_at else None,
                "source_updated_at": self.source_updated_at.isoformat() if self.source_updated_at else None,
                "embedding_provider": self.embedding_provider,
                "embedding_model": self.embedding_model,
                "embedding_updated_at": self.embedding_updated_at.isoformat() if self.embedding_updated_at else None,
            },
            "crop_codes": list(self.crop_codes),
            "topics": list(self.topics),
            "cosine_similarity": round(self.cosine_similarity, 6),
        }


def clean_document_text(content: str) -> str:
    if not isinstance(content, str):
        raise KnowledgeError("document text must be a string")
    value = content.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    value = "\n".join(line.rstrip() for line in value.splitlines()).strip()
    if not value:
        raise KnowledgeError("document text is empty")
    if len(value) > MAX_DOCUMENT_CHARS:
        raise KnowledgeError("document exceeds the text ingestion budget")
    return value


def chunk_document(content: str) -> list[str]:
    """Split normalized text at natural boundaries without exceeding the hard limit."""
    if MAX_CHUNK_CHARS < 200 or not 0 <= CHUNK_OVERLAP_CHARS < MAX_CHUNK_CHARS:
        raise KnowledgeError("knowledge chunk settings are inconsistent")
    text = clean_document_text(content)
    chunks: list[str] = []
    effective_overlap = min(CHUNK_OVERLAP_CHARS, MAX_CHUNK_CHARS // 2)
    start = 0
    while start < len(text):
        hard_end = min(len(text), start + MAX_CHUNK_CHARS)
        end = hard_end
        if hard_end < len(text):
            # Prefer a paragraph, sentence, or whitespace boundary in the final
            # quarter of the window. Falling back to hard_end handles long tokens.
            floor = start + max(1, MAX_CHUNK_CHARS * 3 // 4)
            candidates = [
                text.rfind("\n\n", floor, hard_end),
                text.rfind("\n", floor, hard_end),
                text.rfind(". ", floor, hard_end) + 1,
                text.rfind("! ", floor, hard_end) + 1,
                text.rfind("? ", floor, hard_end) + 1,
                text.rfind(" ", floor, hard_end),
            ]
            boundary = max(candidates)
            if boundary >= floor:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            if len(chunk) > MAX_CHUNK_CHARS:
                raise KnowledgeError("knowledge chunk exceeds the configured hard limit")
            chunks.append(chunk)
            if len(chunks) > MAX_DOCUMENT_CHUNKS:
                raise KnowledgeError("document chunk count is outside the supported bound")
        if end >= len(text):
            break
        next_start = end - effective_overlap
        # With zero overlap, continue exactly at the boundary; for very small
        # boundary positions, force progress rather than looping.
        start = max(start + 1, next_start)
    if not chunks or len(chunks) > MAX_DOCUMENT_CHUNKS:
        raise KnowledgeError("document chunk count is outside the supported bound")
    return chunks


def _tag_list(values: list[str], *, max_items: int = 20) -> list[str]:
    result: list[str] = []
    for value in values[:max_items]:
        if not isinstance(value, str):
            continue
        normalized = re.sub(r"[^a-z0-9_-]+", "_", value.strip().casefold()).strip("_-")
        if normalized and normalized not in result:
            result.append(normalized[:40])
    return result


def create_knowledge_document(
    db: Session,
    *,
    organization_id: UUID,
    uploaded_by: UUID,
    source_title: str,
    publisher: str,
    source_reference: str,
    jurisdiction: str,
    language: str,
    crop_codes: list[str],
    topics: list[str],
    document_version: str,
    license_name: str,
    usage_restrictions: str,
    content: str,
    rights_confirmed: bool,
    published_at: Any | None = None,
    source_updated_at: Any | None = None,
) -> AIKnowledgeDocument:
    """Persist text chunks only after a human explicitly attests usage rights."""
    if rights_confirmed is not True:
        raise KnowledgeError("rights confirmation is required before ingestion")
    normalized = clean_document_text(content)
    if not source_title.strip() or not publisher.strip() or not source_reference.strip():
        raise KnowledgeError("title, publisher and source reference are required")
    if not license_name.strip() or not usage_restrictions.strip():
        raise KnowledgeError("license and usage restrictions are required")
    if not jurisdiction.strip() or not language.strip() or not document_version.strip():
        raise KnowledgeError("jurisdiction, language and version are required")

    chunks = chunk_document(normalized)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    duplicate = db.scalar(select(AIKnowledgeDocument.id).where(
        AIKnowledgeDocument.organization_id == organization_id,
        AIKnowledgeDocument.content_hash == digest,
        AIKnowledgeDocument.document_version == document_version.strip()[:100],
    ))
    if duplicate is not None:
        raise KnowledgeError("this document version is already ingested for the organization")

    from datetime import UTC, datetime

    document = AIKnowledgeDocument(
        organization_id=organization_id,
        uploaded_by=uploaded_by,
        source_title=source_title.strip()[:300],
        publisher=publisher.strip()[:200],
        source_reference=source_reference.strip()[:1000],
        published_at=published_at,
        source_updated_at=source_updated_at,
        jurisdiction=jurisdiction.strip()[:100],
        language=language.strip().casefold()[:12],
        crop_codes=_tag_list(crop_codes),
        topics=_tag_list(topics),
        document_version=document_version.strip()[:100],
        license_name=license_name.strip()[:200],
        usage_restrictions=usage_restrictions.strip()[:5000],
        rights_confirmed_by=uploaded_by,
        rights_confirmed_at=datetime.now(UTC),
        content_hash=digest,
        character_count=len(normalized),
        processing_status="pending_embedding",
    )
    db.add(document)
    db.flush()
    for index, chunk_text in enumerate(chunks):
        db.add(AIKnowledgeChunk(
            organization_id=organization_id,
            document_id=document.id,
            chunk_index=index,
            text=chunk_text,
            text_hash=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest(),
        ))
    db.flush()
    return document


async def embed_pending_document(
    db: Session,
    document: AIKnowledgeDocument,
    *,
    provider: EmbeddingProvider,
) -> int:
    """Embed one explicitly selected document; no raw text leaves this adapter seam."""
    if document.processing_status not in ("pending_embedding", "failed"):
        raise KnowledgeError("document is not awaiting embedding")
    chunks = db.scalars(
        select(AIKnowledgeChunk)
        .where(
            AIKnowledgeChunk.document_id == document.id,
            AIKnowledgeChunk.organization_id == document.organization_id,
        )
        .order_by(AIKnowledgeChunk.chunk_index)
    ).all()
    if not chunks:
        raise KnowledgeError("document has no content chunks")

    def mark_failed(category: str) -> None:
        document.processing_status = "failed"
        document.failure_category = category
        db.flush()

    if (
        not isinstance(provider.name, str)
        or not provider.name.strip()
        or len(provider.name) > 100
        or not isinstance(provider.model, str)
        or not provider.model.strip()
        or len(provider.model) > 160
    ):
        mark_failed("embedding_contract_mismatch")
        raise KnowledgeError("the configured embedding provider metadata is invalid")

    texts = [chunk.text for chunk in chunks]
    batches: list[list[str]] = []
    batch: list[str] = []
    batch_chars = 0
    for text in texts:
        if not isinstance(text, str) or not text or len(text) > MAX_EMBEDDING_BATCH_CHARS:
            mark_failed("embedding_contract_mismatch")
            raise KnowledgeError("a knowledge chunk exceeds the provider input bound")
        if batch and (
            len(batch) >= MAX_EMBEDDING_BATCH_SIZE
            or batch_chars + len(text) > MAX_EMBEDDING_BATCH_CHARS
        ):
            batches.append(batch)
            batch = []
            batch_chars = 0
        batch.append(text)
        batch_chars += len(text)
    if batch:
        batches.append(batch)
    if not batches or len(batches) > MAX_EMBEDDING_PROVIDER_CALLS:
        mark_failed("embedding_contract_mismatch")
        raise KnowledgeError("document requires too many bounded embedding batches")

    cleaned_vectors: list[list[float]] = []
    expected_dimension: int | None = None
    deadline = asyncio.get_running_loop().time() + MAX_DOCUMENT_EMBEDDING_SECONDS
    try:
        for current_batch in batches:
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise _EmbeddingProviderCallFailed()
                vectors = await asyncio.wait_for(
                    provider.embed(current_batch),
                    timeout=min(EMBEDDING_PROVIDER_TIMEOUT_SECONDS, remaining),
                )
            except Exception:
                raise _EmbeddingProviderCallFailed() from None
            if not isinstance(vectors, list) or len(vectors) != len(current_batch):
                raise KnowledgeError("embedding provider returned an unexpected vector count")
            for vector in vectors:
                cleaned = validate_embedding(vector, expected_dimension=expected_dimension)
                expected_dimension = len(cleaned)
                cleaned_vectors.append(cleaned)
    except _EmbeddingProviderCallFailed:
        mark_failed("embedding_provider_failure")
        raise EmbeddingProviderFailure("the configured embedding provider failed") from None
    except KnowledgeError:
        mark_failed("embedding_contract_mismatch")
        raise
    except Exception:  # provider-specific details are never persisted or returned
        mark_failed("embedding_provider_failure")
        raise EmbeddingProviderFailure("the configured embedding provider failed") from None
    if len(cleaned_vectors) != len(chunks):
        mark_failed("embedding_contract_mismatch")
        raise KnowledgeError("embedding provider returned an unexpected vector count")

    # No chunk row changes until every batch and every vector has passed.
    embedded_at = datetime.now(UTC)
    for chunk, vector in zip(chunks, cleaned_vectors, strict=True):
        chunk.embedding = vector
        chunk.embedding_dimension = len(vector)
        chunk.embedding_updated_at = embedded_at
    document.embedding_provider = provider.name[:100]
    document.embedding_model = provider.model[:160]
    document.processing_status = "ready"
    document.failure_category = None
    db.flush()
    return len(chunks)


async def embed_query(query: str, *, provider: EmbeddingProvider) -> list[float]:
    """Embed one bounded retrieval query and normalize all adapter failures."""
    if not isinstance(query, str) or not query.strip() or len(query) > 2_000:
        raise KnowledgeError("query text is outside the supported bound")
    try:
        vectors = await asyncio.wait_for(
            provider.embed([query.strip()]), timeout=EMBEDDING_PROVIDER_TIMEOUT_SECONDS
        )
    except Exception:
        raise EmbeddingProviderFailure("the configured embedding provider failed") from None
    if not isinstance(vectors, list) or len(vectors) != 1:
        raise EmbeddingProviderFailure("embedding provider returned an invalid vector response")
    try:
        return validate_embedding(vectors[0])
    except KnowledgeError:
        raise EmbeddingProviderFailure("embedding provider returned an invalid vector response") from None


def validate_embedding(vector: list[float], *, expected_dimension: int | None = None) -> list[float]:
    if not isinstance(vector, list) or not 1 <= len(vector) <= MAX_EMBEDDING_DIMENSIONS:
        raise KnowledgeError("embedding dimension is outside the supported bound")
    if expected_dimension is not None and len(vector) != expected_dimension:
        raise KnowledgeError("embedding dimension does not match the indexed model")
    cleaned: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise KnowledgeError("embedding must contain finite numeric values")
        try:
            converted = float(value)
        except (OverflowError, ValueError):
            raise KnowledgeError("embedding must contain finite numeric values") from None
        if not math.isfinite(converted):
            raise KnowledgeError("embedding must contain finite numeric values")
        cleaned.append(converted)
    if not any(value != 0 for value in cleaned):
        raise KnowledgeError("zero vectors cannot be searched")
    return cleaned


def cosine_similarity(left: list[float], right: list[float]) -> float:
    a = validate_embedding(left)
    b = validate_embedding(right, expected_dimension=len(a))
    # Scale before norm/dot calculations: finite float inputs can still overflow
    # when squared or multiplied directly.
    scale_a = max(abs(value) for value in a)
    scale_b = max(abs(value) for value in b)
    if scale_a == 0 or scale_b == 0:
        raise KnowledgeError("zero vectors cannot be searched")
    scaled_a = [value / scale_a for value in a]
    scaled_b = [value / scale_b for value in b]
    norm_a = math.hypot(*scaled_a)
    norm_b = math.hypot(*scaled_b)
    unit_a = [value / norm_a for value in scaled_a]
    unit_b = [value / norm_b for value in scaled_b]
    return sum(x * y for x, y in zip(unit_a, unit_b, strict=True))


def search_knowledge(
    db: Session,
    *,
    organization_id: UUID,
    query_embedding: list[float],
    embedding_provider: str,
    embedding_model: str,
    language: str | None = None,
    jurisdiction: str | None = None,
    crop_code: str | None = None,
    top_k: int = 8,
    min_similarity: float = 0.72,
    max_candidates: int = MAX_SEARCH_CANDIDATES,
    now: datetime | None = None,
    max_embedding_age: timedelta = MAX_EMBEDDING_AGE,
) -> list[KnowledgePassage]:
    """Exact cosine scan over fresh, same-model, same-tenant bounded candidates."""
    query = validate_embedding(query_embedding)
    if not 1 <= top_k <= 20 or not 1 <= max_candidates <= MAX_SEARCH_CANDIDATES:
        raise KnowledgeError("retrieval limits are outside the supported bound")
    if not -1.0 <= min_similarity <= 1.0:
        raise KnowledgeError("similarity threshold must be between -1 and 1")
    if (
        not isinstance(embedding_provider, str)
        or not embedding_provider.strip()
        or not isinstance(embedding_model, str)
        or not embedding_model.strip()
        or not isinstance(max_embedding_age, timedelta)
        or max_embedding_age <= timedelta(0)
    ):
        raise KnowledgeError("embedding retrieval metadata is invalid")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    else:
        current = current.astimezone(UTC)
    cutoff = current - max_embedding_age
    future_limit = current + timedelta(minutes=5)

    statement = (
        select(AIKnowledgeChunk, AIKnowledgeDocument)
        .join(AIKnowledgeDocument, AIKnowledgeDocument.id == AIKnowledgeChunk.document_id)
        .where(
            AIKnowledgeChunk.organization_id == organization_id,
            AIKnowledgeDocument.organization_id == organization_id,
            AIKnowledgeDocument.processing_status == "ready",
            AIKnowledgeDocument.embedding_provider == embedding_provider,
            AIKnowledgeDocument.embedding_model == embedding_model,
            AIKnowledgeChunk.embedding.is_not(None),
            AIKnowledgeChunk.embedding_dimension == len(query),
            AIKnowledgeChunk.embedding_updated_at >= cutoff,
            AIKnowledgeChunk.embedding_updated_at <= future_limit,
        )
        .order_by(AIKnowledgeChunk.embedding_updated_at.desc(), AIKnowledgeChunk.id)
        .limit(max_candidates)
    )
    if language:
        statement = statement.where(AIKnowledgeDocument.language == language.casefold())
    if jurisdiction:
        statement = statement.where(AIKnowledgeDocument.jurisdiction == jurisdiction)
    if crop_code:
        statement = statement.where(AIKnowledgeDocument.crop_codes.contains([crop_code.casefold()]))

    passages: list[KnowledgePassage] = []
    for chunk, document in db.execute(statement).all():
        if (
            chunk.organization_id != organization_id
            or document.organization_id != organization_id
            or document.embedding_provider != embedding_provider
            or document.embedding_model != embedding_model
            or chunk.embedding_dimension != len(query)
        ):
            continue
        embedded_at = chunk.embedding_updated_at
        if not isinstance(embedded_at, datetime):
            continue
        if embedded_at.tzinfo is None:
            embedded_at = embedded_at.replace(tzinfo=UTC)
        else:
            embedded_at = embedded_at.astimezone(UTC)
        if embedded_at < cutoff or embedded_at > future_limit:
            continue
        if document.source_updated_at and embedded_at.date() < document.source_updated_at:
            continue
        vector = chunk.embedding
        if not isinstance(vector, list) or len(vector) != len(query):
            continue
        try:
            score = cosine_similarity(query, vector)
        except KnowledgeError:
            continue
        if score < min_similarity:
            continue
        passages.append(KnowledgePassage(
            citation_id=f"K-{str(document.id)[:8]}-{chunk.chunk_index}",
            chunk_id=chunk.id,
            document_id=document.id,
            text=chunk.text,
            title=document.source_title,
            publisher=document.publisher,
            source_reference=document.source_reference,
            license_name=document.license_name,
            document_version=document.document_version,
            language=document.language,
            jurisdiction=document.jurisdiction,
            crop_codes=tuple(document.crop_codes or []),
            topics=tuple(document.topics or []),
            cosine_similarity=score,
            published_at=document.published_at,
            source_updated_at=document.source_updated_at,
            embedding_provider=document.embedding_provider,
            embedding_model=document.embedding_model,
            embedding_updated_at=embedded_at,
        ))
    return sorted(passages, key=lambda item: (-item.cosine_similarity, str(item.chunk_id)))[:top_k]
