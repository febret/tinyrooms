const MIN_PANEL = 120;
const MIN_ABOVE = 200;
const KEY_STEP = 24;

export function bindPanelSplitters(stage) {
  const resize = height => {
    const max = Math.max(MIN_PANEL, stage.clientHeight - MIN_ABOVE);
    stage.style.setProperty("--lower-height", `${Math.round(Math.min(max, Math.max(MIN_PANEL, height)))}px`);
  };

  stage.addEventListener("pointerdown", event => {
    const handle = event.target.closest(".we-splitter");
    if (!handle) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = handle.parentElement.offsetHeight;
    const move = moveEvent => resize(startHeight + startY - moveEvent.clientY);
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.setPointerCapture(event.pointerId);
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  });

  stage.addEventListener("keydown", event => {
    const handle = event.target.closest?.(".we-splitter");
    if (!handle || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    resize(handle.parentElement.offsetHeight + (event.key === "ArrowUp" ? KEY_STEP : -KEY_STEP));
  });
}
