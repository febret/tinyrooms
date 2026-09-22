import { escapeHtml } from "../presentation.js";
import { cardsGrid, modalShell } from "./view-helpers.js";

export function roomView(state) {
  return modalShell({
    extraClass: "room-view",
    ariaLabel: "Room View",
    title: `You see these in <span>${escapeHtml(state.room.label)}</span>:`,
    subtitle: `<p>${escapeHtml(state.room.description)}</p>`,
    body: cardsGrid(state.room.roomCards, "room", state.selection, "No room cards are visible in this room."),
  });
}
