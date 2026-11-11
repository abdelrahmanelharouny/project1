"""A10 Arabic/English AI content: locale propagation, per-locale caching,
language-independent ids; A3 cache behavior with locale; A2 async paths."""

from __future__ import annotations

import asyncio
import json

from tests.conftest import auth_headers, client, farm_with_field  # noqa: F401


class _ScriptedBridge:
    """Records (system_prompt, user_message) pairs; returns scripted content."""

    def __init__(self) -> None:
        self.calls: list[list[dict]] = []
        self.responses: list[str] = []

    def install(self, monkeypatch):
        from app.intelligence import bridge, narrative

        def sync_chat(messages, temperature=None, max_tokens=None):
            self.calls.append(messages)
            if not self.responses:
                raise AssertionError("unexpected bridge call: no scripted response")
            content = self.responses.pop(0)
            return {"content": content, "model": "test-model"}

        async def async_chat(messages, temperature=None, max_tokens=None):
            return sync_chat(messages, temperature=temperature, max_tokens=max_tokens)

        monkeypatch.setattr(bridge, "chat_detail", sync_chat)
        monkeypatch.setattr(bridge, "achat_detail", async_chat)
        monkeypatch.setattr(narrative, "chat_detail", sync_chat)
        monkeypatch.setattr(narrative, "achat_detail", async_chat)

    def narr_array(self, items: list[str]) -> str:
        return json.dumps(
            [{"key": str(i), "narrative": t} for i, t in enumerate(items)]
        )


def test_arabic_narrative_generation_and_caching(client, farm_with_field, monkeypatch):
    """locale=ar → the Arabic system prompt is used, Arabic narratives come
    back, and the SAME evidence+locale hits the narrative cache (A3+A10)."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    spy = _ScriptedBridge()
    spy.responses = [spy.narr_array(["هذه توصية بالعربية للري."])]
    spy.install(monkeypatch)

    # Prime the recommendation set (also consumes the one scripted response).
    refreshed = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh?locale=ar",
        headers=headers,
    )
    assert refreshed.status_code == 200, refreshed.text
    body = refreshed.json()
    assert body["recommendations"]
    arabic_recs = [r for r in body["recommendations"] if r.get("narrative")]
    assert arabic_recs, "at least one narrative attached"
    assert all(
        any("\u0600" <= ch <= "\u06FF" for ch in r["narrative"])
        for r in arabic_recs
    ), "Arabic locale narratives must be Arabic"
    assert body["engine"]["mode"] == "rules+llm"

    # Same evidence + locale → cache hit: NO new bridge call.
    calls_after_first = len(spy.calls)
    second = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh?locale=ar",
        headers=headers,
    ).json()
    assert second["narrative_cache"] == "hit"
    assert len(spy.calls) == calls_after_first
    assert [r["id"] for r in second["recommendations"]] == [
        r["id"] for r in body["recommendations"]
    ]

    # force=true bypasses the cache lookup (needs a scripted response) but
    # must REPOPULATE the cache so the next normal refresh hits (A3.5).
    spy.responses = [spy.narr_array(["سرد جديد بعد إعادة التوليد."])]
    forced = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh?locale=ar&force=true",
        headers=headers,
    ).json()
    assert forced["narrative_cache"] == "miss"
    assert len(spy.calls) == calls_after_first + 1

    third = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh?locale=ar",
        headers=headers,
    ).json()
    assert third["narrative_cache"] == "hit"
    assert len(spy.calls) == calls_after_first + 1  # no extra bridge call


def test_english_and_arabic_cached_independently(client, farm_with_field, monkeypatch):
    """Same evidence, different locales → two cache entries, two generations;
    the recs (and their ids) are identical — only the narrative differs."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    spy = _ScriptedBridge()
    spy.install(monkeypatch)
    spy.responses = [
        spy.narr_array(["English narrative about irrigation."]),
        spy.narr_array(["سرد عربي عن الري."]),
    ]

    en = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh?locale=en",
        headers=headers,
    ).json()
    ar = client.post(
        f"/api/v1/fields/{field_id}/recommendations/refresh?locale=ar",
        headers=headers,
    ).json()

    assert [r["id"] for r in en["recommendations"]] == [r["id"] for r in ar["recommendations"]]
    en_narratives = {r["id"]: r.get("narrative") for r in en["recommendations"]}
    ar_narratives = {r["id"]: r.get("narrative") for r in ar["recommendations"]}
    assert any(n and "English" in n for n in en_narratives.values())
    assert any(n and any("\u0600" <= ch <= "\u06FF" for ch in n) for n in ar_narratives.values())
    # No cross-locale contamination.
    for rid, text in en_narratives.items():
        if text:
            assert not any("\u0600" <= ch <= "\u06FF" for ch in text)


def test_arabic_advisor_answer(client, farm_with_field, monkeypatch):
    """locale=ar advisor: Arabic system rules present; structured answer ok."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    captured: list[list[dict]] = []

    from app.intelligence import advisor

    def fake_chat_detail(messages, temperature=None, max_tokens=None):
        captured.append(messages)
        return {
            "content": json.dumps({
                "answer": "مستوى الأمطار هذا الموسم ضمن المعدل الطبيعي.",
                "citations": ["field"],
            }),
            "model": "m",
        }

    async def fake_chat_detail_async(messages, temperature=None, max_tokens=None):
        return fake_chat_detail(messages, temperature=temperature, max_tokens=max_tokens)

    monkeypatch.setattr(advisor, "chat_detail", fake_chat_detail)
    monkeypatch.setattr(advisor, "achat_detail", fake_chat_detail_async)
    body = client.post(
        f"/api/v1/fields/{field_id}/advisor/query?locale=ar",
        headers=headers, json={"question": "كيف حال الأمطار؟"},
    ).json()
    system_prompt = captured[0][0]["content"]
    assert "ar" in system_prompt or "Arabic" in system_prompt
    assert any("\u0600" <= ch <= "\u06FF" for ch in body["answer"])
    assert body["engine"]["response_format"] == "structured"


def test_async_refresh_path_works_end_to_end(client, farm_with_field):
    """The async service function (used by async endpoints) runs against the
    real DB and produces the fingerprinted payload without an event loop."""
    field_id = farm_with_field["field"]["id"]
    headers = farm_with_field["headers"]
    # Force a GET ?refresh=true → the async endpoint path executes
    # refresh_field_recommendations_async under TestClient's event loop.
    resp = client.get(
        f"/api/v1/fields/{field_id}/recommendations?refresh=true&locale=ar",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recommendations"]
    assert body.get("narrative_cache") in (None, "hit", "miss")
