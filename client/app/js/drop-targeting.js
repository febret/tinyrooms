import { buildContainerDropCommand, buildDropCommand } from "./commands.js";

/** Arm-and-click dropping: a selected inventory card drops at the clicked board position. */
export function createDropController({ getState, store, sendCommand, onToast, onError, onDropFlight }) {
  function dropAt(position, screen) {
    const drop = getState().ui.dropTargeting;
    if (!drop || !Array.isArray(position)) return false;
    store.dispatch({ type: "cancel-drop" });
    onDropFlight?.(drop.stackId, screen);
    void sendCommand(buildDropCommand(drop.stackId, drop.quantity, position)).catch(onError);
    return true;
  }

  function dropOnContainer(propId) {
    const drop = getState().ui.dropTargeting;
    if (!drop) return false;
    store.dispatch({ type: "cancel-drop" });
    void sendCommand(buildContainerDropCommand(drop.stackId, drop.quantity, propId)).catch(onError);
    return true;
  }

  function handle(selection) {
    const drop = getState().ui.dropTargeting;
    if (!drop) return false;
    if (selection?.kind === "prop" && selection.id) {
      const prop = getState().room?.props?.find(entry => entry.id === selection.id);
      if (prop?.behavior === "container") return dropOnContainer(prop.id);
    }
    onToast?.(`Click a spot in the room to drop ${drop.label}.`, "info");
    return true;
  }

  return { dropAt, handle };
}
