import { placeAt } from "./presentation.js";
import { isTargetableStack, findInventoryCard, findEntity } from "./state.js";

export function createTargetingController({ board, boardFrame, getState, store, sendCommand, onToast, onError }) {
  const layer = boardFrame?.querySelector("#target-line") || null;
  const svg = layer?.querySelector("svg") || null;
  const stroke = svg?.querySelector(".target-line-stroke") || null;
  const sourceDot = svg?.querySelector(".target-line-source") || null;
  const endDot = svg?.querySelector(".target-line-end") || null;
  const button = boardFrame?.querySelector("#target-confirm") || null;
  if (button) button.onclick = confirm;
  let preview = null;
  let sourceStackId = "";
  let sourcePoint = null;
  let frame = 0;

  function eligibleKind(state) {
    const stack = findInventoryCard(state, state.ui.targeting?.stackId);
    return isTargetableStack(stack) ? stack.definition.target : "";
  }

  function toFrame(point) {
    if (!point) return null;
    const bounds = boardFrame?.getBoundingClientRect();
    if (!bounds) return point;
    return { x: point.x - bounds.left, y: point.y - bounds.top };
  }

  function captureSource(stackId) {
    if (sourceStackId !== stackId) preview = null;
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
    const entity = findEntity(getState(), { kind, id });
    if (!entity) return null;
    if (kind === "prop") {
      const project = board.projectPositionToScreen;
      const point = typeof project === "function" ? toFrame(project.call(board, entity.position)) : null;
      return point ? { ...point, entity } : null;
    }
    if (kind === "peep") {
      const chip = document.querySelector(`#peeps-panel [data-peep-id="${CSS.escape(id)}"]`);
      if (!chip) return null;
      const bounds = chip.getBoundingClientRect();
      return { ...toFrame({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 }), entity };
    }
    return null;
  }

  function draw() {
    const state = getState();
    if (state.ui.targeting) captureSource(state.ui.targeting.stackId);
    const show = Boolean(preview && state.ui.targeting);
    const end = show ? targetPoint(preview.kind, preview.id) : null;
    if (show && !end) preview = null;
    if (layer) layer.hidden = !end;
    if (button) button.hidden = !end;
    if (!stroke || !sourcePoint || !end) {
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
    if (button) {
      const text = `Use ${state.ui.targeting.label} on ${end.entity.label}`;
      if (button.textContent !== text) button.textContent = text;
      const bounds = boardFrame.getBoundingClientRect();
      const left = `${Math.max(0, Math.min(bounds.width - button.offsetWidth, end.x + 14))}px`;
      const top = `${Math.max(0, Math.min(bounds.height - button.offsetHeight, end.y + 14))}px`;
      placeAt(button, left, top);
    }
  }

  function confirm() {
    const targeting = getState().ui.targeting;
    const target = preview;
    preview = null;
    if (!targeting || !target) return;
    if (eligibleKind(getState()) !== target.kind || !targetPoint(target.kind, target.id)) return;
    store.dispatch({ type: "cancel-targeting", restoreSelection: false });
    void sendCommand(`.use @card:${targeting.stackId} @${target.kind}:${target.id}`).catch(onError);
  }

  function choose(kind, id) {
    captureSource(getState().ui.targeting.stackId);
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
    if (kind === selection.kind && selection.id) {
      choose(kind, selection.id);
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
      if (button) button.hidden = true;
      if (targeting && !eligibleKind(state)) store.dispatch({ type: "cancel-targeting", restoreSelection: false });
      return;
    }
    captureSource(targeting.stackId);
    draw();
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function tick() {
    frame = 0;
    const state = getState();
    if (!state.ui.targeting) {
      preview = null;
      if (layer) layer.hidden = true;
      if (button) button.hidden = true;
      return;
    }
    draw();
    frame = requestAnimationFrame(tick);
  }

  return { handle, sync };
}
