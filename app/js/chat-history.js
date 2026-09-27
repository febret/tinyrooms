/**
 * In-memory chat and command history for the chat bar.
 *
 * Entries are captured as typed, kept oldest-first, and bounded so the bar can
 * recall the most recent submissions. Nothing is persisted: the client keeps
 * all chat state in memory by design. `filterHistory` is a pure helper so the
 * fuzzy matching can be unit tested without a DOM.
 */

export const MAX_HISTORY = 100;

/** Score a fuzzy subsequence match, or null when *query* is not a subsequence. */
export function fuzzyScore(query, text) {
  const needle = String(query ?? "").toLowerCase();
  const haystack = String(text ?? "").toLowerCase();
  if (!needle) return 0;
  let score = 0;
  let cursor = 0;
  let previous = -2;
  for (const character of needle) {
    const found = haystack.indexOf(character, cursor);
    if (found < 0) return null;
    score += found === previous + 1 ? 4 : 1;
    if (found === 0) score += 2;
    previous = found;
    cursor = found + 1;
  }
  return score - haystack.length / 1000;
}

/** Return matching history entries, newest first. */
export function filterHistory(entries, query, limit = MAX_HISTORY) {
  const list = Array.isArray(entries) ? entries : [];
  const needle = String(query ?? "").trim();
  if (!needle) return list.slice(-limit).reverse();
  const matches = [];
  list.forEach((text, index) => {
    const score = fuzzyScore(needle, text);
    if (score !== null) matches.push({ text, index, score });
  });
  matches.sort((a, b) => b.score - a.score || b.index - a.index);
  return matches.slice(0, limit).map(match => match.text);
}

/** Create a bounded, in-memory history store. */
export function createChatHistory({ limit = MAX_HISTORY } = {}) {
  let entries = [];
  return {
    record(text) {
      const value = String(text ?? "").trim();
      if (!value || entries.at(-1) === value) return;
      entries.push(value);
      if (entries.length > limit) entries = entries.slice(-limit);
    },
    entries() {
      return [...entries];
    },
    filter(query, max = limit) {
      return filterHistory(entries, query, max);
    },
    clear() {
      entries = [];
    },
  };
}
