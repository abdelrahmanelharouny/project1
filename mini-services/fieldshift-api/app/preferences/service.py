"""Global product configuration per user (P3 §9.2).

Locale, timezone, units, currency, country, week start and agricultural
calendar preference. Stored once per user; the API serializes it into every
client session bootstrap so frontend formatting is deterministic. Internal
units stay SI/metric everywhere — this preference governs PRESENTATION
conversions only.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.db.models_p3 import UserPreference

LOCALES = ("en", "ar")
UNIT_SYSTEMS = ("metric", "imperial")
WEEK_STARTS = ("monday", "sunday", "saturday")

# Common timezone allowlist is NOT enforced as a closed set (IANA names are
# open-ended); validation is a sane shape check plus a guard against control
# characters.
MAX_TIMEZONE_LEN = 60


def get_preferences(db: Session, user_id: uuid.UUID) -> UserPreference:
    row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if row is None:
        row = UserPreference(user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def update_preferences(
    db: Session, user_id: uuid.UUID, **changes: Any
) -> UserPreference:
    row = get_preferences(db, user_id)
    allowed = {
        "locale", "timezone", "unit_system", "currency_code", "country_code",
        "week_start", "agricultural_calendar", "notify_in_app", "notify_email",
    }
    unknown = set(changes) - allowed
    if unknown:
        raise ValidationFailed(f"Unknown preference fields: {sorted(unknown)}.")
    if "locale" in changes:
        if changes["locale"] not in LOCALES:
            raise ValidationFailed("locale must be 'en' or 'ar'.")
        row.locale = changes["locale"]
    if "timezone" in changes:
        tz = str(changes["timezone"]).strip()
        if not tz or len(tz) > MAX_TIMEZONE_LEN or any(c in tz for c in "\x00\r\n"):
            raise ValidationFailed("Invalid timezone identifier.")
        row.timezone = tz
    if "unit_system" in changes:
        if changes["unit_system"] not in UNIT_SYSTEMS:
            raise ValidationFailed("unit_system must be 'metric' or 'imperial'.")
        row.unit_system = changes["unit_system"]
    if "currency_code" in changes:
        cc = str(changes["currency_code"]).strip().upper()
        if len(cc) != 3 or not cc.isalpha():
            raise ValidationFailed("currency_code must be a 3-letter ISO 4217 code.")
        row.currency_code = cc
    if "country_code" in changes:
        value = changes["country_code"]
        if value is not None:
            cc = str(value).strip().upper()
            if len(cc) != 2 or not cc.isalpha():
                raise ValidationFailed("country_code must be a 2-letter ISO code.")
            row.country_code = cc
        else:
            row.country_code = None
    if "week_start" in changes:
        if changes["week_start"] not in WEEK_STARTS:
            raise ValidationFailed("week_start must be monday, sunday or saturday.")
        row.week_start = changes["week_start"]
    if "agricultural_calendar" in changes:
        cal = changes["agricultural_calendar"]
        if cal is not None and (not str(cal).strip() or len(str(cal)) > 60):
            raise ValidationFailed("Invalid agricultural calendar preference.")
        row.agricultural_calendar = cal
    if "notify_in_app" in changes:
        row.notify_in_app = bool(changes["notify_in_app"])
    if "notify_email" in changes:
        row.notify_email = bool(changes["notify_email"])
    db.commit()
    db.refresh(row)
    return row


def preferences_payload(row: UserPreference) -> dict[str, Any]:
    return {
        "locale": row.locale,
        "timezone": row.timezone,
        "unit_system": row.unit_system,
        "currency_code": row.currency_code,
        "country_code": row.country_code,
        "week_start": row.week_start,
        "agricultural_calendar": row.agricultural_calendar,
        "notifications": {"in_app": row.notify_in_app, "email": row.notify_email},
    }
