"""Rights-aware, tenant-scoped knowledge ingestion and retrieval primitives.

No embedding vendor is assumed. Documents remain pending until a reviewed
EmbeddingProvider populates vectors; retrieval never silently falls back to
model memory or claims keyword matching is semantic search.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
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


class KnowledgeError(ValueError):
    """Expected ingestion/retrieval policy or input failure."""


class EmbeddingProvider(Protocol):
    name: str
    model: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingProviderRegistry:
    """Explicit allowlist; empty by default until an embedding adapter is reviewed."""

    def __init__(self) -> None:
        self._providers: dict[str, EmbeddingProvider] = {}

    def register(self, provider: EmbeddingProvider) -> None:
        if not provider.name or provider.name in self._providers:
            raise ValueError("embedding provider name is empty or already registered")
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
    """Split UTF-8 text on paragraph/sentence boundaries with fixed overlap."""
    if MAX_CHUNK_CHARS < 200 or not 0 <= CHUNK_OVERLAP_CHARS < MAX_CHUNK_CHARS:
        raise KnowledgeError("knowledge chunk settings are inconsistent")
    text = clean_document_text(content)
    pieces = [part.strip() for part in re.split(r"\n{2,}|(?<=[.!?])\s+", text) if part.strip()]
    chunks: list[str] = []
    current = ""

    def emit(value: str) -> None:
        cleaned = value.strip()
        if cleaned:
            chunks.append(cleaned)

    for piece in pieces:
        while len(piece) > MAX_CHUNK_CHARS:
            if current:
                emit(current)
                current = ""
            cut = piece.rfind(" ", 0, MAX_CHUNK_CHARS + 1)
            cut = cut if cut > 0 else MAX_CHUNK_CHARS
            emit(piece[:cut])
            piece = piece[max(1, cut - CHUNK_OVERLAP_CHARS):].lstrip()
        candidate = f"{current}\n{piece}" if current else piece
        if len(candidate) <= MAX_CHUNK_CHARS:
            current = candidate
            continue
        emit(current)
        overlap = current[-CHUNK_OVERLAP_CHARS:].strip()
        current = f"{overlap}\n{piece}" if overlap else piece
    emit(current)
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
    try:
        vectors = await provider.embed([chunk.text for chunk in chunks])
    except Exception as exc:  # provider-specific details are never persisted
        document.processing_status = "failed"
        document.failure_category = "embedding_provider_failure"
        db.flush()
        raise KnowledgeError("the configured embedding provider failed") from exc
    if len(vectors) != len(chunks):
        document.processing_status = "failed"
        document.failure_category = "embedding_contract_mismatch"
        db.flush()
        raise KnowledgeError("embedding provider returned an unexpected vector count")
    expected_dimension: int | None = None
    for chunk, vector in zip(chunks, vectors, strict=True):
        cleaned = validate_embedding(vector, expected_dimension=expected_dimension)
        expected_dimension = len(cleaned)
        chunk.embedding = cleaned
        chunk.embedding_dimension = len(cleaned)
    document.embedding_provider = provider.name[:100]
    document.embedding_model = provider.model[:160]
    document.processing_status = "ready"
    document.failure_category = None
    db.flush()
    return len(chunks)


def validate_embedding(vector: list[float], *, expected_dimension: int | None = None) -> list[float]:
    if not isinstance(vector, list) or not 1 <= len(vector) <= MAX_EMBEDDING_DIMENSIONS:
        raise KnowledgeError("embedding dimension is outside the supported bound")
    if expected_dimension is not None and len(vector) != expected_dimension:
        raise KnowledgeError("embedding dimension does not match the indexed model")
    cleaned: list[float] = []
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise KnowledgeError("embedding must contain finite numeric values")
        cleaned.append(float(value))
    if not any(value != 0 for value in cleaned):
        raise KnowledgeError("zero vectors cannot be searched")
    return cleaned


def cosine_similarity(left: list[float], right: list[float]) -> float:
    a = validate_embedding(left)
    b = validate_embedding(right, expected_dimension=len(a))
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        raise KnowledgeError("zero vectors cannot be searched")
    return dot / (norm_a * norm_b)


def search_knowledge(
    db: Session,
    *,
    organization_id: UUID,
    query_embedding: list[float],
    language: str | None = None,
    jurisdiction: str | None = None,
    crop_code: str | None = None,
    top_k: int = 8,
    min_similarity: float = 0.72,
    max_candidates: int = MAX_SEARCH_CANDIDATES,
) -> list[KnowledgePassage]:
    """Exact cosine scan of a bounded, organization-filtered Postgres candidate set."""
    query = validate_embedding(query_embedding)
    if not 1 <= top_k <= 20 or not 1 <= max_candidates <= MAX_SEARCH_CANDIDATES:
        raise KnowledgeError("retrieval limits are outside the supported bound")
    if not -1.0 <= min_similarity <= 1.0:
        raise KnowledgeError("similarity threshold must be between -1 and 1")

    statement = (
        select(AIKnowledgeChunk, AIKnowledgeDocument)
        .join(AIKnowledgeDocument, AIKnowledgeDocument.id == AIKnowledgeChunk.document_id)
        .where(
            AIKnowledgeChunk.organization_id == organization_id,
            AIKnowledgeDocument.organization_id == organization_id,
            AIKnowledgeDocument.processing_status == "ready",
            AIKnowledgeChunk.embedding.is_not(None),
        )
        .order_by(AIKnowledgeChunk.created_at.desc(), AIKnowledgeChunk.id)
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
        vector = chunk.embedding
        if not isinstance(vector, list) or len(vector) != len(query):
            continue
        score = cosine_similarity(query, vector)
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
        ))
    return sorted(passages, key=lambda item: (-item.cosine_similarity, str(item.chunk_id)))[:top_k]
