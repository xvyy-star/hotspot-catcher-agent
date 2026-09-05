"""Application time helpers.

Database server-generated timestamps are stored as naive business-local values,
while explicitly recorded run timestamps are UTC-naive. Keep those conventions
visible at reporting boundaries instead of relying on the host process timezone.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo


APP_TIMEZONE = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Shanghai"))


def business_now_naive() -> datetime:
    return datetime.now(APP_TIMEZONE).replace(tzinfo=None)


def utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_naive_to_business(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(APP_TIMEZONE).replace(tzinfo=None)


def business_naive_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def business_today() -> date:
    return business_now_naive().date()
