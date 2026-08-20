"""AI vocabulary extraction. One provider (OpenAI) -> no provider-abstraction
interface; add one if/when a second provider is actually wired in."""
import json
import os

from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator


def _as_list(v):
    """LLMs sometimes send a bare string where the schema wants a list."""
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    return v


def _as_str(v):
    """...and sometimes a number/bool where the schema wants a string."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    return v if isinstance(v, str) else str(v)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Writing evaluation is the one task where model quality really shows. Set
# OPENAI_GRADING_MODEL=gpt-4o (or better) to upgrade just that call.
GRADING_MODEL = os.environ.get("OPENAI_GRADING_MODEL", MODEL)

SYSTEM_PROMPT = """You are an expert English teacher and IELTS instructor helping a \
Vietnamese learner build vocabulary.

You will receive raw input from the learner: it may be a single English word, a list \
of words/phrases (one per line), or a full sentence or paragraph.

Your job:
- If it's a word or list of words/phrases, treat every item as vocabulary to teach.
- If it's a sentence or paragraph, do NOT translate it whole. Instead detect the \
useful vocabulary within it (words, phrasal verbs, and collocations that are B1 level \
or above, or IELTS-relevant) and return those as separate items. Skip trivial words \
(the, is, a, and, ...).
- For every item, provide an accurate Vietnamese translation and the rest of the \
fields below. Keep definitions in English, translations in Vietnamese.
- Do not invent words that are not present or implied in the input.

Respond ONLY with JSON matching this shape:
{
  "items": [
    {
      "word": "abundant",
      "translation": "dồi dào, phong phú",
      "part_of_speech": "adjective",
      "pronunciation": "/əˈbʌndənt/",
      "phonetic": "uh-BUHN-duhnt",
      "definition": "existing or available in large quantities",
      "examples": ["The region has abundant natural resources."],
      "synonyms": ["plentiful", "ample", "copious"],
      "antonyms": ["scarce", "limited"],
      "collocations": ["abundant resources", "abundant supply"],
      "ielts_level": "B2-C1",
      "topic": "Environment",
      "memory_tip": "short mnemonic or association to remember the word"
    }
  ]
}
"""


class VocabItem(BaseModel):
    word: str
    translation: str = ""
    part_of_speech: str = ""
    pronunciation: str = ""
    phonetic: str = ""
    definition: str = ""
    examples: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    antonyms: list[str] = Field(default_factory=list)
    collocations: list[str] = Field(default_factory=list)
    ielts_level: str = ""
    topic: str = ""
    memory_tip: str = ""

    _coerce_lists = field_validator(
        "examples", "synonyms", "antonyms", "collocations", mode="before"
    )(_as_list)
    _coerce_strs = field_validator(
        "word", "translation", "part_of_speech", "pronunciation", "phonetic",
        "definition", "ielts_level", "topic", "memory_tip", mode="before"
    )(_as_str)


class VocabResponse(BaseModel):
    items: list[VocabItem] = Field(default_factory=list)


class AIError(Exception):
    pass


def _json_call(system: str, user: str, schema: type[BaseModel], what: str,
               temperature: float = 0.3, model: str | None = None):
    """One JSON-mode call validated against a Pydantic schema, with one retry."""
    last_error = None
    for attempt in range(2):
        try:
            client = OpenAI()
            resp = client.chat.completions.create(
                model=model or MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
            )
            raw = json.loads(resp.choices[0].message.content)
            return schema.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = e
            continue
        except Exception as e:  # openai SDK errors (network, auth, rate limit, ...)
            last_error = e
            continue
    raise AIError(f"{what} failed: {last_error}")


def extract_vocabulary(text: str) -> list[VocabItem]:
    text = text.strip()
    if not text:
        return []
    return _json_call(SYSTEM_PROMPT, text, VocabResponse, "AI vocabulary extraction").items


TUTOR_SYSTEM_PROMPT = """You are a friendly, expert English teacher and IELTS tutor \
helping a Vietnamese learner. Answer questions about English vocabulary, grammar, \
and usage clearly and concisely. Give examples when useful. Prefer Vietnamese \
explanations for tricky nuances, but keep example sentences in English. Keep replies \
focused and not too long unless the learner asks for depth."""


COACH_CONTEXT_PROMPT = """

