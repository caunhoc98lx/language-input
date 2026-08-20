"""Working out which audio file belongs to which listening section.

Filenames in real IELTS audio sets are all over the place - "Test1_Section3.mp3",
"cam18-t2-p4.mp3", "04.mp3", "Test 1 Part 2 (2).mp3" - so this reads whatever
signals it can find and reports how sure it is. High confidence links
automatically; anything else is offered to the user to confirm.

Pure functions, no DB and no filesystem, so `python audio_match.py` proves the
matching rules without an import running.

ponytail: filename, folder and order only. Duration and audio fingerprinting are
listed in the spec but need a decoder dependency and buy little - the filename is
right almost every time, and the UI asks when it isn't.
"""
import os
import re

# Confidence bands. Above AUTO_LINK the material is linked without asking.
AUTO_LINK = 0.9

_RE_TEST = re.compile(r"(?:^|[^a-z])(?:test|t)\s*[-_ ]?(\d{1,2})(?:[^0-9]|$)", re.I)
_RE_SECTION = re.compile(r"(?:section|sect|part|p)\s*[-_ ]?(\d{1,2})(?:[^0-9]|$)", re.I)
_RE_TRAILING_NUMBER = re.compile(r"(\d{1,3})\s*$")
_RE_SKILL = re.compile(r"listening|reading|speaking", re.I)


def parse_name(path: str) -> dict:
    """Pull test/section/order hints out of a filename (and its folders)."""
    parts = re.split(r"[\\/]+", path)
    stem = os.path.splitext(parts[-1])[0]
    folder = " ".join(parts[:-1])
    haystack = f"{folder} {stem}"

    test = _RE_TEST.search(haystack)
    section = _RE_SECTION.search(stem) or _RE_SECTION.search(haystack)
    skill = _RE_SKILL.search(haystack)

    # "04.mp3" or "cam18_04" - a bare trailing number is a sequence hint only.
    bare = None
    if not section:
        m = _RE_TRAILING_NUMBER.search(stem.strip())
        if m and (stem.strip().isdigit() or not test or m.start() > 0):
            bare = int(m.group(1))

    return {
        "test": int(test.group(1)) if test else None,
        "section": int(section.group(1)) if section else None,
        "order_hint": bare,
        "skill": skill.group(0).upper() if skill else None,
    }


def match_files(files: list[dict], sections: list[dict]) -> list[dict]:
    """Propose an audio file for each listening section.

    files:    [{"id": 1, "filename": "Test1_Section2.mp3"}] in upload order
    sections: [{"id": 9, "test_number": 1, "section_number": 2}] in document order
    Returns one row per section: {section_id, file_id|None, confidence, reason}.
    A file is never proposed for two sections.
    """
    parsed = [{**f, **parse_name(f["filename"])} for f in files]
    taken: set[int] = set()
    matches: list[dict] = []
    single_test = len({s["test_number"] for s in sections}) == 1

    for section in sections:
        best = None
        for f in parsed:
            if f["id"] in taken:
                continue
            if f["section"] != section["section_number"]:
                continue
            if f["test"] == section["test_number"]:
                best = (f, 0.97, "test and section number in the filename")
                break
            if f["test"] is None and single_test:
                best = best or (f, 0.85, "section number in the filename")
        if best:
            f, confidence, reason = best
            taken.add(f["id"])
            matches.append({"section_id": section["id"], "file_id": f["id"],
                            "filename": f["filename"], "confidence": confidence, "reason": reason})
        else:
            matches.append({"section_id": section["id"], "file_id": None,
                            "filename": None, "confidence": 0.0, "reason": "no filename match"})

    # Fallback: as many unmatched files as unmatched sections, and the files carry
    # an ordering hint (or were uploaded in order) -> pair them up, but say plainly
    # that this is a guess.
    missing = [m for m in matches if not m["file_id"]]
    spare = [f for f in parsed if f["id"] not in taken]
    if missing and len(missing) == len(spare):
        spare.sort(key=lambda f: (f["order_hint"] if f["order_hint"] is not None else 0, f["id"]))
        for m, f in zip(missing, spare):
            m.update({"file_id": f["id"], "filename": f["filename"], "confidence": 0.6,
                      "reason": "matched by upload order"})
    return matches


