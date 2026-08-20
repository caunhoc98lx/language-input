"""Turning extracted page text into IELTS structure.

Two layers, cheapest first:

1. `outline()` - regex over page text finds tests, skills, sections and question
   ranges. Free, deterministic, and testable without an API key. It is what
   produces the "4 tests, 16 listening sections, 12 reading passages" summary.
2. `extract_section()` - one AI call per detected section, over that section's
   pages only, returning schema-validated questions.

ponytail: the whole document is never sent to the model. Layer 1 decides which
page ranges are worth a call, which is where the cost actually lives.

Nothing here invents content: if a section cannot be parsed it comes back
flagged NEEDS_REVIEW with its page text intact, for the review screen to fix.
"""
import re

from pydantic import BaseModel, Field, field_validator

import ai

SKILLS = ("LISTENING", "READING", "WRITING", "SPEAKING")

QUESTION_TYPES = {
    "MULTIPLE_CHOICE", "TRUE_FALSE_NOT_GIVEN", "YES_NO_NOT_GIVEN",
    "MATCHING_HEADINGS", "MATCHING_INFORMATION", "MATCHING_FEATURES",
    "MATCHING_SENTENCE_ENDINGS", "SENTENCE_COMPLETION", "SUMMARY_COMPLETION",
    "NOTE_COMPLETION", "TABLE_COMPLETION", "FORM_COMPLETION", "FLOW_CHART_COMPLETION",
    "DIAGRAM_LABELING", "MAP_LABELING", "SHORT_ANSWER", "ESSAY", "SPEAKING",
}

# --- page classification -----------------------------------------------------

_RE_TEST = re.compile(r"\bTEST\s+(\d{1,2})\b", re.I)
_RE_SECTION = re.compile(r"\bSECTION\s+(\d{1,2})\b", re.I)
_RE_PART = re.compile(r"\bPART\s+(\d{1,2})\b", re.I)
_RE_PASSAGE = re.compile(r"\bREADING\s+PASSAGE\s+(\d{1,2})\b", re.I)
_RE_TASK = re.compile(r"\b(?:WRITING\s+)?TASK\s+(\d{1,2})\b", re.I)
_RE_QUESTIONS = re.compile(r"\bQUESTIONS?\s+(\d{1,3})\s*[-‐-―]\s*(\d{1,3})\b", re.I)
_RE_ANSWER_KEY = re.compile(r"\bANSWER\s*KEYS?\b|\bANSWERS\b", re.I)
_RE_TRANSCRIPT = re.compile(r"\bAUDIO\s*SCRIPTS?\b|\bTRANSCRIPTS?\b|\bTAPESCRIPTS?\b", re.I)
_RE_WORD_LIMIT = re.compile(
    r"\bNO\s+MORE\s+THAN\s+(ONE|TWO|THREE|FOUR|\d+)\s+WORDS?(?:\s+AND/OR\s+A\s+NUMBER)?", re.I)


def _skill_in(text: str) -> str | None:
    """The first skill heading on the page, by position - a page can mention
    'Reading' in passing after its real 'LISTENING' heading."""
    found = [(m.start(), s) for s in SKILLS for m in [re.search(rf"\b{s}\b", text, re.I)] if m]
    if not found:
        return None
    return min(found)[1]


def classify_page(text: str) -> dict:
    """Structural markers found on a single page. Everything may be None."""
    head = text[:600]  # headings live at the top; body prose is noise here
    skill = _skill_in(head)
    passage = _RE_PASSAGE.search(head)
    if passage:
        skill = "READING"
    section_no = None
    if passage:
        section_no = int(passage.group(1))
    elif m := _RE_SECTION.search(head):
        section_no = int(m.group(1))
    elif m := _RE_PART.search(head):
        section_no = int(m.group(1))
    elif skill == "WRITING" and (m := _RE_TASK.search(head)):
        section_no = int(m.group(1))

    q = _RE_QUESTIONS.search(text)
    test = _RE_TEST.search(head)
    is_key = bool(_RE_ANSWER_KEY.search(head))
    return {
        "test_number": int(test.group(1)) if test else None,
        "skill": skill,
        "section_number": section_no,
        "first_question": int(q.group(1)) if q else None,
        "last_question": int(q.group(2)) if q else None,
        "is_answer_key": is_key,
        "is_transcript": bool(_RE_TRANSCRIPT.search(head)) and not is_key,
    }


