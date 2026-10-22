import { placeAt } from "./presentation.js";
import { defaultPropAction } from "./prop-actions.js";

export function createPropActionButton({ button, getState, onAction }) {
  let clickedProp = null;

  function sync(state) {
    const prop = clickedProp && state.room?.id === clickedProp.roomId && state.selection.kind === "prop"
      && state.selection.id === clickedProp.id
      && !state.views.main && !state.views.auth && !state.views.commandPalette
      && !state.ui.targeting && !state.ui.dropTargeting && !state.editing && !state.editor
      ? state.room.props.find(entry => entry.id === clickedProp.id) : null;
    const action = defaultPropAction(prop);
    if (!action) {
      clickedProp = null;
      button.hidden = true;
      return;
    }
    if (button.textContent !== action.label) button.textContent = action.label;
    button.hidden = false;
    const bounds = button.parentElement.getBoundingClientRect();
    const x = clickedProp.x - bounds.left + 12;
    const y = clickedProp.y - bounds.top + 12;
    const left = `${Math.max(0, Math.min(bounds.width - button.offsetWidth, x))}px`;
    const top = `${Math.max(0, Math.min(bounds.height - button.offsetHeight, y))}px`;
    placeAt(button, left, top);
  }

  function clear() {
    clickedProp = null;
    button.hidden = true;
  }

  function select(selection, point, room) {
    clickedProp = selection.kind === "prop" && point && defaultPropAction(room?.props.find(prop => prop.id === selection.id))
      ? { id: selection.id, roomId: room.id, ...point } : null;
    if (!clickedProp) button.hidden = true;
  }

  button.onclick = () => {
    const state = getState();
    const prop = !button.hidden && !state.ui.targeting && !state.ui.dropTargeting && !state.editor && !state.views.main
      && !state.views.auth && !state.views.commandPalette
      && state.room?.id === clickedProp?.roomId && state.selection.kind === "prop"
      && state.selection.id === clickedProp.id ? state.room.props.find(entry => entry.id === clickedProp.id) : null;
    const action = defaultPropAction(prop);
    clear();
    if (action) onAction(action);
  };

  return { sync, clear, select };
}
