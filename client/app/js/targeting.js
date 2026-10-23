import { placeAt } from "./presentation.js";
import { isTargetableStack, findInventoryCard, findEntity } from "./state.js";

export function createTargetingController({ board, boardFrame, getState, store, sendCommand, onToast, onError }) {
  const button = boardFrame?.querySelector("#target-confirm") || null;
  if (button) button.onclick = confirm;
  let preview = null;
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

  function targetPoint(kind, id) {
    const entity = findEntity(getState(), { kind, id });
    if (!entity) return null;
    if (kind === "prop") {
      const project = board.projectPositionToScreen;
      const point = typeof project === "function" ? toFrame(project.call(board, entity.position)) : null;
      return point ? { ...point, entity } : null;
    }
    if (kind === "peep") {
      const project = board.projectPositionToScreen;
      if (Array.isArray(entity.spritePosition) && typeof project === "function") {
        const point = toFrame(project.call(board, entity.spritePosition));
        if (point) return { ...point, entity };
      }
      const chip = document.querySelector(`#peeps-panel [data-peep-id="${CSS.escape(id)}"]`);
      if (!chip) return null;
      const bounds = chip.getBoundingClientRect();
      return { ...toFrame({ x: bounds.left + bounds.width / 2, y: bounds.top + bounds.height / 2 }), entity };
    }
    return null;
  }

  function draw() {
    const state = getState();
    const show = Boolean(preview && state.ui.targeting);
    const end = show ? targetPoint(preview.kind, preview.id) : null;
    if (show && !end) preview = null;
    if (button) button.hidden = !end;
    if (button && end) {
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
      if (button) button.hidden = true;
      if (targeting && !eligibleKind(state)) store.dispatch({ type: "cancel-targeting", restoreSelection: false });
      return;
    }
    draw();
    if (!frame) frame = requestAnimationFrame(tick);
  }

  function tick() {
    frame = 0;
    const state = getState();
    if (!state.ui.targeting) {
      preview = null;
      if (button) button.hidden = true;
      return;
    }
    draw();
    frame = requestAnimationFrame(tick);
  }

  return { handle, sync };
}
