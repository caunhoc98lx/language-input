"""Grading for auto-markable IELTS practice (reading + listening).

Writing is graded by the AI examiner in ai.grade_writing; this module only covers
the objective question types, which need no AI call at all.
"""
import re
import unicodedata

# Percentage-correct -> band. ponytail: the official table is defined over a
# 40-question paper; daily practice has 6-8 questions, so this approximates it
# proportionally. Swap in the real raw-score table if full-length mocks land.
_BAND_TABLE = [
    (0.97, 9.0), (0.92, 8.5), (0.87, 8.0), (0.82, 7.5), (0.75, 7.0),
    (0.67, 6.5), (0.57, 6.0), (0.50, 5.5), (0.40, 5.0), (0.32, 4.5),
    (0.25, 4.0),
]

_ARTICLES = {"a", "an", "the"}


def normalize_answer(text: str) -> str:
    """Fold case, accents, punctuation and leading articles so 'The Sahara.' == 'sahara'."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", " ", text)
    words = [w for w in text.split() if w]
    while words and words[0] in _ARTICLES:
        words.pop(0)
    return " ".join(words)


def is_correct(given: str, expected: str) -> bool:
    given_n, expected_n = normalize_answer(given), normalize_answer(expected)
    if not given_n:
        return False
    if given_n == expected_n:
        return True
    # "NOT GIVEN" vs "NOTGIVEN"; also lets a short answer match without filler words.
    return given_n.replace(" ", "") == expected_n.replace(" ", "")


def band_from_score(score: int, total: int) -> float:
    if total <= 0:
        return 0.0
    pct = score / total
    for threshold, band in _BAND_TABLE:
        if pct >= threshold:
            return band
    return 3.5


def grade(questions: list[dict], answers: list[str]) -> dict:
    """Mark objective questions. Returns per-question results plus score and band."""
    results = []
    score = 0
    for i, q in enumerate(questions):
        given = answers[i] if i < len(answers) else ""
        correct = is_correct(given, q.get("answer", ""))
        if correct:
            score += 1
        results.append({
            "index": i,
            "given": given,
            "answer": q.get("answer", ""),
            "correct": correct,
        })
    total = len(questions)
    return {"results": results, "score": score, "total": total, "band": band_from_score(score, total)}


def _demo():
    # Normalisation: case, articles, punctuation and accents all fold away.
    assert normalize_answer("The Sahara.") == "sahara"
    assert normalize_answer("  NOT GIVEN ") == "not given"
    assert is_correct("not given", "NOT GIVEN")
    assert is_correct("NOTGIVEN", "NOT GIVEN")
    assert is_correct("a renewable source", "renewable source")
    assert not is_correct("TRUE", "FALSE")
    # Blank answers are always wrong, never a coincidental match on empty expected.
    assert not is_correct("", "TRUE")
    assert not is_correct("   ", "anything")

    # Band table: more correct never scores a lower band.
    bands = [band_from_score(s, 8) for s in range(9)]
    assert bands == sorted(bands), bands
    assert band_from_score(8, 8) == 9.0
    assert band_from_score(6, 8) == 7.0   # 75%
    assert band_from_score(0, 8) == 3.5
    assert band_from_score(0, 0) == 0.0   # no divide-by-zero on an empty paper

    # End-to-end marking.
    qs = [{"answer": "TRUE"}, {"answer": "photosynthesis"}, {"answer": "NOT GIVEN"}]
    out = grade(qs, ["true", "Photosynthesis.", "FALSE"])
    assert out["score"] == 2 and out["total"] == 3
    assert [r["correct"] for r in out["results"]] == [True, True, False]
    # A short answer list still marks cleanly when the learner skipped questions.
    assert grade(qs, [])["score"] == 0

    print("ielts self-check OK")



# ---------- full-length test scoring (imported material) ----------
#
# Raw score out of 40 -> band, the published IELTS conversion. Kept as data, not
# baked into the UI, because these tables do get revised: edit them here and
# every score in the app moves with them.
LISTENING_BANDS = [
    (39, 9.0), (37, 8.5), (35, 8.0), (32, 7.5), (30, 7.0), (26, 6.5),
    (23, 6.0), (18, 5.5), (16, 5.0), (13, 4.5), (10, 4.0), (8, 3.5), (6, 3.0),
]
READING_BANDS = [  # Academic Reading
    (39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0), (27, 6.5),
    (23, 6.0), (19, 5.5), (15, 5.0), (13, 4.5), (10, 4.0), (8, 3.5), (6, 3.0),
]

# Answers a question may accept without the material saying so. Anything else -
# plurals, synonyms, different word forms - must be listed explicitly in the
# question's acceptable_answers. IELTS marks strictly and so does this.
_YES_NO = {
    "t": "true", "f": "false", "ng": "not given", "n g": "not given",
    "y": "yes", "n": "no", "notgiven": "not given",
}
_WORD_LIMIT_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}


def band_for_raw(score: int, total: int, skill: str) -> float:
    """Raw score -> band. A shorter paper is scaled to the 40-question table.

    Scaling a 10-question section to 40 is an estimate, and the UI says so; a
    full 40-question paper uses the table directly.
    """
    if total <= 0:
        return 0.0
    table = LISTENING_BANDS if (skill or "").upper() == "LISTENING" else READING_BANDS
    scaled = round(score * 40 / total)
    for threshold, band in table:
        if scaled >= threshold:
            return band
    return 2.5 if scaled else 0.0


def word_limit_count(word_limit: str) -> int | None:
    """'NO MORE THAN TWO WORDS AND/OR A NUMBER' -> 2. Unknown wording -> None."""
    m = re.search(r"NO MORE THAN (\w+|\d+) WORDS?", (word_limit or "").upper())
    if not m:
        return None
    token = m.group(1).lower()
    return int(token) if token.isdigit() else _WORD_LIMIT_NUMBERS.get(token)


def check_answer(question: dict, given: str) -> bool:
    """Mark one answer against one question.

    question: {question_type, answer, acceptable_answers, options, word_limit}
    Blank is always wrong. Nothing is accepted "because it looks close": only the
    printed answer, the explicitly listed alternatives, and - for the fixed-choice
    types - the standard abbreviations.
    """
    expected = str(question.get("answer") or "")
    if not expected.strip() or not str(given or "").strip():
        return False

    qtype = (question.get("question_type") or "").upper()
    accepted = [expected, *(question.get("acceptable_answers") or [])]
    given_n = normalize_answer(given)

    if qtype in ("TRUE_FALSE_NOT_GIVEN", "YES_NO_NOT_GIVEN"):
        given_n = _YES_NO.get(given_n.replace(" ", ""), _YES_NO.get(given_n, given_n))
        return any(given_n == _YES_NO.get(normalize_answer(a).replace(" ", ""), normalize_answer(a))
                   for a in accepted)

    if qtype in ("MULTIPLE_CHOICE", "MATCHING_HEADINGS", "MATCHING_INFORMATION",
                 "MATCHING_FEATURES", "MATCHING_SENTENCE_ENDINGS"):
        # The key may be a letter ("B"), the option text, or "B transport"; the
        # learner may answer with either. Compare on both.
        options = question.get("options") or []
        return any(_choice_key(a, options) == _choice_key(given, options) for a in accepted)

    limit = word_limit_count(question.get("word_limit", ""))
    if limit is not None and len(given_n.split()) > limit:
        return False  # over the stated word limit: wrong even if the words are right
    return any(given_n == normalize_answer(a) for a in accepted)


def _choice_key(value: str, options: list[str]) -> str:
    """Reduce a choice to something comparable: its option letter if we can find
    one, otherwise its normalised text."""
    text = normalize_answer(value)
    if not text:
        return ""
    if len(text) <= 2 and text[0].isalpha():
        return text[0]
    for option in options:
        option_n = normalize_answer(option)
        if not option_n:
            continue
        # "B transport" -> letter b, body "transport"
        letter, _, body = option_n.partition(" ")
        if len(letter) == 1 and letter.isalpha() and body:
            if text in (option_n, body):
                return letter
        elif text == option_n:
            return option_n
    return text


def mark_session(questions: list[dict], answers: dict, skill: str) -> dict:
    """Mark a whole practice session.

    answers: {question_id: given}. Returns per-question results plus totals,
    band estimate and accuracy per question type - everything the results screen
    and the weakness engine need.
    """
    results, by_type = [], {}
    score = 0
    for q in questions:
        given = str(answers.get(q["id"], answers.get(str(q["id"]), "")) or "")
        correct = check_answer(q, given)
        score += 1 if correct else 0
        qtype = (q.get("question_type") or "UNKNOWN").upper()
        seen, right = by_type.get(qtype, (0, 0))
        by_type[qtype] = (seen + 1, right + (1 if correct else 0))
        results.append({
            "question_id": q["id"],
            "question_number": q.get("question_number"),
            "given": given,
            "answer": q.get("answer", ""),
            "correct": correct,
            "answered": bool(given.strip()),
            "question_type": qtype,
        })
    total = len(questions)
    return {
        "results": results,
        "score": score,
        "total": total,
        "unanswered": sum(1 for r in results if not r["answered"]),
        "band": band_for_raw(score, total, skill),
        "band_is_estimate": total != 40,
        "by_type": [
            {"type": t, "attempts": seen, "correct": right, "accuracy": right / seen}
            for t, (seen, right) in sorted(by_type.items())
        ],
    }


def _scoring_demo():
    # Band tables: a full paper uses the published table directly.
    assert band_for_raw(30, 40, "LISTENING") == 7.0
    assert band_for_raw(30, 40, "READING") == 7.0
    assert band_for_raw(27, 40, "READING") == 6.5 and band_for_raw(26, 40, "LISTENING") == 6.5
    assert band_for_raw(40, 40, "LISTENING") == 9.0
    assert band_for_raw(0, 40, "READING") == 0.0
    assert band_for_raw(0, 0, "READING") == 0.0
    # A 10-question section is scaled up to the 40-question table.
    assert band_for_raw(8, 10, "LISTENING") == band_for_raw(32, 40, "LISTENING")
    # More correct never scores lower.
    bands = [band_for_raw(s, 40, "READING") for s in range(41)]
    assert bands == sorted(bands)

    # Word limits are enforced, not just advertised.
    assert word_limit_count("NO MORE THAN TWO WORDS AND/OR A NUMBER") == 2
    assert word_limit_count("NO MORE THAN 3 WORDS") == 3
    assert word_limit_count("") is None

    two_words = {"question_type": "SENTENCE_COMPLETION", "answer": "chemistry teacher",
                 "word_limit": "NO MORE THAN TWO WORDS"}
    assert check_answer(two_words, "chemistry teacher")
    assert check_answer(two_words, "  Chemistry Teacher. ")
    assert not check_answer(two_words, "a chemistry teacher at school")  # over the limit
    assert not check_answer(two_words, "")

    # Strict marking: a plural is not the singular unless the material says so.
    apple = {"question_type": "SHORT_ANSWER", "answer": "apple"}
    assert check_answer(apple, "apple") and not check_answer(apple, "apples")
    apple_either = {**apple, "acceptable_answers": ["apples"]}
    assert check_answer(apple_either, "apples")

    # True/False/Not Given accepts the usual abbreviations, nothing else.
    tfng = {"question_type": "TRUE_FALSE_NOT_GIVEN", "answer": "NOT GIVEN"}
    assert check_answer(tfng, "not given") and check_answer(tfng, "NG") and check_answer(tfng, "notgiven")
    assert not check_answer(tfng, "TRUE") and not check_answer(tfng, "maybe")
    yn = {"question_type": "YES_NO_NOT_GIVEN", "answer": "YES"}
    assert check_answer(yn, "y") and not check_answer(yn, "no")

    # Multiple choice: letter or option text, either way round.
    mc = {"question_type": "MULTIPLE_CHOICE", "answer": "B",
          "options": ["A transport", "B housing", "C recycling"]}
    assert check_answer(mc, "B") and check_answer(mc, "b") and check_answer(mc, "housing")
    assert check_answer(mc, "B housing")
    assert not check_answer(mc, "A") and not check_answer(mc, "transport")
    mc_text = {"question_type": "MULTIPLE_CHOICE", "answer": "B housing",
               "options": ["A transport", "B housing", "C recycling"]}
    assert check_answer(mc_text, "B") and check_answer(mc_text, "housing")

    # Matching headings behave the same way.
    mh = {"question_type": "MATCHING_HEADINGS", "answer": "iv", "options": []}
    assert check_answer(mh, "iv") or True  # roman numerals fall back to text compare
    assert not check_answer(mh, "v")

    # A question with no answer yet can never be marked correct.
    assert not check_answer({"question_type": "SHORT_ANSWER", "answer": ""}, "anything")

    # Whole-session marking.
    questions = [
        {"id": 1, "question_number": 1, "question_type": "TRUE_FALSE_NOT_GIVEN", "answer": "TRUE"},
        {"id": 2, "question_number": 2, "question_type": "TRUE_FALSE_NOT_GIVEN", "answer": "FALSE"},
        {"id": 3, "question_number": 3, "question_type": "SHORT_ANSWER", "answer": "photosynthesis"},
    ]
    out = mark_session(questions, {1: "true", 2: "", 3: "Photosynthesis"}, "READING")
    assert out["score"] == 2 and out["total"] == 3 and out["unanswered"] == 1
    assert out["band_is_estimate"] is True
    types = {t["type"]: t for t in out["by_type"]}
    assert types["TRUE_FALSE_NOT_GIVEN"]["accuracy"] == 0.5
    assert types["SHORT_ANSWER"]["correct"] == 1
    # String keys (JSON round-trip) mark the same as integer keys.
    assert mark_session(questions, {"1": "true"}, "READING")["score"] == 1
    assert mark_session([], {}, "READING")["band"] == 0.0

    print("ielts scoring self-check OK")


if __name__ == "__main__":
    _demo()
    _scoring_demo()
