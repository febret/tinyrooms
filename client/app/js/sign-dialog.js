import { escapeHtml } from "./presentation.js";

/** Open the small in-game editor for one sign surface. */
export function openSignDialog({ dialogs, store, api, payload, toast, showError }) {
  const editor = payload || {};
  const surface = editor.surface || {};
  const options = editor.options || {};
  const initial = typeof surface.content?.text === "string" ? surface.content.text : "New sign";
  const maxLength = Number(options.max_length || 240);
  const maxLines = Number(options.max_lines || 8);
  let busy = false;
  dialogs.open(`<section class="global-dialog sign-dialog" role="dialog" aria-modal="true" aria-labelledby="sign-title">
    <h2 id="sign-title">Edit sign</h2>
    <label>Text<textarea data-sign-text rows="5" maxlength="${maxLength}" aria-label="Sign text" aria-describedby="sign-help">${escapeHtml(initial)}</textarea></label>
    <p id="sign-help">Up to ${maxLength} characters and ${maxLines} lines. Everyone in the room can edit this sign.</p>
    <p data-sign-error role="status" aria-live="polite"></p>
    <div class="dialog-actions"><button type="button" data-sign-cancel>Cancel</button><button type="button" class="primary" data-sign-save>Save</button></div>
  </section>`, (shade, close, cancel) => {
    const input = shade.querySelector("[data-sign-text]");
    const error = shade.querySelector("[data-sign-error]");
    const save = shade.querySelector("[data-sign-save]");
    function validate(value) {
      if (!value.trim()) return "Enter some text.";
      if ([...value].length > maxLength) return `Use at most ${maxLength} characters.`;
      if (value.split("\n").length > maxLines) return `Use at most ${maxLines} lines.`;
      return "";
    }
    input.oninput = () => { error.textContent = validate(input.value); };
    shade.querySelector("[data-sign-cancel]").onclick = cancel;
    save.onclick = async () => {
      if (busy) return;
      const message = validate(input.value);
      if (message) { error.textContent = message; return; }
      busy = true;
      save.disabled = true;
      save.textContent = "Saving…";
      try {
        const next = await api.saveSign(editor.room_id, editor.instance_id, input.value.normalize("NFC"));
        if (next) {
          store.dispatch({
            type: "room-event",
            event: {
              type: "room.prop.surface",
              room_id: editor.room_id,
              prop_id: editor.instance_id,
              surface: next,
            },
          });
        }
        close();
        toast("Sign updated.", "success");
      } catch (failure) {
        error.textContent = failure instanceof Error ? failure.message : String(failure);
        save.disabled = false;
        save.textContent = "Save";
        busy = false;
        showError?.(failure);
      }
    };
    input.focus();
    input.select();
  }, () => {});
}
