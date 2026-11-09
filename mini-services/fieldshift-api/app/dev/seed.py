"""Idempotent demo workspace seeding (SYNTHETIC data, dev-only).

Creates demo@fieldshift.local with a farm and two fields, ingests clearly
labelled synthetic observations, and returns a login token. Every observation
is a software fixture (is_synthetic=true) — never real-world data.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import generate_token, hash_password, verify_password
from app.db.models import AuthToken, Farm, Field, IngestionJob, Membership, Organization, User
from app.data_platform.ingestion.service import start_ingestion_job

DEMO_EMAIL = "demo@fieldshift.local"
DEMO_PASSWORD = "fieldshift-demo-2026"

_FARM = {
    "name": "Demo Nile Delta Farm (SYNTHETIC)",
    "country_code": "EG",
    "admin_region": "Demo region — synthetic workspace",
    "timezone": "Africa/Cairo",
    "currency_code": "EGP",
    "unit_system": "metric",
    "preferred_language": "en",
}

_FIELDS = [
    {
        "name": "North Field (synthetic)",
        "profile": "mediterranean_dry_summer",
        "year": 2023,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[31.40, 31.10], [31.42, 31.10], [31.42, 31.12], [31.40, 31.12], [31.40, 31.10]]],
        },
        "variables": ["air_temperature_mean", "air_temperature_max", "air_temperature_min", "precipitation", "reference_et0", "soil_moisture_surface"],
    },
    {
        "name": "South Field (synthetic)",
        "profile": "semi_arid",
        "year": 2022,
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[31.50, 30.88], [31.52, 30.88], [31.52, 30.90], [31.50, 30.90], [31.50, 30.88]]],
        },
        "variables": ["air_temperature_mean", "precipitation", "reference_et0"],
    },
]


def ensure_demo_workspace(db: Session) -> dict:
    user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
    created = False
    if user is None:
        user = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PASSWORD),
                    display_name="Demo Farmer (fixture)",
                    email_verified=True)
        db.add(user)
        org = Organization(name="Demo Organization (SYNTHETIC)")
        db.add(org)
        db.flush()
        db.add(Membership(organization_id=org.id, user_id=user.id, role_code="owner", status="active"))
        db.flush()
        created = True
    elif not user.email_verified:
        # Heal demo accounts created before email verification was enforced.
        user.email_verified = True

    org_id = db.scalar(select(Membership.organization_id).where(Membership.user_id == user.id))
    farm = db.scalar(select(Farm).where(Farm.organization_id == org_id))
    if farm is None:
        farm = Farm(organization_id=org_id, **_FARM)
        db.add(farm)
        db.flush()

    # Create fields + ingest synthetic data idempotently.
    token, token_hash, expires_at = generate_token()
    db.add(AuthToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at))
    db.commit()

    from app.domains.farms_fields.service import create_field
    from app.domains.identity.service import Principal
    from app.db.models import Membership as M

    principal = Principal(user=user, memberships=list(db.scalars(select(M).where(M.user_id == user.id)).all()))

    field_ids = []
    existing_fields = db.scalars(select(Field).where(Field.farm_id == farm.id)).all()
    if not existing_fields:
        for spec in _FIELDS:
            created_field = create_field(db, principal, farm, name=spec["name"], geometry=spec["geometry"],
                                         change_reason="demo seed (synthetic fixture)")
            field_ids.append(created_field["id"])
            start_ingestion_job(
                db,
                field=db.get(Field, created_field["id"]),
                provider_code="synthetic",
                variables=spec["variables"],
                start=datetime(spec["year"], 1, 1, tzinfo=UTC),
                end=datetime(spec["year"], 12, 31, 23, 59, 59, tzinfo=UTC),
                options={"profile": spec["profile"], "seed": 42},
                idempotency_key=f"demo-{spec['name']}-{spec['year']}",
                created_by=user.id,
            )
    else:
        field_ids = [str(f.id) for f in existing_fields]

    return {
        "token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "demo_user": {"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
        "note": "Demo workspace contains SYNTHETIC fixture data only.",
        "farm_id": str(farm.id),
        "field_ids": field_ids,
        "created": created,
    }