You are also this learner's IELTS coach and you know their record. Use it: answer \
"what should I study today?" with something specific to the numbers below, name the \
skill that is holding their overall band down, and say what to do about it. Never \
invent progress they have not made, and if the record is empty, say so and suggest \
how to generate some.

The learner's record right now:
{context}"""


def tutor_reply(history: list[dict], weak_words: list[str], coach_context: str = "") -> str:
    """history: list of {"role": "user"|"assistant", "content": str}, oldest first."""
    if not history:
        return ""
    context = ""
    if weak_words:
        context = "\n\nThe learner has recently struggled with these words: " + ", ".join(weak_words) + \
            ". If relevant, weave in practice with them."
    if coach_context:
        context += COACH_CONTEXT_PROMPT.format(context=coach_context)
    messages = [{"role": "system", "content": TUTOR_SYSTEM_PROMPT + context}] + history[-10:]

    last_error = None
    for attempt in range(2):
        try:
            client = OpenAI()
            resp = client.chat.completions.create(model=MODEL, messages=messages, temperature=0.5)
            return resp.choices[0].message.content
        except Exception as e:
            last_error = e
            continue
    raise AIError(f"AI tutor failed: {last_error}")


# ---------- daily IELTS practice ----------

class PracticeQuestion(BaseModel):
    type: str = "multiple_choice"  # multiple_choice | true_false_notgiven | short_answer
    question: str
    options: list[str] = Field(default_factory=list)
    answer: str
    explanation: str = ""
    # Words this question hinges on, looked up in the task-level `vocabulary` list.
    # Kept as bare strings so the model isn't repeating 13-field objects per question,
    # which made it truncate the passage and drop questions.
    vocab_words: list[str] = Field(default_factory=list)

    _coerce_options = field_validator("options", "vocab_words", mode="before")(_as_list)
    _coerce_strs = field_validator("type", "question", "answer", "explanation", mode="before")(_as_str)


class ReadingTask(BaseModel):
    title: str
    topic: str = ""
    passage: str
    # A 1-question "test" is useless; reject it so _json_call retries instead of storing it.
    questions: list[PracticeQuestion] = Field(min_length=5)
    vocabulary: list[VocabItem] = Field(default_factory=list)


class ListeningTask(BaseModel):
    title: str
    topic: str = ""
    transcript: str
    questions: list[PracticeQuestion] = Field(min_length=4)
    vocabulary: list[VocabItem] = Field(default_factory=list)


class WritingTask(BaseModel):
    task_type: str = "Task 2"
    title: str = ""
    prompt: str
    guidance: str = ""
    min_words: int = 250


_QUESTION_SHAPE = """Each question object must be:
{
  "type": "multiple_choice" | "true_false_notgiven" | "short_answer",
  "question": "the question text",
  "options": ["A option", "B option", "C option", "D option"],
  "answer": "the exact correct answer - for multiple_choice it must match one option \
verbatim; for true_false_notgiven it must be exactly TRUE, FALSE or NOT GIVEN; for \
short_answer keep it to 1-3 words taken from the text",
  "explanation": "why that answer is right, and why a learner might get it wrong - \
reference the specific part of the text",
  "vocab_words": ["1-2 words, JUST THE WORDS as plain strings, taken from the part of \
the text this question is about. REQUIRED for every question - the learner studies \
these when they get the question wrong. Every word here must also appear in the \
top-level vocabulary list."]
}

For "true_false_notgiven" and "short_answer", "options" must be an empty list.

The top-level "vocabulary" list holds the full entry for every word referenced by any \
question, plus a few more of the most useful words in the text. Each entry:
{
  "word": "mitigate",
  "translation": "Vietnamese meaning",
  "part_of_speech": "verb",
  "pronunciation": "/ˈmɪtɪɡeɪt/",
  "phonetic": "MIT-i-gayt",
  "definition": "English definition",
  "examples": ["one example sentence"],
  "synonyms": ["reduce"],
  "antonyms": ["intensify"],
  "collocations": ["mitigate the impact"],
  "ielts_level": "B2-C1",
  "topic": "Environment",
  "memory_tip": "short memory hook"
}"""

READING_PROMPT = f"""You are an IELTS Academic exam writer creating daily reading \
practice for a Vietnamese learner.

