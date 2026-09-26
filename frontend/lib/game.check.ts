// Self-check for the game rules. Run: node lib/game.check.ts
import assert from "node:assert/strict";
import { buildSession, checkTyped, pickWords, xpWithCombo, type Round } from "./game.ts";
import type { Vocab } from "./types.ts";

const TOPICS = ["Environment", "Health", "Work", "Education"];
const vocab = (id: number, word: string, state: Vocab["srs_state"] = "REVIEW"): Vocab => ({
  id, word, translation: `nghĩa ${id}`, definition: `definition of ${word}`, part_of_speech: "noun",
  pronunciation: "", phonetic: "", examples: [`People often talk about the ${word} in this city today.`],
  synonyms: [`syn${id}`], antonyms: [], collocations: [`make a ${word}`], word_family: [],
  ielts_level: "B2", topic: TOPICS[id % 4], memory_tip: "", notes: "", srs_state: state, ease: 2.5,
  interval_days: 0, repetitions: 0, lapses: 0, next_review_at: "", last_reviewed_at: null, starred: 0,
  created_at: "", updated_at: "", memory_strength: 50,
});

assert.equal(checkTyped("complaint", "complaint"), "exact");
assert.equal(checkTyped(" Complaint ", "complaint"), "exact");
assert.equal(checkTyped("complaimt", "complaint"), "typo");
assert.equal(checkTyped("cat", "car"), "wrong"); // short words must be exact
assert.equal(checkTyped("", "car"), "wrong");
assert.equal(xpWithCombo(25, 1), 25);
assert.equal(xpWithCombo(25, 5), 35);
assert.equal(xpWithCombo(25, 99), 50);

const queue = [1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => vocab(i, `word${i}`, i <= 2 ? "NEW" : "REVIEW"));
const pool = [10, 11, 12, 13, 14].map((i) => vocab(i, `other${i}`));
const words = pickWords(queue);
assert.ok(words.length >= 5 && words.length <= 8);

for (let run = 0; run < 200; run++) {
  const rounds: Round[] = buildSession(words, pool);
  assert.ok(rounds.length <= 15, `too long: ${rounds.length}`);
  assert.equal(rounds[rounds.length - 1].kind, "boss");
  const boss = rounds[rounds.length - 1];
  assert.ok(boss.kind === "boss" && boss.questions.length === 5);
  // Every new word is introduced before any single-word question about it.
  for (const w of words.filter((w) => w.srs_state === "NEW")) {
    const learnAt = rounds.findIndex((r) => r.kind === "learn" && r.vocab.id === w.id);
    const askedAt = rounds.findIndex((r) => (r.kind === "choice" || r.kind === "type" || r.kind === "sentence") && r.vocab.id === w.id);
    assert.ok(learnAt >= 0 && learnAt < askedAt, `learn ${learnAt} vs ask ${askedAt}`);
  }
  // Every word gets at least one single-word question outside the boss.
  for (const w of words) {
    assert.ok(rounds.some((r) => (r.kind === "choice" || r.kind === "type" || r.kind === "sentence") && r.vocab.id === w.id));
  }
  // Choice options always contain the answer exactly once, no duplicates.
  for (const r of rounds.flatMap((r) => (r.kind === "battle" || r.kind === "boss" ? r.questions : [r]))) {
    if (r.kind !== "choice") continue;
    assert.equal(r.options.length, 4);
    assert.equal(new Set(r.options).size, 4);
    assert.equal(r.options.filter((o) => o === r.answer).length, 1);
  }
}
console.log("game self-check OK");
