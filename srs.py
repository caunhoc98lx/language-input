"""Spaced repetition scheduling.

ponytail: SM-2 (well-understood, ~30 lines), not FSRS. FSRS needs a
history-fitted parameter set to earn its complexity; upgrade to it once
there's enough review history to tune it and retention data shows SM-2
falling short.
"""
from datetime import datetime, timedelta, timezone

RATINGS = ("again", "hard", "good", "easy")


def review(ease: float, interval_days: float, repetitions: int, lapses: int, rating: str, now=None):
    """Given current SRS state + a rating, return the next state.

    Returns dict: ease, interval_days, repetitions, lapses, state, next_review_at
    """
    if rating not in RATINGS:
        raise ValueError(f"invalid rating: {rating}")
    now = now or datetime.now(timezone.utc)

    if rating == "again":
        repetitions = 0
        interval_days = 1.0
        lapses += 1
        ease = max(1.3, ease - 0.2)
    else:
        if repetitions == 0:
            interval_days = 1.0
        elif repetitions == 1:
            interval_days = 6.0
        else:
            interval_days = round(interval_days * ease, 1)
        repetitions += 1

        if rating == "hard":
            ease = max(1.3, ease - 0.15)
            interval_days = max(1.0, round(interval_days * 0.8, 1))
        elif rating == "easy":
            ease = ease + 0.15
            interval_days = round(interval_days * 1.3, 1)

    if repetitions >= 4 and interval_days >= 60:
        state = "MASTERED"
    elif interval_days >= 21:
        state = "REVIEW"
    elif repetitions == 0:
        state = "RELEARNING" if lapses > 0 else "NEW"
    else:
        state = "LEARNING"

    next_review_at = now + timedelta(days=interval_days)
    return {
        "ease": round(ease, 2),
        "interval_days": interval_days,
        "repetitions": repetitions,
        "lapses": lapses,
        "state": state,
        "next_review_at": next_review_at.isoformat(),
    }


def _demo():
    # New card, repeatedly rated "good" -> interval should grow monotonically.
    ease, interval, reps, lapses = 2.5, 0.0, 0, 0
    intervals = []
    for _ in range(4):
        r = review(ease, interval, reps, lapses, "good")
        ease, interval, reps, lapses = r["ease"], r["interval_days"], r["repetitions"], r["lapses"]
        intervals.append(interval)
    assert intervals == sorted(intervals), f"intervals should grow: {intervals}"
    assert intervals[0] == 1.0 and intervals[1] == 6.0

    # "Again" always resets repetitions and shrinks the interval back to 1 day.
    r = review(ease=2.8, interval_days=40.0, repetitions=5, lapses=0, rating="again")
    assert r["repetitions"] == 0
    assert r["interval_days"] == 1.0
    assert r["lapses"] == 1
    assert r["state"] == "RELEARNING"

    # Mastery requires both enough repetitions and a long interval.
    r = review(ease=2.6, interval_days=55.0, repetitions=4, lapses=0, rating="good")
    assert r["state"] == "MASTERED"

    print("srs self-check OK")


if __name__ == "__main__":
    _demo()
