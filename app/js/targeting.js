// Card targeting: preview a line from the played card to a chosen target and
// confirm it by selecting that same target a second time.
//
// Targeting state lives in `state.ui.targeting` (set when a card offers a
// "Use on…" action). This controller only draws the preview and turns clicks
// on props/peeps into `.use` commands; opening another view or Escape is
// handled by the store's reducers.

import { findInventoryCard } from "./state.js";

export function createTargetingController({ board, boardFrame, getState, store, sendCommand, onToast, onError }) {
  const layer = boardFrame?.querySelector("#target-line") || null;
  const svg = layer?.querySelector("svg") || null;
  const stroke = svg?.querySelector(".target-line-stroke") || null;
  const sourceDot = svg?.querySelector(".target-line-source") || null;
  const endDot = svg?.querySelector(".target-line-end") || null;
  let preview = null;
  let sourceStackId = "";
  let sourcePoint = null;
  let frame = 0;

  function eligibleKind(state) {
    const stack = findInventoryCard(state, state.ui.targeting?.stackId);
    return stack?.definition?.target || "";
  }

  function toFrame(point) {
    if (!point) return null;
    const bounds = boardFrame?.getBoundingClientRect();
    if (!bounds) return point;
    return { x: point.x - bounds.left, y: point.y - bounds.top };
  }

  function captureSource(stackId) {
    if (sourceStackId === stackId && sourcePoint) return;
    sourceStackId = stackId;
    const tile = document.querySelector(`#card-hand [data-stack-id="${CSS.escape(stackId)}"]`)
      || document.querySelector(`#panel-layer [data-stack-id="${CSS.escape(stackId)}"]`);
    if (tile) {
      const bounds = tile.getBoundingClientRect();
      sourcePoint = toFrame({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 });
      return;
    }
    const bounds = boardFrame?.getBoundingClientRect();
    sourcePoint = bounds ? { x: bounds.width / 2, y: bounds.height } : { x: 0, y: 0 };
  }

  function targetPoint(kind, id) {
    if (kind === "prop") {
      const prop = getState().room?.props?.find(entry => entry.id === id);
      const project = board.projectPositionToScreen;
      return prop && typeof project === "function" ? toFrame(project.call(board, prop.position)) : null;
    }
    if (kind === "peep") {
      const chip = document.querySelector(`#peeps-panel [data-peep-id="${CSS.escape(id)}"]`);
      if (!chip) return null;
      const bounds = chip.getBoundingClientRect();
      return toFrame({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 });
    }
    return null;
  }

  function draw() {
    if (!stroke || !sourcePoint) return;
    const show = Boolean(preview);
    layer.hidden = !show;
    if (!show) return;
    const end = targetPoint(preview.kind, preview.id);
    if (!end) return;
    stroke.setAttribute("x1", sourcePoint.x);
    stroke.setAttribute("y1", sourcePoint.y);
    stroke.setAttribute("x2", end.x);
    stroke.setAttribute("y2", end.y);
    for (const [dot, x, y] of [[sourceDot, sourcePoint.x, sourcePoint.y], [endDot, end.x, end.y]]) {
      dot?.setAttribute("cx", x);
      dot?.setAttribute("cy", y);
    }
  }

  function confirm() {
    const targeting = getState().ui.targeting;
    const target = preview;
    preview = null;
    if (!targeting || !target) return;
    store.dispatch({ type: "cancel-targeting" });
    void sendCommand(`.use @card:${targeting.stackId} @${target.kind}:${target.id}`).catch(onError);
  }

  function choose(kind, id) {
    if (preview && preview.kind === kind && preview.id === id) {
      confirm();
      return;
    }
    preview = { kind, id };
    draw();
  }

  /** Absorb a board/sidebar selection while targeting; true when handled. */
  function handle(selection) {
    const state = getState();
    if (!state.ui.targeting) return false;
    const kind = eligibleKind(state);
    if (kind === "prop" && selection.kind === "prop" && selection.id) {
      choose("prop", selection.id);
      return true;
    }
    if (kind === "peep" && selection.kind === "peep" && selection.id) {
      choose("peep", selection.id);
      return true;
    }
    onToast(`Choose a ${kind === "peep" ? "peep" : "prop"} to use ${state.ui.targeting.label}.`, "info");
    return true;
  }

  /** Keep the preview line in sync with the store and the moving camera. */
  function sync(state) {
    const targeting = state.ui.targeting;
    if (!targeting || !eligibleKind(state)) {
      if (frame) cancelAnimationFrame(frame);
      frame = 0;
      preview = null;
      sourceStackId = "";
      sourcePoint = null;
      if (layer) layer.hidden = true;
      if (targeting && !eligibleKind(state)) store.dispatch({ type: "cancel-targeting" });
      return;
    }
    captureSource(targeting.stackId);
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function tick() {
    frame = 0;
    const state = getState();
    if (!state.ui.targeting) {
      preview = null;
      if (layer) layer.hidden = true;
      return;
    }
    draw();
    frame = requestAnimationFrame(tick);
  }

  return { handle, sync };
}
