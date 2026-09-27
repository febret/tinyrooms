import test from "node:test";
import assert from "node:assert/strict";

import { MAX_HISTORY, createChatHistory, filterHistory, fuzzyScore } from "../../app/js/chat-history.js";

test("fuzzyScore matches ordered subsequences only", () => {
  assert.notEqual(fuzzyScore("gp", ".grant bops"), null);
  assert.notEqual(fuzzyScore("gnb", ".grant bops"), null);
  assert.equal(fuzzyScore("xyz", ".grant bops"), null);
  assert.equal(fuzzyScore("", "anything"), 0);
});

test("fuzzyScore prefers contiguous and earlier matches", () => {
  const contiguous = fuzzyScore("grant", ".grant bops");
  const scattered = fuzzyScore("grant", ".go ran to granny");
  assert.ok(contiguous > scattered, `${contiguous} should beat ${scattered}`);
});

test("filterHistory with no query returns the newest entries first", () => {
  const entries = ["first", "second", "third"];
  assert.deepEqual(filterHistory(entries, ""), ["third", "second", "first"]);
  assert.deepEqual(filterHistory([], ""), []);
  assert.deepEqual(filterHistory(entries, "", 2), ["third", "second"]);
});

test("filterHistory fuzzy matches ordered subsequences", () => {
  const entries = [".grant bops 10", ".go @way:exit0"];
  assert.deepEqual(filterHistory(entries, "gbo"), [".grant bops 10"]);
  assert.deepEqual(filterHistory(entries, "gwe"), [".go @way:exit0"]);
  assert.deepEqual(filterHistory(entries, "zzz"), []);
});

test("createChatHistory bounds, dedupes, and ignores blanks", () => {
  const history = createChatHistory({ limit: 3 });
  history.record("hello");
  history.record("hello");
  history.record("  ");
  history.record(".look");
  history.record(".grant bops 10");
  history.record("last");
  assert.deepEqual(history.entries(), [".look", ".grant bops 10", "last"]);
  assert.equal(history.filter("").length, 3);
});

test("createChatHistory keeps only the most recent entries", () => {
  const history = createChatHistory({ limit: 2 });
  for (let index = 0; index < 150; index += 1) history.record(`message ${index}`);
  assert.equal(history.entries().length, 2);
  assert.deepEqual(history.entries(), ["message 148", "message 149"]);
  assert.deepEqual(history.filter("message 149"), ["message 149"]);
});

test("MAX_HISTORY bounds the default store", () => {
  const history = createChatHistory();
  for (let index = 0; index < MAX_HISTORY + 25; index += 1) history.record(`entry ${index}`);
  assert.equal(history.entries().length, MAX_HISTORY);
  assert.equal(history.entries().at(-1), `entry ${MAX_HISTORY + 24}`);
});
