"""The coaching brain: turns practice history into band estimates, weak areas
and a plan for today.

Pure functions over rows the caller has already fetched - no DB access here, so
it is testable with `python coach.py` and reusable from any route.

ponytail: no StudyPlan/StudyTask tables. Today's plan is derived from state the
app already stores (due cards, recent attempts, daily goal) and recomputed on
each dashboard load. Persist it only when the user needs to tick tasks off or
edit the plan by hand.
"""
import math
from datetime import date, timedelta

SKILLS = ("listening", "reading", "writing", "speaking")

# A question type needs at least this many answered questions before we are
# willing to call it a weakness - two wrong answers out of three is noise.
MIN_ATTEMPTS_FOR_WEAKNESS = 6
WEAK_ACCURACY = 0.75

# Question types have one canonical spelling across the whole app: the one the
# imported-material schema uses. AI-generated daily practice writes its own
# looser names, so they are folded in here - otherwise the same weakness would
# be counted as two separate ones and never cross the evidence threshold.
TYPE_ALIASES = {
    "TRUE_FALSE_NOTGIVEN": "TRUE_FALSE_NOT_GIVEN",
    "TFNG": "TRUE_FALSE_NOT_GIVEN",
    "YES_NO_NOTGIVEN": "YES_NO_NOT_GIVEN",
    "YNNG": "YES_NO_NOT_GIVEN",
    "MCQ": "MULTIPLE_CHOICE",
    "GAP_FILL": "SENTENCE_COMPLETION",
    "FILL_BLANK": "SENTENCE_COMPLETION",
    "DIAGRAM_LABELLING": "DIAGRAM_LABELING",
    "MAP_LABELLING": "MAP_LABELING",
}

TYPE_LABELS = {
    "MULTIPLE_CHOICE": "Multiple Choice",
    "TRUE_FALSE_NOT_GIVEN": "True / False / Not Given",
    "YES_NO_NOT_GIVEN": "Yes / No / Not Given",
    "MATCHING_HEADINGS": "Matching Headings",
    "MATCHING_INFORMATION": "Matching Information",
    "MATCHING_FEATURES": "Matching Features",
    "MATCHING_SENTENCE_ENDINGS": "Matching Sentence Endings",
    "SENTENCE_COMPLETION": "Sentence Completion",
    "SUMMARY_COMPLETION": "Summary Completion",
    "NOTE_COMPLETION": "Note Completion",
    "TABLE_COMPLETION": "Table Completion",
    "FORM_COMPLETION": "Form Completion",
    "FLOW_CHART_COMPLETION": "Flow-chart Completion",
    "SHORT_ANSWER": "Short Answer",
    "DIAGRAM_LABELING": "Diagram Labelling",
    "MAP_LABELING": "Map / Plan Labelling",
    "ESSAY": "Writing Task",
    "SPEAKING": "Speaking",
}


def canonical_type(question_type: str) -> str:
    key = (question_type or "unknown").strip().upper().replace(" ", "_").replace("-", "_").replace("/", "_")
    return TYPE_ALIASES.get(key, key)


def label_for(question_type: str) -> str:
    key = canonical_type(question_type)
    return TYPE_LABELS.get(key, key.replace("_", " ").title())


def _round_half(x: float) -> float:
    """IELTS bands come in .0 / .5 steps, and a .25 average rounds up - so this
    is floor(x+0.5), not Python's round(), which rounds 6.25 down to 6.0."""
    return math.floor(x * 2 + 0.5) / 2


def skill_bands(attempts: list[dict]) -> dict:
    """Latest-weighted band per skill from graded attempts.

    attempts: [{"skill": "reading", "band": 6.5}, ...] newest first.
    Uses the mean of the 5 most recent attempts per skill - one lucky test
    shouldn't move the estimate, and one bad day shouldn't either.
    """
    by_skill: dict[str, list[float]] = {}
    for a in attempts:
        band = a.get("band")
        skill = (a.get("skill") or "").lower()
        if band is None or skill not in SKILLS:
            continue
        by_skill.setdefault(skill, [])
        if len(by_skill[skill]) < 5:
            by_skill[skill].append(float(band))
    return {s: _round_half(sum(v) / len(v)) for s, v in by_skill.items() if v}