def outline(pages: list[dict]) -> dict:
    """Group classified pages into sections.

    pages: [{"page_number": 1, "text": "..."}] in document order.
    Returns {"tests": [...], "sections": [...], "answer_key_pages": [...],
             "transcript_pages": [...]}, where each section carries its page
    range and, when the document stated one, its question range.
    """
    sections: list[dict] = []
    answer_key_pages: list[int] = []
    transcript_pages: list[int] = []
    test_no, skill, section_no = None, None, None

    for page in pages:
        text = page.get("text") or ""
        num = page["page_number"]
        marks = classify_page(text)

        if marks["is_answer_key"]:
            answer_key_pages.append(num)
        if marks["is_transcript"]:
            transcript_pages.append(num)
        if marks["test_number"]:
            test_no = marks["test_number"]
        if marks["skill"]:
            skill = marks["skill"]
            if not marks["section_number"]:
                section_no = None  # a new skill restarts section numbering
        if marks["section_number"]:
            section_no = marks["section_number"]

        if marks["is_answer_key"] or marks["is_transcript"] or not skill or section_no is None:
            continue

        key = (test_no or 1, skill, section_no)
        current = sections[-1] if sections else None
        if current and (current["test_number"], current["skill"], current["section_number"]) == key:
            current["last_page"] = num
            if marks["first_question"] and not current["first_question"]:
                current["first_question"] = marks["first_question"]
            if marks["last_question"]:
                current["last_question"] = marks["last_question"]
            continue

        sections.append({
            "test_number": key[0], "skill": skill, "section_number": section_no,
            "first_page": num, "last_page": num,
            "first_question": marks["first_question"],
            "last_question": marks["last_question"],
            "title": _section_title(skill, section_no),
        })

    tests = sorted({s["test_number"] for s in sections})
    return {
        "tests": tests,
        "sections": sections,
        "answer_key_pages": answer_key_pages,
        "transcript_pages": transcript_pages,
    }


def _section_title(skill: str, number: int) -> str:
    return {
        "LISTENING": f"Section {number}",
        "READING": f"Passage {number}",
        "WRITING": f"Task {number}",
        "SPEAKING": f"Part {number}",
    }[skill]


def summarise(outlined: dict) -> dict:
    """Counts for the import preview screen."""
    by_skill: dict[str, int] = {}
    questions = 0
    for s in outlined["sections"]:
        by_skill[s["skill"]] = by_skill.get(s["skill"], 0) + 1
        if s["first_question"] and s["last_question"]:
            questions += s["last_question"] - s["first_question"] + 1
    return {
        "tests": len(outlined["tests"]),
        "sections_by_skill": by_skill,
        "questions_declared": questions,
        "answer_key_pages": len(outlined["answer_key_pages"]),
        "transcript_pages": len(outlined["transcript_pages"]),
    }


# --- answer keys -------------------------------------------------------------

# A question number: digits followed by whitespace, not preceded by a digit or a
# dot - so the "30" in an answer like "09.30" is never mistaken for a number.
_RE_KEY_ITEM = re.compile(r"(?<![\w.])(\d{1,3})[.):]?\s+")


def parse_answer_key(text: str) -> dict[int, str]:
    """Pull `1 TRUE  2 09.30  3 chemistry ...` pairs out of an answer-key page.

    Deliberately conservative: at most four words, which is what IELTS keys
    contain. Anything longer is prose that happened to start with a number.
    Imported answers are stored with source=DOCUMENT and stay editable, because
    an OCR'd key is not evidence of correctness.
    """
    out: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        items = list(_RE_KEY_ITEM.finditer(line))
        # An answer line starts with its first question number. This drops
        # headings like "Test 1 Listening", which would otherwise be read as
        # "question 1 = Listening".
        if not items or items[0].start() != 0:
            continue
        for i, m in enumerate(items):
            number = int(m.group(1))
            end = items[i + 1].start() if i + 1 < len(items) else len(line)
            answer = line[m.end():end].strip(" .;:,")
            if not answer or not (1 <= number <= 200) or number in out:
                continue
            if len(answer.split()) > 4 or len(answer) > 40:
                continue
            out[number] = answer
    return out


def word_limit_in(text: str) -> str:
    m = _RE_WORD_LIMIT.search(text or "")
    return m.group(0).upper() if m else ""


# --- AI extraction -----------------------------------------------------------

