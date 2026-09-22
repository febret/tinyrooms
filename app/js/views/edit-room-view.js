import { modalShell } from "./view-helpers.js";

export function editRoomView() {
  return modalShell({
    extraClass: "edit-room-view",
    ariaLabel: "Edit Room",
    title: "Edit Room",
    body: '<div class="empty-state locked-state">🔒 You do not have permission to edit this room. Room editing arrives with the next milestone.</div>',
  });
}
