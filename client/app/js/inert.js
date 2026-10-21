/**
 * The `inert` sweep for the board-side surfaces.
 *
 * A playing cutscene blocks the board and the board-side panels but not the
 * activity layer, which renders above it. This module is the single writer so
 * the cutscene manager can ask for a re-sweep instead of fighting the render
 * loop: the activity layer watches for `inert` mutations and re-walks the tree
 * when it sees one, so writing an unchanged value on every render made each
 * socket message cost a full ancestor and sibling pass.
 */

/** Toggle a class only when it actually changes. */
export function toggleClass(node, name, value) {
  if (!node || node.classList.contains(name) === value) return;
  node.classList.toggle(name, value);
}

function setInert(node, value) {
  if (!node || node.inert === value) return;
  node.inert = value;
}

export function createInertSweep({ root, panelLayer, activityLayer, settings, bottomStack }) {
  return function applyInert(state) {
    const cutscene = root.classList.contains("cutscene-playing");
    const viewOpen = Boolean(state.views.main && state.views.main !== "edit-room");
    const onboarding = !state.loggedIn || !state.user?.initialStickerComplete;
    setInert(root.querySelector("#board-canvas"), !state.loggedIn || viewOpen || cutscene);
    setInert(panelLayer, cutscene);
    setInert(activityLayer, false);
    setInert(bottomStack, onboarding);
    setInert(settings, onboarding);
  };
}
