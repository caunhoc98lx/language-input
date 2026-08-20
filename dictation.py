"""Comparing what the learner typed against what was actually said.

Word-level diff of the learner's dictation attempt versus the transcript, so the
UI can show exactly which words were missed, mis-heard or invented.

ponytail: difflib.SequenceMatcher from the standard library does the alignment.
No fuzzy-matching dependency, no edit-distance implementation to maintain.
"""
import difflib
import re

_PUNCT = re.compile(r"[^\w'\- ]+")


def tokens(text: str) -> list[str]:
    """Words as the learner should be judged on them: punctuation and case are
    not part of listening comprehension."""
    cleaned = _PUNCT.sub(" ", (text or "").lower().replace("’", "'"))
    return [w for w in cleaned.split() if w]


def compare(expected: str, typed: str) -> dict:
    """Diff a dictation attempt.

    Returns the transcript as marked-up tokens plus counts:
      words   - [{"word", "status"}] with status ok | missing | wrong
      extra   - words the learner typed that are not in the transcript
      accuracy - correct words / transcript words
    """
    want, got = tokens(expected), tokens(typed)
    matcher = difflib.SequenceMatcher(a=want, b=got, autojunk=False)

    words: list[dict] = []
    extra: list[str] = []
    correct = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            correct += i2 - i1
            words += [{"word": w, "status": "ok"} for w in want[i1:i2]]
        elif tag == "delete":
            words += [{"word": w, "status": "missing"} for w in want[i1:i2]]
        elif tag == "insert":
            extra += got[j1:j2]
        else:  # replace: heard something, but not the right word
            words += [{"word": w, "status": "wrong", "typed": " ".join(got[j1:j2])}
                      for w in want[i1:i2]]
            if (j2 - j1) > (i2 - i1):
                extra += got[j1 + (i2 - i1):j2]

    return {
        "words": words,
        "extra": extra,
        "correct": correct,
        "total": len(want),
        "missing": sum(1 for w in words if w["status"] == "missing"),
        "wrong": sum(1 for w in words if w["status"] == "wrong"),
        "accuracy": correct / len(want) if want else 0.0,
    }


def _demo():
    assert tokens("The government's plan — 2024!") == ["the", "government's", "plan", "2024"]
    assert tokens("") == []

    # Perfect dictation, ignoring case and punctuation.
    out = compare("The government has introduced a new policy.",
                  "the government has introduced a new policy")
    assert out["accuracy"] == 1.0 and out["missing"] == 0 and out["wrong"] == 0
    assert out["extra"] == [] and all(w["status"] == "ok" for w in out["words"])

    # A missing word is reported in place, so the UI can show the gap.
    out = compare("The government has introduced a new policy",
                  "The government introduced a new policy")
    assert out["missing"] == 1 and out["correct"] == 6
    assert [w["word"] for w in out["words"] if w["status"] == "missing"] == ["has"]
    assert round(out["accuracy"], 2) == 0.86

    # A mis-heard word is "wrong", and carries what the learner typed instead.
    out = compare("They discussed the council budget", "They discussed the counsel budget")
    assert out["wrong"] == 1
    wrong = next(w for w in out["words"] if w["status"] == "wrong")
    assert wrong["word"] == "council" and wrong["typed"] == "counsel"

    # Words that were never said are listed separately, not counted as correct.
    out = compare("She arrived early", "She actually arrived very early")
    assert out["correct"] == 3 and sorted(out["extra"]) == ["actually", "very"]
    assert out["accuracy"] == 1.0  # every transcript word was heard

    # Typing nothing scores zero but still returns the full transcript to study.
    out = compare("Some words here", "")
    assert out["accuracy"] == 0.0 and out["missing"] == 3 and len(out["words"]) == 3

    # An empty transcript cannot be scored, and must not divide by zero.
    assert compare("", "anything")["accuracy"] == 0.0

    print("dictation self-check OK")


if __name__ == "__main__":
    _demo()
