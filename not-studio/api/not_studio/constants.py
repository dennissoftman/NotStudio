from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    from uuid import uuid4

    return uuid4().hex
