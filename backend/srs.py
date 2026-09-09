"""Spaced repetition scheduler.

A thin, HTTP/DB-free wrapper around the `fsrs` package - FSRS-6
(github.com/open-spaced-repetition/py-fsrs), the same algorithm family Anki
itself ships. The rest of the app depends on this module, never on `fsrs`
directly, so the library (or a fallback scheduler) can be swapped here
without touching any route or the database shape beyond what this module
already persists - see `review()`/`preview()`.

State model: fsrs.State only has Learning/Review/Relearning - there is no
library-level "New" or "Mastered". This app's UI already shows five states
(NEW/LEARNING/REVIEW/RELEARNING/MASTERED), so `display_state()` derives them:
NEW is "Learning, never reviewed"; MASTERED is a display-only label for a
long, stable REVIEW card (FSRS itself has no such concept).
"""
from datetime import datetime, timedelta, timezone as tz
from zoneinfo import ZoneInfo

import fsrs

RATINGS = ("again", "hard", "good", "easy")

_RATING = {"again": fsrs.Rating.Again, "hard": fsrs.Rating.Hard, "good": fsrs.Rating.Good, "easy": fsrs.Rating.Easy}
_FSRS_STATE = {fsrs.State.Learning: 1, fsrs.State.Review: 2, fsrs.State.Relearning: 3}
_STATE_FSRS = {1: fsrs.State.Learning, 2: fsrs.State.Review, 3: fsrs.State.Relearning}
_DISPLAY_STATE = {fsrs.State.Learning: "LEARNING", fsrs.State.Review: "REVIEW", fsrs.State.Relearning: "RELEARNING"}

# Display-only: a REVIEW card whose stability (expected days until forgetting
# drops below the retention target) has reached this is shown as "mastered".
MASTERED_STABILITY_DAYS = 60

_scheduler = fsrs.Scheduler()  # FSRS-6 defaults: desired_retention=0.9, 36500-day max interval, fuzzing on


def _parse_dt(value) -> datetime:
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz.utc)


