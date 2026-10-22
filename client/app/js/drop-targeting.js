import { buildDropCommand } from "./commands.js";

/** Arm-and-click dropping: a selected inventory card drops at the clicked board position. */
export function createDropController({ getState, store, sendCommand, onToast, onError, onDropFlight }) {
  function dropAt(position, screen) {
    const drop = getState().ui.dropTargeting;
    if (!drop || !Array.isArray(position)) return false;
    store.dispatch({ type: "cancel-drop", restoreSelection: false });
    onDropFlight?.(drop.stackId, screen);
    void sendCommand(buildDropCommand(drop.stackId, drop.quantity, position)).catch(onError);
    return true;
  }

  function handle() {
    const drop = getState().ui.dropTargeting;
    if (!drop) return false;
    onToast?.(`Click a spot in the room to drop ${drop.label}.`, "info");
    return true;
  }

  return { dropAt, handle };
}
