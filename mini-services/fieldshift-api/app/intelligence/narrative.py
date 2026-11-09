"""Recommendation narratives (Intelligence layer).

ONE bridge call per refresh: the compact recommendation list (titles,
summaries, key numbers) goes in; a JSON array of {key, narrative} comes back.
The narrative is a farmer-friendly 1-2 sentence expansion that may ONLY use
the given facts — no new numbers, no new claims. Parsing is defensive; on any
failure the recommendations are left unchanged (rules output is never lost).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.intelligence.bridge import chat_detail

logger = logging.getLogger("fieldshift.intelligence.narrative")

MAX_NARRATIVE_CHARS = 600
MAX_RECS_IN_PROMPT = 30

_SYSTEM_PROMPT = (
    "You are FieldShift's narrative writer. You expand deterministic "
    "agronomic recommendations for farmers. You MUST only use the facts in "
    "the given recommendation list — never invent numbers, never add claims "
    "that are not present. Write 1-2 short, farmer-friendly sentences per "
    "recommendation. Respond in the same language as the recommendation "
    "titles. Reply ONLY with a JSON array of objects "
    '{"key": "<key>", "narrative": "<text>"} — no prose around it.'
)


def _rec_facts(index: int, rec: Any) -> dict[str, Any]:
    """Compact, prompt-safe facts for one recommendation (attribute or key
    access so both ORM rows and contract objects work)."""
    def get(name: str) -> Any:
        if isinstance(rec, dict):
            return rec.get(name)
        return getattr(rec, name, None)

    facts: dict[str, Any] = {
        "key": str(index),
        "domain": get("domain"),
        "severity": (
            getattr(get("severity"), "value", None)
            if not isinstance(get("severity"), str)
            else get("severity")
        ),
        "title": get("title"),
        "summary": get("summary"),
        "confidence": get("confidence"),
        "actions": (get("actions") or [])[:3],
    }
    return facts


def _parse_narratives(content: str) -> dict[str, str]:
    """Defensively extract {key: narrative} from the bridge response."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON array in bridge response")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("bridge response is not a JSON array")
    out: dict[str, str] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        narrative = item.get("narrative")
        if key is None or not isinstance(narrative, str):
            continue
        narrative = narrative.strip()
        if not narrative:
            continue
        out[str(key)] = narrative[:MAX_NARRATIVE_CHARS]
    return out


def enrich_recommendations(
    db: Any, field: Any, recommendations: list[Any]
) -> dict[str, Any] | None:
    """Add `narrative` to recommendations in place (best-effort).

    Returns {"model", "enriched_count"} when the bridge contributed, or None
    when it did not (disabled, unreachable, malformed, or nothing to enrich) —
    in which case every recommendation is left exactly as the rules layer
    produced it.
    """
    if not recommendations:
        return None
    facts = [
        _rec_facts(i, rec)
        for i, rec in enumerate(recommendations[:MAX_RECS_IN_PROMPT])
    ]
    user_message = (
        "Expand each recommendation for a farmer. Facts (JSON):\n"
        + json.dumps(facts, ensure_ascii=False, default=str)
    )
    detail = chat_detail(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
    )
    if detail is None:
        return None
    try:
        narratives = _parse_narratives(detail["content"])
    except (ValueError, json.JSONDecodeError) as exc:
        logger.warning("narrative enrichment parse failed: %s — recs unchanged", exc)
        return None
    enriched = 0
    for i, rec in enumerate(recommendations):
        narrative = narratives.get(str(i))
        if not narrative:
            continue
        if isinstance(rec, dict):
            rec["narrative"] = narrative
        else:
            rec.narrative = narrative
        enriched += 1
    if not enriched:
        return None
    return {"model": detail.get("model"), "enriched_count": enriched}
