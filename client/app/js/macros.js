export const MACRO_PAGES = 5;
export const MACROS_PER_PAGE = 6;
export const MACRO_COUNT = MACRO_PAGES * MACROS_PER_PAGE;
export const MACRO_MAX_LENGTH = 80;

/** Pad or trim a profile macro grid into the fixed five-page display shape. */
export function normalizeMacros(raw) {
  const values = Array.isArray(raw) ? raw : [];
  return Array.from({ length: MACRO_COUNT }, (_, index) => {
    const value = values[index];
    return typeof value === "string" ? value.slice(0, MACRO_MAX_LENGTH) : "";
  });
}