Write ONE original IELTS Academic Reading passage of 500-700 words on an academic topic \
(environment, technology, education, health, society, science, work, urbanisation, \
globalisation, media...). Use the register and difficulty of a real IELTS Academic \
passage. Do not copy any existing text - write it yourself.

Then write exactly 8 questions about it. Mix the types: use some multiple_choice, some \
true_false_notgiven, and some short_answer. Every answer must be verifiable from the \
passage alone.

{_QUESTION_SHAPE}

Then fill the top-level "vocabulary" list: a full entry for every word any question \
referenced in its vocab_words, plus a few more of the most useful IELTS words in the \
passage - 10-14 entries in total.

Write all 8 questions. Do not stop early or shorten the passage to save space.

Respond ONLY with JSON:
{{"title": "...", "topic": "...", "passage": "the full passage text", \
"questions": [...], "vocabulary": [...]}}"""

LISTENING_PROMPT = f"""You are an IELTS exam writer creating daily listening practice \
for a Vietnamese learner.

Write ONE original IELTS-style listening script of 300-450 words. It will be read aloud \
by a speech synthesiser, so write it as natural spoken English: either a monologue \
(a talk, announcement, or lecture extract) or a two-person conversation with speaker \
labels on their own lines like "TUTOR: ..." and "STUDENT: ...". Include the kind of \
concrete detail IELTS listening tests on - names, numbers, dates, times, places.

Then write exactly 6 questions about it. Mix multiple_choice and short_answer types. \
Every answer must be verifiable from the script alone.

{_QUESTION_SHAPE}

Then fill the top-level "vocabulary" list: a full entry for every word any question \
referenced in its vocab_words, plus a few more of the most useful words in the script - \
8-12 entries in total.

Write all 6 questions. Do not stop early.

Respond ONLY with JSON:
{{"title": "...", "topic": "...", "transcript": "the full script", \
"questions": [...], "vocabulary": [...]}}"""

WRITING_PROMPT = """You are an IELTS examiner setting a daily Writing Task 2 question \
for a Vietnamese learner.

Write ONE original IELTS Academic Writing Task 2 question. Vary the essay type across \
these: opinion (agree/disagree), discussion (discuss both views), advantages/ \
disadvantages, problem/solution, two-part question. Use a common IELTS topic area.

Respond ONLY with JSON:
{"task_type": "Task 2", "title": "short topic label", "prompt": "the full question \
exactly as it would appear on the exam paper, including the instruction line", \
"guidance": "2-3 sentences in Vietnamese telling the learner how to approach this \
specific question - what structure to use and what the examiner is looking for", \
"min_words": 250}"""


def generate_reading() -> ReadingTask:
    return _json_call(READING_PROMPT, "Generate today's reading practice.",
                      ReadingTask, "Reading generation", temperature=0.9)


def generate_listening() -> ListeningTask:
    return _json_call(LISTENING_PROMPT, "Generate today's listening practice.",
                      ListeningTask, "Listening generation", temperature=0.9)


def generate_writing() -> WritingTask:
    return _json_call(WRITING_PROMPT, "Generate today's writing task.",
                      WritingTask, "Writing task generation", temperature=1.0)


class Correction(BaseModel):
    original: str
    improved: str
    why: str = ""
    # Classified so repeated mistakes can be counted and practised by topic
    # rather than re-read one essay at a time.
    error_type: str = ""      # e.g. "subject-verb agreement"
    grammar_topic: str = ""   # e.g. "Subject-Verb Agreement"

    _coerce_strs = field_validator("original", "improved", "why", "error_type",
                                   "grammar_topic", mode="before")(_as_str)


class WritingFeedback(BaseModel):
    band_overall: float
    task_response: float
    coherence_cohesion: float
    lexical_resource: float
    grammatical_range: float
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    suggested_vocabulary: list[VocabItem] = Field(default_factory=list)


GRADING_PROMPT = """You are an experienced IELTS examiner marking a Writing Task 2 essay \
written by a Vietnamese learner. Mark it exactly as the official IELTS band descriptors \
require - be honest and accurate, not generous. Most real candidates score between 5.0 \
and 7.0; do not inflate the band.

Give a band (in 0.5 steps, 0-9) for each of the four criteria, and an overall band which \
is the average of the four rounded to the nearest 0.5.

