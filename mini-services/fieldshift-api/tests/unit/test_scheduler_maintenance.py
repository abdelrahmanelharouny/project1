from app.core import scheduler


def test_public_api_retention_task_uses_bounded_scheduler_entrypoint(monkeypatch):
    from app.publicapi import api_keys

    calls = []
    expected = {"usage_rows": 3, "rate_rows": 2}

    def fake_purge(session, *, batch_size):
        calls.append((session, batch_size))
        return expected

    monkeypatch.setattr(api_keys, "purge_api_key_usage", fake_purge)
    session = object()
    assert scheduler._purge_public_api_state(session) == str(expected)
    assert calls == [(session, 1000)]
    task = next(task for task in scheduler.TASKS if task.name == "public_api.retention")
    assert task.interval_seconds == 3600