def overall_band(bands: dict, fallback: float | None = None) -> float | None:
    """IELTS overall = mean of the four skills, rounded to the nearest half.

    ponytail: with fewer than four skills practised this averages what exists
    and is therefore an estimate, not a real overall - the UI labels it as such.
    """
    if not bands:
        return fallback
    return _round_half(sum(bands.values()) / len(bands))


def question_type_accuracy(graded: list[dict]) -> list[dict]:
    """Tally accuracy per question type.

    graded: [{"type": "matching_headings", "correct": True}, ...]
    Returns every type seen, worst accuracy first.
    """
    tally: dict[str, list[int]] = {}
    for g in graded:
        qtype = canonical_type(g.get("type"))
        seen, right = tally.setdefault(qtype, [0, 0])
        tally[qtype] = [seen + 1, right + (1 if g.get("correct") else 0)]
    out = [
        {
            "type": qtype,
            "label": label_for(qtype),
            "attempts": seen,
            "correct": right,
            "accuracy": right / seen,
        }
        for qtype, (seen, right) in tally.items()
        if seen
    ]
    out.sort(key=lambda r: (r["accuracy"], -r["attempts"]))
    return out


def weak_areas(accuracy_rows: list[dict], limit: int = 4) -> list[dict]:
    """The types worth spending time on: enough evidence, and below target."""
    return [
        r for r in accuracy_rows
        if r["attempts"] >= MIN_ATTEMPTS_FOR_WEAKNESS and r["accuracy"] < WEAK_ACCURACY
    ][:limit]


def todays_plan(*, due_cards: int, new_cards: int, weak: list[dict],
                done_today: set[str], minutes: int = 30, mistakes: int = 0,
                grammar_topic: str = "") -> list[dict]:
    """Build the "what should I study right now" list.

    done_today: kinds already completed today, e.g. {"reading", "vocabulary"}.
    Every task links to a page that actually exists - no placeholders.
    Returns tasks totalling roughly `minutes`; always returns at least one.
    """
    budget = max(10, minutes)
    plan: list[dict] = []

    def add(kind, title, detail, mins, href):
        nonlocal budget
        if budget <= 0:
            return
        mins = min(mins, budget)
        budget -= mins
        plan.append({"kind": kind, "title": title, "detail": detail,
                     "minutes": mins, "href": href, "done": kind in done_today})

    if due_cards and "vocabulary" not in done_today:
        # ~4 cards a minute at review speed, capped at a third of the session.
        mins = max(5, min(round(due_cards / 4), round(budget / 3)))
        add("vocabulary", f"Review {due_cards} vocabulary cards",
            "Due for spaced repetition today", mins, "/study/flashcards")

    if weak:
        top = weak[0]
        add("weakness", f"Practice {top['label']}",
            f"{round(top['accuracy'] * 100)}% accuracy over {top['attempts']} questions",
            min(20, max(10, round(budget / 2))), "/practice")

    if mistakes:
        add("mistakes", f"Redo {min(mistakes, 10)} questions you got wrong",
            "Questions you have never answered correctly", min(10, budget), "/practice")

    if grammar_topic:
        add("grammar", f"Fix your {grammar_topic} mistakes",
            "The grammar point the examiner flagged most often", min(10, budget), "/writing")

    for kind, title, detail, href in (
        ("listening", "Listening practice", "Today's listening task", "/daily/listening"),
        ("reading", "Reading practice", "Today's reading passage", "/daily/reading"),
        ("writing", "Writing Task 2", "Today's essay, graded by AI", "/daily/writing"),
    ):
        if kind not in done_today:
            add(kind, title, detail, min(20, budget), href)

    if new_cards and budget > 0:
        add("new-vocabulary", f"Learn {min(new_cards, 10)} new words",
            "Words you have saved but not studied yet", budget, "/study/learn")

    if not plan:
        add("capture", "Add new vocabulary",
            "Paste a text and let AI extract IELTS words", budget or 10, "/vocabulary/new")
    return plan


