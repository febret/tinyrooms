export const SYMBOLS = ["circle", "triangle", "square", "diamond", "star", "key"];

export function hashSeed(seed) {
  let hash = 2166136261;
  for (const character of String(seed || "")) {
    hash ^= character.codePointAt(0) || 0;
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

export function generateSafecrack(seed, difficulty = 2) {
  const length = Math.min(6, Math.max(3, 2 + Math.floor(Number(difficulty) || 2)));
  let state = hashSeed(seed) || 1;
  const sequence = [];
  while (sequence.length < length) {
    state = (Math.imul(state, 1103515245) + 12345) >>> 0;
    const symbol = SYMBOLS[state % SYMBOLS.length];
    if (sequence[sequence.length - 1] !== symbol) sequence.push(symbol);
  }
  return { sequence, symbols: [...SYMBOLS] };
}

export function checkSafecrack(sequence, attempt) {
  const expected = Array.isArray(sequence) ? sequence : [];
  const given = Array.isArray(attempt) ? attempt : [];
  let placed = 0;
  for (let index = 0; index < expected.length; index += 1) {
    if (given[index] === expected[index]) placed += 1;
    else break;
  }
  return { ok: placed === expected.length && given.length === expected.length, placed };
}

export function previewMask(sequence, revealed) {
  return sequence.map((symbol, index) => (index < revealed ? symbol : "hidden"));
}