def _card_from_row(row) -> fsrs.Card:
    """Rebuild an fsrs.Card from the engine columns persisted on a vocabulary row."""
    return fsrs.Card(
        card_id=row["id"],
        state=_STATE_FSRS.get(row["fsrs_state"] or 1, fsrs.State.Learning),
        step=row["fsrs_step"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        due=_parse_dt(row["next_review_at"]) if row["next_review_at"] else datetime.now(tz.utc),
        last_review=_parse_dt(row["last_reviewed_at"]) if row["last_reviewed_at"] else None,
    )


def display_state(card: fsrs.Card, lapses: int = 0) -> str:
    if card.last_review is None:
        return "NEW"
    if card.state == fsrs.State.Review and (card.stability or 0) >= MASTERED_STABILITY_DAYS:
        return "MASTERED"
    return _DISPLAY_STATE[card.state]


def _apply(row, rating: str, now: datetime):
    if rating not in RATINGS:
        raise ValueError(f"invalid rating: {rating}")
    return _scheduler.review_card(_card_from_row(row), _RATING[rating], review_datetime=now)


def review(row, rating: str, now: datetime | None = None) -> dict:
    """Apply one rating to a card. Returns the fields to persist on the
    vocabulary row (under "fields") and a full before/after snapshot for the
    review log (under "log") - nothing here touches the database itself."""
    now = now or datetime.now(tz.utc)
    before = _card_from_row(row)
    new_card, _log = _apply(row, rating, now)

    lapses = (row["lapses"] or 0) + (1 if rating == "again" and before.state == fsrs.State.Review else 0)
    elapsed_days = (now - before.last_review).total_seconds() / 86400 if before.last_review else None
    scheduled_days = round((new_card.due - now).total_seconds() / 86400, 2)
    state_after = display_state(new_card, lapses)

    return {
        "fields": {
            "fsrs_state": _FSRS_STATE[new_card.state],
            "fsrs_step": new_card.step,
            "stability": new_card.stability,
            "difficulty": new_card.difficulty,
            "repetitions": (row["repetitions"] or 0) + 1,
            "lapses": lapses,
            "next_review_at": new_card.due.isoformat(),
            "interval_days": scheduled_days,
            "srs_state": state_after,
        },
        "log": {
            "state_before": display_state(before, row["lapses"] or 0),
            "state_after": state_after,
            "stability_before": before.stability,
            "stability_after": new_card.stability,
            "difficulty_before": before.difficulty,
            "difficulty_after": new_card.difficulty,
            "scheduled_days": scheduled_days,
            "elapsed_days": round(elapsed_days, 2) if elapsed_days is not None else None,
        },
    }


def preview(row, now: datetime | None = None) -> dict:
    """What each of the 4 ratings would produce, without persisting anything -
    the intervals shown on the rating buttons before the learner picks one."""
    now = now or datetime.now(tz.utc)
    out = {}
    for rating in RATINGS:
        new_card, _log = _apply(row, rating, now)
        out[rating] = {
            "interval_days": round((new_card.due - now).total_seconds() / 86400, 4),
            "next_review_at": new_card.due.isoformat(),
            "state": _DISPLAY_STATE[new_card.state],
        }
    return out


def day_bounds_utc(user_timezone: str, now: datetime | None = None) -> tuple[str, str]:
    """The [start, end) of "today" in the learner's own timezone, as UTC ISO
    strings - so daily new-card/review caps reset at their midnight, not UTC's."""
    now = now or datetime.now(tz.utc)
    try:
        local_now = now.astimezone(ZoneInfo(user_timezone))
    except Exception:
        local_now = now.astimezone(ZoneInfo("UTC"))
    local_midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = local_midnight.astimezone(tz.utc)
    end = (local_midnight + timedelta(days=1)).astimezone(tz.utc)
    return start.isoformat(), end.isoformat()


def _new_row(**overrides) -> dict:
    row = {
        "id": 1, "fsrs_state": 1, "fsrs_step": 0, "stability": None, "difficulty": None,
        "repetitions": 0, "lapses": 0,
        "next_review_at": datetime.now(tz.utc).isoformat(), "last_reviewed_at": None,
    }
    row.update(overrides)
    return row


def _demo():
    # Fuzzing (real FSRS jitters the final day count so cards don't all clump
    # on the same date) is exactly what the real `_scheduler` singleton
    # should use - but it makes exact-value comparisons flaky here, where the
    # point is to check the underlying stability/difficulty/state math, not
    # the cosmetic day-of-week spread. Swap it out for the self-check only.
    global _scheduler
    _real_scheduler = _scheduler
    _scheduler = fsrs.Scheduler(enable_fuzzing=False)
    try:
        _run_demo_assertions()
    finally:
        _scheduler = _real_scheduler
    print("srs self-check OK")


def _run_demo_assertions():
    now = datetime(2026, 1, 1, tzinfo=tz.utc)

    # A brand-new card is NEW until its first review.
    row = _new_row()
    assert display_state(_card_from_row(row)) == "NEW"

    # new card + Again -> stays in an early/short-interval state, no lapse yet
    # (lapses only count failures of an already-learned REVIEW card).
    out = review(row, "again", now)
    assert out["fields"]["lapses"] == 0
    assert out["fields"]["repetitions"] == 1
    assert out["log"]["state_before"] == "NEW"

    # new card + Good vs new card + Easy: Easy must not schedule sooner than Good.
    good = review(row, "good", now)
    easy = review(row, "easy", now)
    assert easy["fields"]["next_review_at"] >= good["fields"]["next_review_at"]

    # Simulate a card that graduated to REVIEW with some stability.
    reviewed = _new_row(
        fsrs_state=2, stability=8.0, difficulty=5.0, repetitions=3, lapses=0,
        last_reviewed_at=(now - timedelta(days=8)).isoformat(),
        next_review_at=now.isoformat(),
    )

    # review card + Again on a REVIEW card increments lapses and demotes the state.
    again = review(reviewed, "again", now)
    assert again["fields"]["lapses"] == 1
    assert again["log"]["state_before"] == "REVIEW"
    assert again["fields"]["srs_state"] in ("RELEARNING", "LEARNING", "REVIEW")

    # review card + Hard/Good/Easy: intervals must order Hard <= Good <= Easy -
    # this is the invariant that matters, not any specific day count (those
    # depend on the FSRS parameters/version, which can legitimately change).
    hard = review(reviewed, "hard", now)
    good2 = review(reviewed, "good", now)
    easy2 = review(reviewed, "easy", now)
    assert hard["fields"]["interval_days"] <= good2["fields"]["interval_days"] <= easy2["fields"]["interval_days"], \
        (hard["fields"]["interval_days"], good2["fields"]["interval_days"], easy2["fields"]["interval_days"])

    # Multiple successful reviews in a row should trend the interval upward.
    card = _new_row()
    prev_interval = -1.0
    r = None
    for _ in range(4):
        r = review(card, "good", now)
        assert r["fields"]["interval_days"] >= prev_interval
        prev_interval = r["fields"]["interval_days"]
        card = _new_row(
            fsrs_state=r["fields"]["fsrs_state"], fsrs_step=r["fields"]["fsrs_step"],
            stability=r["fields"]["stability"], difficulty=r["fields"]["difficulty"],
            repetitions=r["fields"]["repetitions"], lapses=r["fields"]["lapses"],
            last_reviewed_at=now.isoformat(),
            next_review_at=r["fields"]["next_review_at"],
        )
        now = now + timedelta(days=max(1, round(prev_interval)))

    # Multiple failures in a row should keep the interval short (never
    # allowed to run away upward the way a streak of Good/Easy does).
    card = _new_row(fsrs_state=2, stability=20.0, difficulty=6.0, repetitions=5, lapses=0,
                     last_reviewed_at=(now - timedelta(days=20)).isoformat(), next_review_at=now.isoformat())
    for _ in range(3):
        r = review(card, "again", now)
        assert r["fields"]["interval_days"] < 2, r["fields"]["interval_days"]
        card = _new_row(
            fsrs_state=r["fields"]["fsrs_state"], fsrs_step=r["fields"]["fsrs_step"],
            stability=r["fields"]["stability"], difficulty=r["fields"]["difficulty"],
            repetitions=r["fields"]["repetitions"], lapses=r["fields"]["lapses"],
            last_reviewed_at=now.isoformat(), next_review_at=r["fields"]["next_review_at"],
        )

    # Same card, same instant, reviewed "twice" (simulating a duplicate
    # request) must be fully deterministic - identical input, identical
    # output. In production the real scheduler also applies small day-of-
    # week fuzz (disabled here for exactness), so this proves the underlying
    # math has no *hidden* randomness; actual duplicate-submission
    # protection still lives at the API layer (a unique request_id), since
    # two genuinely independent requests a moment apart are not "the same
    # instant" and are allowed to fuzz differently.
    row = _new_row(fsrs_state=2, stability=10.0, difficulty=5.0, last_reviewed_at=(now - timedelta(days=5)).isoformat(),
                    next_review_at=now.isoformat())
    a = review(row, "good", now)
    b = review(row, "good", now)
    assert a["fields"]["next_review_at"] == b["fields"]["next_review_at"]
    assert a["fields"]["stability"] == b["fields"]["stability"]
    assert a["fields"]["difficulty"] == b["fields"]["difficulty"]

    # Preview must not mutate anything and must match what review() would do.
    p = preview(row, now)
    assert set(p.keys()) == set(RATINGS)
    applied = review(row, "good", now)
    assert p["good"]["interval_days"] == applied["fields"]["interval_days"]

    # Timezone boundary: Asia/Ho_Chi_Minh is UTC+7 year-round (no DST), so
    # local midnight on 2026-01-02 is 2026-01-01T17:00:00Z.
    start, end = day_bounds_utc("Asia/Ho_Chi_Minh", datetime(2026, 1, 2, 10, 0, tzinfo=tz.utc))
    assert start == "2026-01-01T17:00:00+00:00", start
    assert end == "2026-01-02T17:00:00+00:00", end
    # An unknown/garbage timezone falls back to UTC instead of crashing the scheduler.
    start_u, _ = day_bounds_utc("Not/AZone", datetime(2026, 1, 2, 10, 0, tzinfo=tz.utc))
    assert start_u == "2026-01-02T00:00:00+00:00", start_u


if __name__ == "__main__":
    _demo()