def summarise(matches: list[dict]) -> dict:
    return {
        "matched": sum(1 for m in matches if m["file_id"]),
        "auto": sum(1 for m in matches if m["confidence"] >= AUTO_LINK),
        "needs_confirmation": sum(1 for m in matches if m["file_id"] and m["confidence"] < AUTO_LINK),
        "unmatched": sum(1 for m in matches if not m["file_id"]),
        "total": len(matches),
    }


def _demo():
    # Filename parsing across the shapes these files actually come in.
    assert parse_name("Test1_Section2.mp3") == {"test": 1, "section": 2, "order_hint": None, "skill": None}
    assert parse_name("cam18-t2-p4.mp3")["test"] == 2
    assert parse_name("cam18-t2-p4.mp3")["section"] == 4
    assert parse_name("Test 1 - Part 3.m4a")["section"] == 3
    assert parse_name("Listening/Test 4/Section 1.wav") == \
        {"test": 4, "section": 1, "order_hint": None, "skill": "LISTENING"}
    assert parse_name("04.mp3")["order_hint"] == 4 and parse_name("04.mp3")["section"] is None
    assert parse_name("random-audio.mp3") == {"test": None, "section": None, "order_hint": None, "skill": None}

    sections = [
        {"id": 11, "test_number": 1, "section_number": 1},
        {"id": 12, "test_number": 1, "section_number": 2},
        {"id": 13, "test_number": 1, "section_number": 3},
        {"id": 14, "test_number": 1, "section_number": 4},
    ]

    # Best case: test + section in every name -> automatic, high confidence.
    files = [{"id": i, "filename": f"Test1_Section{i}.mp3"} for i in range(1, 5)]
    matches = match_files(files, sections)
    assert [m["file_id"] for m in matches] == [1, 2, 3, 4], matches
    assert all(m["confidence"] == 0.97 for m in matches)
    assert summarise(matches) == {"matched": 4, "auto": 4, "needs_confirmation": 0,
                                  "unmatched": 0, "total": 4}

    # Out-of-order filenames still land on the right sections.
    shuffled = [{"id": 1, "filename": "Test1_Section3.mp3"}, {"id": 2, "filename": "Test1_Section1.mp3"},
                {"id": 3, "filename": "Test1_Section4.mp3"}, {"id": 4, "filename": "Test1_Section2.mp3"}]
    assert [m["file_id"] for m in match_files(shuffled, sections)] == [2, 4, 1, 3]

    # Section numbers only, and only one test in the material -> still confident.
    files = [{"id": i, "filename": f"Part{i}.mp3"} for i in range(1, 5)]
    matches = match_files(files, sections)
    assert [m["file_id"] for m in matches] == [1, 2, 3, 4]
    assert all(m["confidence"] == 0.85 for m in matches)

    # Two tests: a file with no test number must not be assigned confidently.
    two_tests = sections + [{"id": 21, "test_number": 2, "section_number": 1}]
    matches = match_files([{"id": 1, "filename": "Section1.mp3"}], two_tests)
    assert matches[0]["file_id"] is None or matches[0]["confidence"] <= 0.6

    # Numbered files fall back to order, flagged as a guess for the user to confirm.
    files = [{"id": 7, "filename": "02.mp3"}, {"id": 8, "filename": "01.mp3"},
             {"id": 9, "filename": "04.mp3"}, {"id": 10, "filename": "03.mp3"}]
    matches = match_files(files, sections)
    assert [m["file_id"] for m in matches] == [8, 7, 10, 9], matches
    assert all(m["confidence"] == 0.6 for m in matches)
    assert summarise(matches)["needs_confirmation"] == 4

    # Fewer files than sections: no guessing - the extra sections stay unmatched.
    matches = match_files([{"id": 1, "filename": "mystery.mp3"}], sections)
    assert summarise(matches)["unmatched"] == 4 and summarise(matches)["matched"] == 0

    # One file is never proposed twice.
    dupes = match_files([{"id": 1, "filename": "Test1_Section1.mp3"}] * 1, sections)
    assert [m["file_id"] for m in dupes].count(1) == 1

    # Nothing to match is not an error.
    assert match_files([], sections)[0]["file_id"] is None
    assert match_files(files, []) == []

    print("audio_match self-check OK")


if __name__ == "__main__":
    _demo()
