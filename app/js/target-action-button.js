export function createTargetActionButton({ button, onConfirm }) {
  let active = false;

  function targetLabel(state, target) {
    if (!state?.room || !target) return "";
    const entities = target.kind === "prop"
      ? state.room.props
      : [...(state.room.occupants || []), ...(state.room.npcs || [])];
    return entities?.find(entity => entity.id === target.id)?.label || "";
  }

  function sync(state, target, point) {
    if (!button) return;
    const label = state?.ui?.targeting?.label;
    const targetName = targetLabel(state, target);
    if (!label || !targetName || !point) {
      clear();
      return;
    }
    const text = `Use ${label} on ${targetName}`;
    if (button.textContent !== text) button.textContent = text;
    button.hidden = false;
    active = true;
    const bounds = button.parentElement.getBoundingClientRect();
    const left = `${Math.max(0, Math.min(bounds.width - button.offsetWidth, point.x + 14))}px`;
    const top = `${Math.max(0, Math.min(bounds.height - button.offsetHeight, point.y + 14))}px`;
    if (button.style.left !== left) button.style.left = left;
    if (button.style.top !== top) button.style.top = top;
  }

  function clear() {
    active = false;
    if (button) button.hidden = true;
  }

  if (button) button.onclick = () => { if (active) onConfirm(); };
  return { sync, clear };
}