class ParsedQuestion(BaseModel):
    question_number: int
    question_type: str = "SHORT_ANSWER"
    question_text: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str = ""
    word_limit: str = ""

    _coerce_lists = field_validator("options", mode="before")(ai._as_list)
    _coerce_strs = field_validator(
        "question_type", "question_text", "answer", "word_limit", mode="before")(ai._as_str)

    @field_validator("question_type", mode="after")
    @classmethod
    def known_type(cls, v: str) -> str:
        v = v.strip().upper().replace(" ", "_").replace("-", "_").replace("/", "_")
        aliases = {
            "TRUE_FALSE_NOTGIVEN": "TRUE_FALSE_NOT_GIVEN", "TFNG": "TRUE_FALSE_NOT_GIVEN",
            "YES_NO_NOTGIVEN": "YES_NO_NOT_GIVEN", "YNNG": "YES_NO_NOT_GIVEN",
            "MCQ": "MULTIPLE_CHOICE", "GAP_FILL": "SENTENCE_COMPLETION",
            "DIAGRAM_LABELLING": "DIAGRAM_LABELING", "MAP_LABELLING": "MAP_LABELING",
        }
        v = aliases.get(v, v)
        return v if v in QUESTION_TYPES else "SHORT_ANSWER"


class ParsedGroup(BaseModel):
    question_type: str = "SHORT_ANSWER"
    instruction: str = ""
    body: str = ""
    options: list[str] = Field(default_factory=list)
    word_limit: str = ""
    questions: list[ParsedQuestion] = Field(default_factory=list)

    _coerce_lists = field_validator("options", mode="before")(ai._as_list)
    _coerce_strs = field_validator(
        "question_type", "instruction", "body", "word_limit", mode="before")(ai._as_str)
    _known_type = field_validator("question_type", mode="after")(ParsedQuestion.known_type.__func__)


class ParsedSection(BaseModel):
    title: str = ""
    instructions: str = ""
    body: str = ""           # reading passage / writing prompt / speaking cue card
    transcript: str = ""
    groups: list[ParsedGroup] = Field(default_factory=list)
    confidence: float = 0.5

    _coerce_strs = field_validator("title", "instructions", "body", "transcript",
                                   mode="before")(ai._as_str)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp(cls, v):
        try:
            return min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            return 0.5


PARSER_SYSTEM = """You are an IELTS test-material parser. You are given the raw \
text of consecutive pages from one section of an IELTS practice book, already \
extracted from a PDF (so it may contain OCR noise, broken line breaks and page \
numbers).

Return the section as strict JSON. Rules:
- Copy text from the input. Never invent, complete, translate or correct questions.
- If something is unreadable, leave that field empty rather than guessing.
- "body" is the reading passage, writing prompt or speaking cue card, if present.
- Group questions the way the paper groups them: one group per shared instruction.
- Use these question_type values exactly: {types}.
- For matching/heading groups, put the shared option bank in the group's "options".
- Only fill "answer" if the answer is printed on these pages. Otherwise leave it empty.
- "confidence" is your own 0-1 estimate that this parse reflects the page.

Shape:
{{"title": "", "instructions": "", "body": "", "transcript": "", "confidence": 0.9,
  "groups": [{{"question_type": "MULTIPLE_CHOICE", "instruction": "", "body": "",
               "options": [], "word_limit": "",
               "questions": [{{"question_number": 1, "question_type": "MULTIPLE_CHOICE",
                              "question_text": "", "options": ["A ...", "B ..."],
                              "answer": "", "word_limit": ""}}]}}]}}
"""


def extract_section(section: dict, page_texts: list[str]) -> ParsedSection:
    """One AI call for one detected section. Raises ai.AIError on failure."""
    header = (f"IELTS {section['skill'].title()} - {section.get('title', '')} "
              f"(test {section['test_number']}, pages "
              f"{section['first_page']}-{section['last_page']})")
    body = "\n\n".join(page_texts)[:24_000]  # a section is a handful of pages; cap runaway input
    return ai._json_call(
        PARSER_SYSTEM.format(types=", ".join(sorted(QUESTION_TYPES))),
        f"{header}\n\n{body}",
        ParsedSection,
        f"IELTS section parsing (test {section['test_number']} {section['skill']} "
        f"{section['section_number']})",
        temperature=0,
    )


