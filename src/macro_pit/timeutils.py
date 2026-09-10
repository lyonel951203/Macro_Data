from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


UTC = timezone.utc
SHANGHAI = ZoneInfo("Asia/Shanghai")


def ensure_aware(value: datetime | str, default_tz: ZoneInfo = SHANGHAI) -> datetime:
    """Parse a timestamp and return a timezone-aware UTC datetime."""
    if isinstance(value, str):
        normalized = value.strip().replace("Z", "+00:00")
        value = datetime.fromisoformat(normalized)
    if value.tzinfo is None:
        value = value.replace(tzinfo=default_tz)
    return value.astimezone(UTC)


def conservative_date_only_available(release_date: date, local_tz: ZoneInfo = SHANGHAI) -> datetime:
    """PIT_B rule: date-only releases become visible next day at local 00:00."""
    local_value = datetime.combine(release_date + timedelta(days=1), time.min, tzinfo=local_tz)
    return local_value.astimezone(UTC)