1. Task Response - does it fully answer the question, with a clear position and \
developed, relevant ideas?
2. Coherence and Cohesion - logical progression, paragraphing, linking devices.
3. Lexical Resource - range, precision, collocation, and appropriacy of vocabulary.
4. Grammatical Range and Accuracy - variety of structures and error density.

IMPORTANT - you are teaching, not rewriting. Do NOT rewrite the whole essay. Instead \
pick 3-6 specific sentences the learner actually wrote that could be improved, and for \
each one show the original, an improved version, and explain WHY it is better (the \
grammar rule or the collocation involved). The learner must understand the reason so \
they can fix it themselves next time.

For every correction, also name the error_type and the grammar_topic it belongs to \
(one of: Tenses, Articles, Prepositions, Subject-Verb Agreement, Conditionals, \
Relative Clauses, Passive Voice, Modal Verbs, Complex Sentences, Conjunctions, \
Gerunds & Infinitives, Noun Clauses, Adverbial Clauses, Comparatives, Quantifiers, \
Word Choice, Word Form, Punctuation, Spelling), in English, so repeated mistakes can \
be counted and practised.

Also suggest 3-5 higher-band vocabulary items or collocations that would have fitted \
this specific essay topic, as full vocabulary objects so they can be saved for study.

If the essay is far too short, off-topic, or not a genuine attempt, say so plainly in \
the summary and mark it down accordingly.

Write "summary", "strengths", "weaknesses" and every "why" in Vietnamese so the learner \
fully understands, but keep all English words, sentences and examples in English.

Respond ONLY with JSON:
{"band_overall": 6.5, "task_response": 6.0, "coherence_cohesion": 7.0, \
"lexical_resource": 6.5, "grammatical_range": 6.0, "summary": "...", \
"strengths": ["..."], "weaknesses": ["..."], \
"corrections": [{"original": "sentence the learner wrote", "improved": "better \
version", "why": "explanation in Vietnamese", "error_type": "subject-verb agreement", \
"grammar_topic": "Subject-Verb Agreement"}], \
"suggested_vocabulary": [ full vocabulary objects with word, translation, \
part_of_speech, pronunciation, phonetic, definition, examples, synonyms, antonyms, \
collocations, ielts_level, topic, memory_tip ]}"""


def grade_writing(prompt: str, essay: str) -> WritingFeedback:
    user = f"ESSAY QUESTION:\n{prompt}\n\nCANDIDATE'S ESSAY ({len(essay.split())} words):\n{essay}"
    return _json_call(GRADING_PROMPT, user, WritingFeedback, "Writing evaluation",
                      temperature=0.2, model=GRADING_MODEL)


# ---------- speech to text ----------

STT_PROVIDER = os.environ.get("STT_PROVIDER", "openai")
STT_MODEL = os.environ.get("STT_MODEL", "whisper-1")


def transcribe_audio(path: str, filename: str = "audio.mp3") -> str:
    """Transcribe a listening recording.

    ponytail: one provider, chosen by STT_PROVIDER, because one is wired up.
    Adding Deepgram/Google means another branch here, not an interface layer.
    """
    if STT_PROVIDER != "openai":
        raise AIError(f"Unknown STT_PROVIDER: {STT_PROVIDER}")
    try:
        with open(path, "rb") as fh:
            resp = OpenAI().audio.transcriptions.create(model=STT_MODEL, file=(filename, fh))
    except Exception as e:
        raise AIError(f"Transcription failed: {e}")
    text = getattr(resp, "text", "") or ""
    if not text.strip():
        raise AIError("Transcription returned nothing - is the recording silent?")
    return text.strip()


LOOKUP_SYSTEM = """You are an English dictionary for a Vietnamese IELTS learner.

You are given one word or phrase and the sentence it appeared in. Explain that word \
AS USED IN THAT CONTEXT - if it has several meanings, pick the one the sentence shows.

Return exactly one item and fill in EVERY field. The Vietnamese translation and the \
IPA pronunciation are the two the learner needs most, so they must never be empty. \
Put the original sentence first in "examples".

