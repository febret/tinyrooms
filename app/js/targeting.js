// Card targeting: with an equipped target card selected, clicking a matching
// prop/peep enters targeting, previews a line from the card to that target, and
// shows an inline "Use <card> on <target>" button. Clicking the target again or
// the button confirms.
//
// Targeting state lives in `state.ui.targeting`. This controller arms targeting
// and turns clicks on props/peeps into `.use` commands; opening another view or
// Escape is handled by the store's reducers.

import { armedTargetStack, findInventoryCard } from "./state.js";
import { createTargetActionButton } from "./target-action-button.js";

export function createTargetingController({ board, boardFrame, getState, store, sendCommand, onToast, onError }) {
  const layer = boardFrame?.querySelector("#target-line") || null;
  const svg = layer?.querySelector("svg") || null;
  const stroke = svg?.querySelector(".target-line-stroke") || null;
  const sourceDot = svg?.querySelector(".target-line-source") || null;
  const endDot = svg?.querySelector(".target-line-end") || null;
  const confirmButton = createTargetActionButton({
    button: boardFrame?.querySelector("#target-confirm") || null,
    onConfirm: () => confirm(),
  });
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
    const state = getState();
    const show = Boolean(preview && state.ui.targeting);
    if (layer) layer.hidden = !show;
    const end = show ? targetPoint(preview.kind, preview.id) : null;
    if (!stroke || !sourcePoint || !end) {
      confirmButton.clear();
      return;
    }
    stroke.setAttribute("x1", sourcePoint.x);
    stroke.setAttribute("y1", sourcePoint.y);
    stroke.setAttribute("x2", end.x);
    stroke.setAttribute("y2", end.y);
    for (const [dot, x, y] of [[sourceDot, sourcePoint.x, sourcePoint.y], [endDot, end.x, end.y]]) {
      dot?.setAttribute("cx", x);
      dot?.setAttribute("cy", y);
    }
    confirmButton.sync(state, preview, end);
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
    if (!state.ui.targeting) {
      const stack = armedTargetStack(state, selection);
      if (!stack) return false;
      store.dispatch({ type: "start-targeting", stackId: stack.stackId, label: stack.definition.label });
      captureSource(stack.stackId);
      choose(selection.kind, selection.id);
      return true;
    }
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
      confirmButton.clear();
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
      confirmButton.clear();
      return;
    }
    draw();
    frame = requestAnimationFrame(tick);
  }

  return { handle, sync };
}
