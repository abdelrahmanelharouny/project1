"""Integration tests for serialized scenario quota reservations.

The existing synthetic fixture is used only to establish a finalized scenario;
execution itself is stubbed at the engine boundary, so no external providers,
mail, or payment services are contacted. Run only with an isolated test DSN.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Event, local
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select

from app.billing import entitlements
from app.billing import service as billing_service
from app.core.database import SessionLocal
from app.core.errors import PaymentRequired
from app.db import models as dbm
from app.db.models_p3 import Plan, PlanEntitlement, Subscription, UsageCounter
from app.scenario_execution import contracts as execution_contracts
from app.scenario_execution import service as execution_service


INGEST_BODY = {
    "provider_code": "synthetic",
    "variables": [
        "precipitation",
        "air_temperature_mean",
        "air_temperature_min",
        "air_temperature_max",
        "reference_et0",
    ],
    "start_date": "2015-01-01",
    "end_date": "2017-12-31",
    "profile": "temperate_seasonal",
    "seed": 17,
}
STRESS_CONFIG = {
    "type": "user_defined_stress",
    "parent_field_state_id": None,
    "period": {"start": "2016-01-01", "end": "2017-12-31"},
    "adjustments": {"temperature_delta_c": 2.0, "water_allocation_multiplier": 0.7},
    "assumption_metadata": {
        "origin": "user_defined",
        "status": "hypothetical",
        "description": "Synthetic quota regression test scenario",
    },
}


def _prepare_parent_state(client, headers, field_id):
    response = client.post(
        f"/api/v1/fields/{field_id}/data-jobs", headers=headers, json=INGEST_BODY
    )
    assert response.status_code == 202, response.text
    assert response.json()["status"] == "succeeded"
    feature_response = client.post(
        f"/api/v1/fields/{field_id}/feature-runs",
        headers=headers,
        json={
            "start_date": "2015-01-01",
            "end_date": "2017-12-31",
            "aggregation_levels": ["monthly"],
            "hemisphere": "north",
        },
    )
    assert feature_response.status_code == 202, feature_response.text
    feature_run = feature_response.json()
    assert feature_run["status"] == "succeeded"
    state_response = client.post(
        f"/api/v1/fields/{field_id}/field-states",
        headers=headers,
        json={
            "period_start": "2015-01-01",
            "period_end": "2017-12-31",
            "environmental_feature_run_id": feature_run["run_id"],
        },
    )
    assert state_response.status_code == 202, state_response.text
    state = state_response.json()
    assert state["status"] == "succeeded"
    return state


def _create_finalized_scenario(client, headers, field_id, state_id, *, delta_c=2.0):
    config = {**STRESS_CONFIG, "parent_field_state_id": state_id}
    config["adjustments"] = {**STRESS_CONFIG["adjustments"], "temperature_delta_c": delta_c}
    response = client.post(
        f"/api/v1/fields/{field_id}/scenarios",
        headers=headers,
        json={
            "scenario_type": "user_defined_stress",
            "name": f"Quota scenario {uuid.uuid4().hex[:8]}",
            "configuration": config,
        },
    )
    assert response.status_code in (200, 201), response.text
    scenario = response.json()
    validate = client.post(f"/api/v1/scenarios/{scenario['id']}/validate", headers=headers)
    assert validate.status_code == 200, validate.text
    finalize = client.post(f"/api/v1/scenarios/{scenario['id']}/finalize", headers=headers)
    assert finalize.status_code == 200, finalize.text
    return finalize.json()


def _set_plan_quota(db, plan_code, quota):
    db.expire_all()
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    assert plan is not None
    entitlement = db.scalar(
        select(PlanEntitlement).where(
            PlanEntitlement.plan_id == plan.id,
            PlanEntitlement.key == entitlements.KEY_SCENARIO_RUNS_PER_MONTH,
        )
    )
    assert entitlement is not None
    entitlement.value_int = quota
    db.commit()
    return plan.id


def _attach_synthetic_subscription(db, organization_id, plan_id, billing_period):
    now = datetime.now(UTC)
    subscription = Subscription(
        organization_id=uuid.UUID(str(organization_id)),
        plan_id=plan_id,
        status="active",
        billing_period=billing_period,
        provider="sandbox",
        current_period_start=now,
        current_period_end=now + timedelta(days=365),
    )
    db.add(subscription)
    db.commit()
    return subscription


def _usage_row(db, organization_id):
    db.expire_all()
    return db.scalar(
        select(UsageCounter).where(
            UsageCounter.organization_id == uuid.UUID(str(organization_id)),
            UsageCounter.key == entitlements.KEY_SCENARIO_RUNS_PER_MONTH,
            UsageCounter.period_start == entitlements.scenario_quota_period_start(),
        )
    )


def _install_success_stub(monkeypatch):
    def succeed(db, run, **_kwargs):
        run.run_status = execution_contracts.RUN_STATUS_SUCCEEDED
        run.output_checksum = "a" * 64
        run.completed_at = datetime.now(UTC)
        db.commit()

    monkeypatch.setattr(execution_service, "_execute_run", succeed)


def _execute(client, headers, scenario_id):
    return client.post(
        f"/api/v1/scenarios/{scenario_id}/executions", headers=headers, json={}
    )


def test_free_plan_cap_and_replay_are_metered_once_without_subscription(
    client, farm_with_field, db, monkeypatch
):
    _install_success_stub(monkeypatch)
    organization_id = farm_with_field["user"]["organization"]["id"]
    _set_plan_quota(db, "free", 1)
    state = _prepare_parent_state(
        client, farm_with_field["headers"], farm_with_field["field"]["id"]
    )
    first = _create_finalized_scenario(
        client, farm_with_field["headers"], farm_with_field["field"]["id"], state["id"]
    )

    first_response = _execute(client, farm_with_field["headers"], first["id"])
    assert first_response.status_code == 200, first_response.text
    replay = _execute(client, farm_with_field["headers"], first["id"])
    assert replay.status_code == 200, replay.text
    assert replay.json()["run_id"] == first_response.json()["run_id"]

    second = _create_finalized_scenario(
        client,
        farm_with_field["headers"],
        farm_with_field["field"]["id"],
        state["id"],
        delta_c=1.0,
    )
    denied = _execute(client, farm_with_field["headers"], second["id"])
    assert denied.status_code == 402, denied.text
    assert denied.json()["error"]["code"] == "PAYMENT_REQUIRED"
    assert "scenario_runs_per_month" in denied.json()["error"]["message"]

    assert entitlements.get_live_subscription(db, uuid.UUID(organization_id)) is None
    assert _usage_row(db, organization_id).used_value == 1


def test_live_subscription_cap_blocks_after_one_admitted_run(
    client, farm_with_field, db, monkeypatch
):
    _install_success_stub(monkeypatch)
    organization_id = farm_with_field["user"]["organization"]["id"]
    starter_plan_id = _set_plan_quota(db, "starter", 1)
    _attach_synthetic_subscription(db, organization_id, starter_plan_id, "monthly")
    state = _prepare_parent_state(
        client, farm_with_field["headers"], farm_with_field["field"]["id"]
    )
    first = _create_finalized_scenario(
        client, farm_with_field["headers"], farm_with_field["field"]["id"], state["id"]
    )
    second = _create_finalized_scenario(
        client,
        farm_with_field["headers"],
        farm_with_field["field"]["id"],
        state["id"],
        delta_c=1.0,
    )

    admitted = _execute(client, farm_with_field["headers"], first["id"])
    assert admitted.status_code == 200, admitted.text
    denied = _execute(client, farm_with_field["headers"], second["id"])
    assert denied.status_code == 402, denied.text

    db.expire_all()
    subscription = db.scalar(
        select(Subscription).where(Subscription.organization_id == uuid.UUID(organization_id))
    )
    assert subscription is not None and subscription.plan_id == starter_plan_id
    assert _usage_row(db, organization_id).used_value == 1


def test_concurrent_distinct_runs_cannot_both_take_the_last_free_slot(
    client, farm_with_field, db, monkeypatch
):
    organization_id = farm_with_field["user"]["organization"]["id"]
    _set_plan_quota(db, "free", 1)
    state = _prepare_parent_state(
        client, farm_with_field["headers"], farm_with_field["field"]["id"]
    )
    scenarios = [
        _create_finalized_scenario(
            client,
            farm_with_field["headers"],
            farm_with_field["field"]["id"],
            state["id"],
            delta_c=delta,
        )
        for delta in (1.0, 2.0)
    ]
    _install_success_stub(monkeypatch)
    barrier = Barrier(2)
    original_fingerprint = execution_service._input_fingerprint
    worker_state = local()

    def synchronized_fingerprint(*args, **kwargs):
        value = original_fingerprint(*args, **kwargs)
        # Force the two independent requests to overlap before admission. The
        # locked recheck must not wait at a second barrier while holding the
        # organization lock needed by its peer.
        if not getattr(worker_state, "synchronized", False):
            worker_state.synchronized = True
            barrier.wait(timeout=20)
        return value

    monkeypatch.setattr(execution_service, "_input_fingerprint", synchronized_fingerprint)
    user = SimpleNamespace(id=uuid.UUID(farm_with_field["user"]["user"]["id"]))

    def attempt(scenario_id):
        with SessionLocal() as session:
            scenario = session.get(dbm.Scenario, uuid.UUID(scenario_id))
            assert scenario is not None
            try:
                run = execution_service.start_scenario_execution(
                    session, scenario, created_by=user
                )
            except PaymentRequired:
                return "denied"
            return f"admitted:{run.id}"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (scenario["id"] for scenario in scenarios)))

    assert sum(outcome.startswith("admitted:") for outcome in outcomes) == 1
    assert outcomes.count("denied") == 1
    assert _usage_row(db, organization_id).used_value == 1


def test_admitted_failed_execution_remains_charged(
    client, farm_with_field, db, monkeypatch
):
    organization_id = farm_with_field["user"]["organization"]["id"]
    _set_plan_quota(db, "free", 1)

    def fail_after_admission(db, run, **_kwargs):
        run.run_status = execution_contracts.RUN_STATUS_FAILED
        run.error_summary = "synthetic engine failure for quota regression"
        run.completed_at = datetime.now(UTC)
        db.commit()

    monkeypatch.setattr(execution_service, "_execute_run", fail_after_admission)
    state = _prepare_parent_state(
        client, farm_with_field["headers"], farm_with_field["field"]["id"]
    )
    failed_scenario = _create_finalized_scenario(
        client, farm_with_field["headers"], farm_with_field["field"]["id"], state["id"]
    )
    response = _execute(client, farm_with_field["headers"], failed_scenario["id"])
    assert response.status_code == 200, response.text
    assert response.json()["run_status"] == execution_contracts.RUN_STATUS_FAILED
    assert _usage_row(db, organization_id).used_value == 1

    next_scenario = _create_finalized_scenario(
        client,
        farm_with_field["headers"],
        farm_with_field["field"]["id"],
        state["id"],
        delta_c=1.0,
    )
    denied = _execute(client, farm_with_field["headers"], next_scenario["id"])
    assert denied.status_code == 402, denied.text
    assert _usage_row(db, organization_id).used_value == 1


def test_yearly_subscription_plan_changes_keep_monthly_scenario_bucket(
    client, farm_with_field, db, monkeypatch
):
    _install_success_stub(monkeypatch)
    organization_id = farm_with_field["user"]["organization"]["id"]
    starter_plan_id = _set_plan_quota(db, "starter", 3)
    _attach_synthetic_subscription(db, organization_id, starter_plan_id, "yearly")
    state = _prepare_parent_state(
        client, farm_with_field["headers"], farm_with_field["field"]["id"]
    )
    scenario = _create_finalized_scenario(
        client, farm_with_field["headers"], farm_with_field["field"]["id"], state["id"]
    )
    response = _execute(client, farm_with_field["headers"], scenario["id"])
    assert response.status_code == 200, response.text

    usage = _usage_row(db, organization_id)
    assert usage is not None
    assert usage.period_start == entitlements.scenario_quota_period_start()
    assert usage.used_value == 1

    db.expire_all()
    subscription = db.scalar(
        select(Subscription).where(Subscription.organization_id == uuid.UUID(organization_id))
    )
    assert subscription is not None
    assert subscription.plan_id == starter_plan_id
    assert subscription.billing_period == "yearly"
    professional = db.scalar(select(Plan).where(Plan.code == "professional"))
    free = db.scalar(select(Plan).where(Plan.code == "free"))
    assert professional is not None and free is not None

    subscription.plan_id = professional.id
    db.commit()
    assert entitlements.current_usage(db, uuid.UUID(organization_id), entitlements.KEY_SCENARIO_RUNS_PER_MONTH) == 1
    subscription.plan_id = free.id
    db.commit()
    assert entitlements.current_usage(db, uuid.UUID(organization_id), entitlements.KEY_SCENARIO_RUNS_PER_MONTH) == 1
    assert _usage_row(db, organization_id).period_start == entitlements.scenario_quota_period_start()


def test_downgrade_serializes_with_scenario_admission_using_committed_plan(
    farm_with_field, db, monkeypatch
):
    organization_id = farm_with_field["user"]["organization"]["id"]
    starter_plan_id = _set_plan_quota(db, "starter", 1)
    free_plan_id = _set_plan_quota(db, "free", 0)
    _attach_synthetic_subscription(db, organization_id, starter_plan_id, "monthly")

    transition_staged = Event()
    allow_transition_commit = Event()
    quota_lock_attempted = Event()
    quota_snapshot_started = Event()
    original_transition = billing_service._record_transition
    original_quota_lock = entitlements.lock_organization_for_quota
    original_limit_for = entitlements.limit_for

    def pause_after_plan_update(session, **kwargs):
        original_transition(session, **kwargs)
        session.flush()
        transition_staged.set()
        if not allow_transition_commit.wait(timeout=20):
            raise TimeoutError("test did not release the staged plan transition")

    def observe_quota_lock(session, locked_organization_id):
        quota_lock_attempted.set()
        return original_quota_lock(session, locked_organization_id)

    def observe_quota_snapshot(session, snapshot_organization_id, key):
        if key == entitlements.KEY_SCENARIO_RUNS_PER_MONTH:
            quota_snapshot_started.set()
        return original_limit_for(session, snapshot_organization_id, key)

    monkeypatch.setattr(billing_service, "_record_transition", pause_after_plan_update)
    monkeypatch.setattr(entitlements, "lock_organization_for_quota", observe_quota_lock)
    monkeypatch.setattr(entitlements, "limit_for", observe_quota_snapshot)
    principal = SimpleNamespace(id=uuid.uuid4(), require_org_role=lambda *_args: None)
    org_uuid = uuid.UUID(organization_id)

    def downgrade():
        with SessionLocal() as session:
            subscription = billing_service.change_plan(
                session,
                principal,
                organization_id=org_uuid,
                new_plan_id=free_plan_id,
            )
            return subscription.plan_id

    def admit_scenario():
        with SessionLocal() as session:
            try:
                entitlements.reserve_scenario_run(session, org_uuid)
            except PaymentRequired:
                return "denied"
            session.commit()
            return "admitted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        downgrade_future = pool.submit(downgrade)
        assert transition_staged.wait(timeout=10), "downgrade did not reach its staged update"
        admission_future = pool.submit(admit_scenario)
        try:
            assert quota_lock_attempted.wait(timeout=10), "scenario admission did not attempt its lock"
            assert not quota_snapshot_started.wait(timeout=0.5), (
                "scenario admission read the old plan before the downgrade committed"
            )
        finally:
            allow_transition_commit.set()

        assert downgrade_future.result(timeout=20) == free_plan_id
        assert admission_future.result(timeout=20) == "denied"

    db.expire_all()
    subscription = db.scalar(
        select(Subscription).where(Subscription.organization_id == org_uuid)
    )
    assert subscription is not None and subscription.plan_id == free_plan_id
    assert entitlements.limit_for(
        db, org_uuid, entitlements.KEY_SCENARIO_RUNS_PER_MONTH
    ) == 0
    usage = _usage_row(db, organization_id)
    assert usage is None or usage.used_value == 0
