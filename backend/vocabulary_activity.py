"""Calendar-day vocabulary activity in the learner's timezone."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def vocabulary_activity(conn, user, now=None):
    try:
        zone = ZoneInfo(user.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    today = (now or datetime.now(timezone.utc)).astimezone(zone).date()
    first = today - timedelta(days=29)
    start = datetime.combine(first, time.min, zone).astimezone(timezone.utc)
    end = datetime.combine(today + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
    rows = conn.execute(
        """SELECT vocabulary_id, reviewed_at FROM reviews
           WHERE user_id=? AND reviewed_at>=? AND reviewed_at<?""",
        (user["id"], start.isoformat(), end.isoformat()),
    ).fetchall()
    days = { (first + timedelta(days=i)).isoformat(): {"words": set(), "reviews": 0} for i in range(30) }
    for row in rows:
        stamp = datetime.fromisoformat(row["reviewed_at"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        day = days.get(stamp.astimezone(zone).date().isoformat())
        if day is not None:
            day["words"].add(row["vocabulary_id"])
            day["reviews"] += 1
    return {
        "timezone": str(zone),
        "days": [{"date": date, "words": len(day["words"]), "reviews": day["reviews"]}
                 for date, day in days.items()],
    }
