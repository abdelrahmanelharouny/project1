"""AI agronomist advisor (Intelligence layer).

answer_field_question: the LLM answers a farmer's question GROUNDED ONLY in
the field's evidence pack. Honesty contract (enforced by prompt + parsing):
- Every claim must cite its evidence label like [evidence: LABEL].
- Missing data must be named as missing; the model never invents numbers.
- The reply is in the question's language.

Degradation: when the bridge is unavailable the advisor returns a
DETERMINISTIC rules answer — a compact summary of the evidence pack plus the
top active recommendations — so the endpoint always returns something useful
and honest. The engine mode in the response records which path produced it
("llm" vs "rules").

field_brief: the 2-3 sentence field brief used by the insights endpoint.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.intelligence.bridge import chat_detail
from app.intelligence.evidence import build_field_evidence
from app.intelligence.anomaly import detect_feature_anomalies

logger = logging.getLogger("fieldshift.intelligence.advisor")

_SYSTEM_PROMPT = (
    "You are FieldShift's AI agronomist. You MUST ground every claim in the "
    "provided evidence pack. Cite evidence items by their label like "
    "[evidence: LABEL]. If the evidence does not contain the answer, say "
    "what data is missing. Never invent numbers. User's language: respond in "
    "the same language as the question.\n"
    "Finish your reply with one final line exactly in this format:\n"
    "EVIDENCE: label1; label2\n"
    "(the evidence-pack labels you actually used, semicolon-separated)."
)


def _top_level_labels(evidence: dict[str, Any]) -> list[str]:
    return [k for k in evidence.keys() if k != "data_gaps"]


def _parse_evidence_line(content: str) -> list[str] | None:
    """Parse the trailing `EVIDENCE: a; b` line (None when absent/malformed)."""
    for line in reversed(content.strip().splitlines()):
        if line.strip().upper().startswith("EVIDENCE:"):
            raw = line.split(":", 1)[1]
            labels = [part.strip() for part in raw.split(";") if part.strip()]
            return labels or None
    return None


def _rules_fallback(
    field: Any, evidence: dict[str, Any], recommendations: list[dict[str, Any]]
) -> str:
    """Deterministic answer summarizing evidence + top active recommendations."""
    gaps = evidence.get("data_gaps") or []
    lines: list[str] = [
        f"Evidence summary for field '{evidence.get('field', {}).get('name')}' "
        f"({evidence.get('field', {}).get('area_ha')} ha):"
    ]
    climate = evidence.get("climate")
    if climate:
        metrics = ", ".join(
            f"{m.get('code')} {m.get('value')} {m.get('unit')}"
            for m in (climate.get("metrics") or [])[:4]
        )
        lines.append(f"- climate: {metrics}.")
    water = evidence.get("water")
    if water:
        lines.append(
            f"- water: plan NIR {water.get('nir_mm')} mm, GIR {water.get('gir_mm')} mm, "
            f"{water.get('deficit_window_count')} deficit window(s)."
        )
    soil = evidence.get("soil")
    if soil:
        budget = soil.get("nutrient_budget") or {}
        if budget:
            lines.append(
                f"- soil: cumulative nutrient balance {budget.get('cumulative_balance_kg_ha')} kg/ha."
            )
        soc = soil.get("soc_stock") or {}
        if soc.get("stock_Mg_C_ha") is not None:
            lines.append(f"- soil: SOC stock {soc.get('stock_Mg_C_ha')} Mg C/ha.")
    rotation = evidence.get("rotation")
    if rotation and rotation.get("assignment"):
        crops = ", ".join(
            f"{a.get('crop')} ({a.get('season')})" for a in rotation["assignment"][:4]
        )
        lines.append(f"- rotation: planned crops {crops}.")
    management = evidence.get("management")
    if management:
        cover = management.get("soil_cover") or {}
        if cover.get("protective_cover_fraction") is not None:
            lines.append(
                f"- management: protective cover "
                f"{round(float(cover['protective_cover_fraction']) * 100, 1)}% of the last year."
            )
    if gaps:
        lines.append(
            f"- missing data: no engine outputs for {', '.join(gaps)} "
            "(run those engines to unlock the corresponding advice)."
        )
    if recommendations:
        lines.append("Top active recommendations:")
        for rec in recommendations[:3]:
            lines.append(f"- [{rec.get('severity')}] {rec.get('title')}")
    lines.append(
        "The AI advisor is offline right now, so this is the deterministic "
        "evidence summary; re-try for a narrated answer. No numbers above are "
        "invented — they come from the engine outputs listed."
    )
    return "\n".join(lines)


def answer_field_question(
    db: Any, field: Any, question: str
) -> dict[str, Any]:
    """Answer one field question; LLM-grounded when possible, rules otherwise.

    Returns {"answer", "evidence_used": [{"type","id","label"}], "engine":
    {"mode","model"}} — the router persists the transcript rows.
    """
    evidence = build_field_evidence(db, field)
    anomalies = detect_feature_anomalies(db, field.id)

    detail = chat_detail(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Farmer's question: {question}\n\n"
                    f"Evidence pack (JSON):\n{json.dumps(evidence, ensure_ascii=False, default=str)}\n\n"
                    f"Statistical anomaly findings over the latest feature run "
                    f"(JSON, may be empty):\n{json.dumps(anomalies, ensure_ascii=False, default=str)}"
                ),
            },
        ]
    )

    if detail is not None:
        labels = _parse_evidence_line(detail["content"])
        answer = detail["content"]
        if labels is not None:
            # Strip the machine-readable trailing line from the visible answer.
            answer = "\n".join(
                line
                for line in answer.strip().splitlines()
                if not line.strip().upper().startswith("EVIDENCE:")
            ).strip()
            valid = set(_top_level_labels(evidence)) | {"data_gaps"}
            labels = [l for l in labels if l in valid] or _top_level_labels(evidence)
        else:
            labels = _top_level_labels(evidence)
        return {
            "answer": answer,
            "evidence_used": _evidence_used(evidence, labels),
            "engine": {"mode": "llm", "model": detail.get("model")},
        }

    # Deterministic fallback: evidence summary + top active recommendations.
    from app.recommendations import service as recommendation_service

    recommendations = recommendation_service.get_active_recommendations(db, field)
    return {
        "answer": _rules_fallback(field, evidence, recommendations),
        "evidence_used": _evidence_used(evidence, _top_level_labels(evidence)),
        "engine": {"mode": "rules", "model": None},
    }


def _evidence_used(
    evidence: dict[str, Any], labels: list[str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label in labels:
        if label == "data_gaps":
            out.append({"type": "data_gap", "id": None, "label": label})
            continue
        section = evidence.get(label) or {}
        source = section.get("source") or {}
        out.append({
            "type": source.get("kind", label),
            "id": source.get("id"),
            "label": label,
        })
    return out


def field_brief(db: Any, field: Any) -> dict[str, Any]:
    """2-3 sentence field brief grounded ONLY in the evidence pack.

    Returns {"summary": str | None, "engine": {"mode","model"}} — summary is
    None (mode "rules") when the bridge is unavailable: no invented brief.
    """
    evidence = build_field_evidence(db, field)
    anomalies = detect_feature_anomalies(db, field.id)
    detail = chat_detail(
        [
            {
                "role": "system",
                "content": (
                    "You are FieldShift's AI agronomist. Write a 2-3 sentence "
                    "field brief. Ground EVERY statement ONLY in the provided "
                    "evidence pack; cite labels like [evidence: LABEL]; name "
                    "missing data as missing; never invent numbers. Respond in "
                    "English."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Evidence pack (JSON):\n{json.dumps(evidence, ensure_ascii=False, default=str)}\n\n"
                    f"Statistical anomaly findings (JSON):\n{json.dumps(anomalies, ensure_ascii=False, default=str)}"
                ),
            },
        ]
    )
    if detail is None:
        return {"summary": None, "engine": {"mode": "rules", "model": None}}
    return {
        "summary": detail["content"].strip(),
        "engine": {"mode": "llm", "model": detail.get("model")},
    }
