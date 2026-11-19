import json
from datetime import datetime


def dump(value) -> str:
    return json.dumps(value, separators=(",", ":"), default=str)


def load(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def stamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
