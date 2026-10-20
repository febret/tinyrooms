const PODIUM_ORDERS = {
  0: [],
  1: [0],
  2: [1, 0],
  3: [1, 0, 2],
  4: [2, 1, 3, 0],
  5: [2, 1, 3, 0, 4],
};

/**
 * Return CSS `order` values that place rank 1 in the center and later ranks
 * alternately toward the left and right sides, like a podium.
 */
export function podiumOrder(count) {
  const total = Math.max(0, Math.trunc(Number(count) || 0));
  const fixed = PODIUM_ORDERS[total];
  if (fixed) return [...fixed];
  return Array.from({ length: total }, (_, index) => index);
}
