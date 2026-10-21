/**
 * Track the Shift modifier for the room editor's top handle.
 *
 * Shift changes what the top handle does (scale vs. vertical movement), so the
 * board only needs to know whether it is held, not which key event carried it.
 * The controller owns its listeners and resets on window blur so a modifier
 * released while the tab is hidden cannot stick.
 */

/** Create a Shift tracker that calls `onChange(active)` whenever the modifier flips. */
export function createEditModifier(onChange) {
  let vertical = false;

  const update = active => {
    const next = Boolean(active);
    if (vertical === next) return;
    vertical = next;
    onChange(next);
  };
  const onKey = event => {
    if (event.key === "Shift") update(event.shiftKey);
  };
  const onBlur = () => update(false);

  document.addEventListener("keydown", onKey);
  document.addEventListener("keyup", onKey);
  window.addEventListener("blur", onBlur);

  return {
    dispose() {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("keyup", onKey);
      window.removeEventListener("blur", onBlur);
    },
  };
}
