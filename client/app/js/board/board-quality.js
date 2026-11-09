const COARSE_POINTER_QUERY = "(pointer: coarse)";

/**
 * Choose the board's GPU quality profile.
 *
 * Phones and tablets get a smaller framebuffer cap, a cheaper shadow filter,
 * and a 1024px shadow map. Desktop keeps the authored 2x/2048px look. The
 * profile is resolved once per board; `matchMedia` is injectable for tests.
 */
export function resolveBoardQuality(matchMedia = typeof window !== "undefined" ? window.matchMedia?.bind(window) : null) {
  let coarse = false;
  try {
    coarse = Boolean(matchMedia?.(COARSE_POINTER_QUERY)?.matches);
  } catch {
    coarse = false;
  }
  return {
    coarse,
    maxPixelRatio: coarse ? 1.5 : 2,
    shadowMapSize: coarse ? 1024 : 2048,
    softShadows: !coarse,
  };
}