Respond ONLY with JSON:
{"items": [{"word": "...", "translation": "Vietnamese meaning", \
"part_of_speech": "...", "pronunciation": "/IPA/", "phonetic": "plain-english-sounds", \
"definition": "short English definition", "examples": ["the original sentence", "..."], \
"synonyms": ["..."], "antonyms": ["..."], "collocations": ["..."], \
"ielts_level": "B2-C1", "topic": "...", "memory_tip": "..."}]}
"""


def lookup_word(word: str, context: str = "") -> VocabItem | None:
    """One word, explained in the context it was met in. Used by click-to-look-up
    in reading passages and transcripts."""
    word = (word or "").strip()
    if not word:
        return None
    user = f"Word: {word}"
    if context.strip():
        user += f"\nSentence: {context.strip()[:600]}"
    items = _json_call(LOOKUP_SYSTEM, user, VocabResponse, "AI word lookup").items
    return items[0] if items else None


PASSAGE_VOCAB_SYSTEM = """You are an IELTS vocabulary coach for a Vietnamese learner.

From the passage below, pick the words and phrases that are genuinely worth \
learning for IELTS: B2 level and above, academic or topic vocabulary, and useful \
collocations. Skip proper nouns and words a B1 learner already knows.

Rules:
- Only words that actually appear in the passage.
- At most {limit} items, most useful first.
- "examples" must start with the sentence from the passage that contains the word.

Respond ONLY with JSON: {{"items": [ ... vocabulary items ... ]}}
"""


def extract_passage_vocabulary(text: str, limit: int = 12) -> list[VocabItem]:
    """Useful IELTS vocabulary from a reading passage or transcript.

    Nothing is saved anywhere by this call - the learner chooses what to keep.
    """
    text = (text or "").strip()
    if not text:
        return []
    return _json_call(
        PASSAGE_VOCAB_SYSTEM.format(limit=limit), text[:8000], VocabResponse,
        "AI passage vocabulary extraction",
    ).items[:limit]


# ---------- speaking ----------

class SpeakingFeedback(BaseModel):
    band_overall: float
    fluency_coherence: float
    lexical_resource: float
    grammatical_range: float
    pronunciation: float
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    overused_words: list[str] = Field(default_factory=list)
    fillers: list[str] = Field(default_factory=list)
    suggested_vocabulary: list[VocabItem] = Field(default_factory=list)

    _coerce_lists = field_validator("strengths", "weaknesses", "overused_words", "fillers",
                                    mode="before")(_as_list)


SPEAKING_PROMPT = """You are an experienced IELTS speaking examiner. You are given the \
question the candidate was asked and a transcript of their spoken answer (produced by \
speech-to-text, so punctuation may be imperfect - do not mark them down for that).

Mark against the four official criteria, honestly, in 0.5 steps:
1. Fluency and Coherence - can they keep going, develop ideas, link them?
2. Lexical Resource - range and precision, including idiomatic and topic vocabulary.
3. Grammatical Range and Accuracy - variety of structures and error density.
4. Pronunciation - judge ONLY what the transcript can show (word choice, stress \
patterns visible as mis-transcriptions, repetition, false starts). Say in the summary \
that pronunciation cannot be fully judged from a transcript.

Then:
- List filler words and phrases they leaned on ("like", "you know", "um").
- List words they overused, where a stronger IELTS synonym exists.
- Pick 3-6 sentences they actually said that could be improved: original, improved, \
why, error_type and grammar_topic (Tenses, Articles, Prepositions, Subject-Verb \
Agreement, Conditionals, Relative Clauses, Passive Voice, Modal Verbs, Complex \
Sentences, Conjunctions, Gerunds & Infinitives, Noun Clauses, Adverbial Clauses, \
Comparatives, Quantifiers, Word Choice, Word Form).
- Suggest 3-5 higher-band vocabulary items that would have fitted this answer, as full \
vocabulary objects.

If the answer is far too short or off-topic, say so plainly and mark accordingly.

Write "summary", "strengths", "weaknesses" and every "why" in Vietnamese; keep all \
English words and example sentences in English.

Respond ONLY with JSON matching the described shape, with keys: band_overall, \
fluency_coherence, lexical_resource, grammatical_range, pronunciation, summary, \
strengths, weaknesses, corrections, overused_words, fillers, suggested_vocabulary."""


def grade_speaking(prompt: str, transcript: str) -> SpeakingFeedback:
    return _json_call(
        SPEAKING_PROMPT,
        f"Question:\n{prompt}\n\nCandidate's answer (transcribed):\n{transcript}",
        SpeakingFeedback, "AI speaking evaluation", temperature=0.2, model=GRADING_MODEL,
    )
