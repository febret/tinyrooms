import { modalShell } from "./view-helpers.js";

export function editRoomView(state) {
  const editable = Boolean(state?.room?.editable);
  return modalShell({
    extraClass: "edit-room-view",
    ariaLabel: "Edit Room",
    title: "Edit Room",
    body: editable
      ? '<div class="empty-state">You own this room. Room editing is coming soon.</div>'
      : '<div class="empty-state locked-state">🔒 You do not have permission to edit this room.</div>',
  });
}