def week_window(today: date | None = None) -> tuple[str, str]:
    """ISO date bounds for the current week, Monday-based."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat(), (monday + timedelta(days=7)).isoformat()


def _demo():
    assert _round_half(6.24) == 6.0 and _round_half(6.25) == 6.5 and _round_half(6.8) == 7.0

    # Band estimate averages recent attempts per skill, ignoring ungraded ones.
    bands = skill_bands([
        {"skill": "reading", "band": 7.0}, {"skill": "reading", "band": 6.0},
        {"skill": "listening", "band": 6.5}, {"skill": "writing", "band": None},
        {"skill": "nonsense", "band": 9.0},
    ])
    assert bands == {"reading": 6.5, "listening": 6.5}, bands
    assert overall_band(bands) == 6.5
    assert overall_band({}, fallback=5.5) == 5.5
    assert overall_band({}) is None

    # Only the 5 most recent attempts count, so old scores age out.
    many = [{"skill": "reading", "band": 8.0}] * 5 + [{"skill": "reading", "band": 4.0}] * 5
    assert skill_bands(many) == {"reading": 8.0}

    # Accuracy tally, worst type first.
    graded = (
        [{"type": "matching_headings", "correct": False}] * 4 +
        [{"type": "matching_headings", "correct": True}] * 2 +
        [{"type": "multiple_choice", "correct": True}] * 9 +
        [{"type": "multiple_choice", "correct": False}] * 1 +
        [{"type": "short_answer", "correct": False}] * 2
    )
    acc = question_type_accuracy(graded)
    assert [r["type"] for r in acc] == ["SHORT_ANSWER", "MATCHING_HEADINGS", "MULTIPLE_CHOICE"], acc
    assert round(acc[1]["accuracy"], 2) == 0.33 and acc[1]["label"] == "Matching Headings"
    # Legacy daily-practice spellings fold onto the canonical type.
    assert question_type_accuracy([{"type": "true_false_notgiven", "correct": True}])[0]["type"] == "TRUE_FALSE_NOT_GIVEN"
    assert question_type_accuracy([]) == []

    # SHORT_ANSWER is worse but has only 2 attempts -> not enough evidence to call it weak.
    weak = weak_areas(acc)
    assert [w["type"] for w in weak] == ["MATCHING_HEADINGS"], weak

    # Plan: fits the budget, links exist, finished work is not re-suggested.
    plan = todays_plan(due_cards=24, new_cards=10, weak=weak, done_today=set(), minutes=60)
    assert sum(t["minutes"] for t in plan) <= 60
    assert plan[0]["kind"] == "vocabulary" and plan[1]["kind"] == "weakness"
    assert all(t["href"].startswith("/") for t in plan)

    # Outstanding mistakes and a repeated grammar error each earn a slot.
    plan = todays_plan(due_cards=0, new_cards=0, weak=[], done_today=set(), minutes=60,
                       mistakes=7, grammar_topic="Articles")
    kinds = [t["kind"] for t in plan]
    assert "mistakes" in kinds and "grammar" in kinds, kinds
    assert next(t for t in plan if t["kind"] == "mistakes")["title"] == "Redo 7 questions you got wrong"
    assert sum(t["minutes"] for t in plan) <= 60

    plan = todays_plan(due_cards=0, new_cards=0, weak=[],
                       done_today={"reading", "listening", "writing"}, minutes=30)
    assert len(plan) == 1 and plan[0]["kind"] == "capture"  # never an empty plan

    plan = todays_plan(due_cards=8, new_cards=0, weak=[], done_today={"vocabulary"}, minutes=30)
    assert all(t["kind"] != "vocabulary" for t in plan)

    # A tiny budget still yields something to do, and never negative minutes.
    plan = todays_plan(due_cards=100, new_cards=50, weak=weak, done_today=set(), minutes=1)
    assert plan and all(t["minutes"] > 0 for t in plan)

    monday, next_monday = week_window(date(2026, 8, 20))  # a Thursday
    assert monday == "2026-08-17" and next_monday == "2026-08-24"

    print("coach self-check OK")


if __name__ == "__main__":
    _demo()
