from __future__ import annotations

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def empty_hours() -> dict:
    return {day: {"closed": True, "open": "11:00", "close": "21:00"} for day in DAYS}


def _clock(value: str) -> tuple[int, int]:
    hour, minute = (value or "00:00").split(":", 1)
    return max(0, min(23, int(hour))), max(0, min(59, int(minute)))


def normalize_hours(raw: dict | None) -> dict:
    base = empty_hours()
    for day in DAYS:
        row = (raw or {}).get(day) or {}
        base[day] = {
            "closed": bool(row.get("closed", True)),
            "open": row.get("open") or "11:00",
            "close": row.get("close") or "21:00",
        }
    return base


def any_day_open(hours: dict) -> bool:
    return any(not row.get("closed", True) for row in hours.values())


def google_regular_hours(hours: dict) -> dict | None:
    if not any_day_open(hours):
        return None
    periods = []
    for day in DAYS:
        row = hours[day]
        if row.get("closed", True):
            continue
        open_h, open_m = _clock(row["open"])
        close_h, close_m = _clock(row["close"])
        periods.append(
            {
                "openDay": day.upper(),
                "openTime": {"hours": open_h, "minutes": open_m},
                "closeDay": day.upper(),
                "closeTime": {"hours": close_h, "minutes": close_m},
            }
        )
    return {"periods": periods}


def google_special_hours(rows: list | None) -> dict | None:
    periods = []
    for row in rows or []:
        date = (row.get("date") or "").strip()
        parts = date.split("-")
        if len(parts) != 3:
            continue
        year, month, day = (int(part) for part in parts)
        period: dict = {
            "startDate": {"year": year, "month": month, "day": day},
            "endDate": {"year": year, "month": month, "day": day},
        }
        if row.get("closed", False):
            period["closed"] = True
        else:
            open_h, open_m = _clock(row.get("open") or "11:00")
            close_h, close_m = _clock(row.get("close") or "21:00")
            period["openTime"] = {"hours": open_h, "minutes": open_m}
            period["closeTime"] = {"hours": close_h, "minutes": close_m}
        periods.append(period)
    if not periods:
        return None
    return {"specialHourPeriods": periods}
