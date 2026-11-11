"""Central recommendation registry.

Every product suggestion flows from this registry: domain modules register
generators via the `@registry.generator("domain")` decorator, and a refresh
runs ALL of them against ONE prebuilt context (evidence pack + statistical
anomalies are computed once per field and shared — generators never re-query
the evidence).

Isolation contract: one generator failing must never break the refresh.
run_all wraps every generator in try/except, logs the exception and returns []
for that generator.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.intelligence.anomaly import detect_feature_anomalies
from app.intelligence.evidence import build_field_evidence
from app.recommendations.contracts import DOMAINS, Recommendation

logger = logging.getLogger("croptwist.recommendations.registry")

Generator = Callable[[Session, Any, "RecommendationContext"], list[Recommendation]]


@dataclass
class RecommendationContext:
    """Preloaded, shared context for one refresh (built ONCE per field).

    - evidence: the compact provenance-labeled evidence pack
      (app/intelligence/evidence.py) — the grounding material.
    - anomalies: statistical z-score findings over the latest feature run
      (app/intelligence/anomaly.py).
    - data_gaps: domains with no engine outputs (mirrors evidence["data_gaps"]).
    """

    field: Any
    evidence: dict[str, Any] = field(default_factory=dict)
    anomalies: list[dict[str, Any]] = field(default_factory=list)

    @property
    def data_gaps(self) -> list[str]:
        return list(self.evidence.get("data_gaps") or [])

    def section(self, domain: str) -> dict[str, Any] | None:
        """The evidence pack section of one domain (None when no data)."""
        return self.evidence.get(domain)


class RecommendationRegistry:
    """Domain-keyed generator registry (insertion-ordered per domain)."""

    def __init__(self) -> None:
        self._generators: dict[str, list[Generator]] = {d: [] for d in DOMAINS}

    def generator(self, domain: str) -> Callable[[Generator], Generator]:
        """Register a generator under one domain.

        Usage:
            @registry.generator("water")
            def water_recommendations(db, field, ctx) -> list[Recommendation]:
                ...
        """
        if domain not in self._generators:
            raise ValueError(
                f"Unknown recommendation domain '{domain}' — must be one of {DOMAINS}."
            )

        def _wrap(fn: Generator) -> Generator:
            self._generators[domain].append(fn)
            logger.debug("registered recommendation generator for domain '%s'", domain)
            return fn

        return _wrap

    @property
    def domains(self) -> list[str]:
        return list(DOMAINS)

    def registered_count(self, domain: str | None = None) -> int:
        if domain is not None:
            return len(self._generators.get(domain, []))
        return sum(len(fns) for fns in self._generators.values())

    def build_context(self, db: Session, field: Any) -> RecommendationContext:
        """Build the shared context ONCE (evidence + seasonal anomalies)."""
        return RecommendationContext(
            field=field,
            evidence=build_field_evidence(db, field),
            anomalies=detect_feature_anomalies(db, field.id),
        )

    def build_context_evidence(self, db: Session, field: Any) -> dict[str, Any]:
        """Just the evidence pack (cache-key material for the refresh path)."""
        return build_field_evidence(db, field)

    def run_with_context(
        self, db: Session, field: Any, ctx: RecommendationContext
    ) -> list[Recommendation]:
        """Run every registered generator against a PREBUILT context."""
        out: list[Recommendation] = []
        for domain in DOMAINS:
            for fn in self._generators[domain]:
                try:
                    produced = fn(db, field, ctx)
                except Exception:  # noqa: BLE001 — isolation contract
                    logger.exception(
                        "recommendation generator %s.%s failed for field %s — skipped",
                        domain, getattr(fn, "__name__", fn), field.id,
                    )
                    continue
                for rec in produced or []:
                    if rec.domain != domain:
                        logger.warning(
                            "generator %s emitted rec for domain '%s' under '%s' — corrected",
                            getattr(fn, "__name__", fn), rec.domain, domain,
                        )
                        rec.domain = domain
                    if not rec.generator:
                        rec.generator = f"{domain}.{getattr(fn, '__name__', fn.__class__.__name__)}"
                    out.append(rec)
        return out

    def run_all(self, db: Session, field: Any) -> list[Recommendation]:
        """Build the context ONCE, then run every registered generator.

        Returns the flattened recommendation list (severities/order preserved:
        domain order, then registration order within a domain). Each rec is
        stamped with its generator's identity (A4 fingerprint material).
        """
        ctx = self.build_context(db, field)
        return self.run_with_context(db, field, ctx)


registry = RecommendationRegistry()