def _demo():
    # --- page classification
    p = classify_page("TEST 1\nLISTENING\nSECTION 1  Questions 1-10\nComplete the form.")
    assert p["test_number"] == 1 and p["skill"] == "LISTENING" and p["section_number"] == 1
    assert (p["first_question"], p["last_question"]) == (1, 10)

    p = classify_page("READING PASSAGE 2\nYou should spend about 20 minutes on Questions 14-26.")
    assert p["skill"] == "READING" and p["section_number"] == 2
    assert (p["first_question"], p["last_question"]) == (14, 26)

    # En-dash ranges are as common as hyphens in real books.
    assert classify_page("Questions 27–40")["last_question"] == 40
    assert classify_page("WRITING TASK 1")["section_number"] == 1
    assert classify_page("SPEAKING PART 2")["skill"] == "SPEAKING"
    assert classify_page("ANSWER KEY")["is_answer_key"]
    assert classify_page("AUDIOSCRIPT")["is_transcript"]
    assert classify_page("just some prose about lakes")["skill"] is None

    # --- outline over a small synthetic book
    pages = [
        {"page_number": 1, "text": "TEST 1\nLISTENING\nSECTION 1  Questions 1-10"},
        {"page_number": 2, "text": "continued form completion, no headings here"},
        {"page_number": 3, "text": "SECTION 2  Questions 11-20"},
        {"page_number": 4, "text": "READING PASSAGE 1\nQuestions 1-13"},
        {"page_number": 5, "text": "READING PASSAGE 2\nQuestions 14-26"},
        {"page_number": 6, "text": "WRITING TASK 1"},
        {"page_number": 7, "text": "WRITING TASK 2"},
        {"page_number": 8, "text": "SPEAKING PART 1"},
        {"page_number": 9, "text": "TEST 2\nLISTENING\nSECTION 1  Questions 1-10"},
        {"page_number": 10, "text": "AUDIOSCRIPT\nTest 1 Section 1"},
        {"page_number": 11, "text": "ANSWER KEY\nTest 1 Listening\n1 library  2 09.30  3 TRUE"},
    ]
    out = outline(pages)
    assert out["tests"] == [1, 2], out["tests"]
    assert out["answer_key_pages"] == [11] and out["transcript_pages"] == [10]

    first = out["sections"][0]
    assert first["skill"] == "LISTENING" and first["section_number"] == 1
    assert (first["first_page"], first["last_page"]) == (1, 2), "unmarked pages join the section above"
    assert (first["first_question"], first["last_question"]) == (1, 10)

    keys = [(s["test_number"], s["skill"], s["section_number"]) for s in out["sections"]]
    assert keys == [
        (1, "LISTENING", 1), (1, "LISTENING", 2), (1, "READING", 1), (1, "READING", 2),
        (1, "WRITING", 1), (1, "WRITING", 2), (1, "SPEAKING", 1), (2, "LISTENING", 1),
    ], keys
    # Answer-key and transcript pages never become practice sections.
    assert all(s["first_page"] not in (10, 11) for s in out["sections"])

    s = summarise(out)
    assert s["tests"] == 2 and s["sections_by_skill"]["READING"] == 2
    assert s["questions_declared"] == 10 + 10 + 13 + 13 + 10  # only ranges the book stated
    assert outline([])["sections"] == [] and summarise(outline([]))["tests"] == 0

    # --- answer keys
    key = parse_answer_key("1 library   2 09.30   3 TRUE\n4 NOT GIVEN  5 chemistry teacher")
    assert key == {1: "library", 2: "09.30", 3: "TRUE", 4: "NOT GIVEN", 5: "chemistry teacher"}, key
    assert parse_answer_key("11. B 12. C 13. A") == {11: "B", 12: "C", 13: "A"}
    # Prose is not an answer, and a repeated number keeps the first reading.
    assert parse_answer_key("1 The examiner will then ask a number of further questions") == {}
    assert parse_answer_key("7 apple\n7 banana") == {7: "apple"}
    # A heading is not an answer line: "Test 1 Listening" must not mean q1 = Listening.
    assert parse_answer_key("ANSWER KEY\nTest 1 Listening\n1 Victoria Hall  2 09.30") == \
        {1: "Victoria Hall", 2: "09.30"}

    assert word_limit_in("Write NO MORE THAN TWO WORDS AND/OR A NUMBER.") == \
        "NO MORE THAN TWO WORDS AND/OR A NUMBER"
    assert word_limit_in("no limit mentioned") == ""

    # --- schema coercion: model output is never trusted as-is
    q = ParsedQuestion(question_number="3", question_type="tfng", options="A only")
    assert q.question_type == "TRUE_FALSE_NOT_GIVEN" and q.options == ["A only"]
    assert ParsedQuestion(question_number=1, question_type="martian").question_type == "SHORT_ANSWER"
    assert ParsedSection(confidence="nonsense").confidence == 0.5
    assert ParsedSection(confidence=5).confidence == 1.0
    g = ParsedGroup(question_type="matching headings")
    assert g.question_type == "MATCHING_HEADINGS"

    print("ielts_parser self-check OK")


if __name__ == "__main__":
    _demo()
