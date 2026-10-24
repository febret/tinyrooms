import { createTextPropPreview } from "./text-prop-preview.js";
import { escapeHtml } from "../presentation.js";

/** Check draft complexity before loading fonts or allocating preview geometry. */
export function validateTextDraft(text, options, props = [], id = null) {
  if (!text.content.trim()) return "Enter some text.";
  const length = [...text.content].length;
  if (length > options.max_length) return `Use at most ${options.max_length} characters.`;
  if (text.content.split("\n").length > options.max_lines) return `Use at most ${options.max_lines} lines.`;
  const others = props.filter(prop => prop.text && prop.id !== id);
  if (others.length >= options.max_props) return `A room can contain at most ${options.max_props} text props.`;
  const total = others.reduce((sum, prop) => sum + [...prop.text.content].length, length);
  if (total > options.max_total_length) return `Use at most ${options.max_total_length} text characters across the room.`;
  return "";
}

/** Commit one undoable recipe change; previews never modify the room draft. */
export function openTextPropDialog({ dialogs, store, id = null, propId = "builtin:text" }) {
  const editor = store.getState().editor;
  if (!editor?.canEdit || !editor.textOptions) return;
  const selected = id ? editor.props.find(prop => prop.id === id) : null;
  if (id && (!selected?.text || selected.locked)) return;
  const initial = selected?.text || { content: "Text", font_id: "sans", color: "#ffffff" };
  const options = editor.textOptions;
  let preview, timer, disposed = false;
  function cleanup() {
    disposed = true;
    clearTimeout(timer);
    preview?.dispose();
  }
  dialogs.open(`<section class="global-dialog text-prop-dialog" role="dialog" aria-modal="true" aria-label="${id ? "Edit text" : "Add text"}">
    <h2 id="text-prop-title">${id ? "Edit text" : "Add text"}</h2>
    <label>Text<textarea data-text-content rows="4" aria-label="Text" aria-describedby="text-prop-help">${escapeHtml(initial.content)}</textarea></label>
    <p id="text-prop-help">Up to ${options.max_length} characters and ${options.max_lines} lines. Characters missing from the selected font are skipped in 3D.</p>
    <div class="text-prop-controls"><label>Font<select data-text-font aria-label="Font">${options.fonts.map(font => `<option value="${escapeHtml(font.id)}" ${initial.font_id === font.id ? "selected" : ""}>${escapeHtml(font.label)}</option>`).join("")}</select></label>
    <label>Color<input data-text-color type="color" aria-label="Color" value="${escapeHtml(initial.color)}"></label></div>
    <div class="text-prop-preview"><canvas aria-label="3D text preview"></canvas><div data-text-preview-status></div></div>
    <p data-text-error role="status" aria-live="polite"></p>
    <div class="dialog-actions"><button type="button" data-text-cancel>Cancel</button><button type="button" class="primary" data-text-apply disabled>${id ? "Apply" : "Create"}</button></div>
  </section>`, (shade, close, cancel) => {
    const content = shade.querySelector("[data-text-content]");
    const font = shade.querySelector("[data-text-font]");
    const color = shade.querySelector("[data-text-color]");
    const error = shade.querySelector("[data-text-error]");
    const apply = shade.querySelector("[data-text-apply]");
    preview = createTextPropPreview(shade.querySelector("canvas"), shade.querySelector("[data-text-preview-status]"));
    const recipe = () => ({ content: content.value.normalize("NFC"), font_id: font.value, color: color.value });
    function update(commit = false) {
      clearTimeout(timer);
      apply.disabled = true;
      const text = recipe();
      const current = store.getState().editor;
      if (!current || current.roomId !== editor.roomId) { cleanup(); close(); return; }
      if (disposed) return;
      const message = validateTextDraft(text, options, current.props, id);
      error.textContent = message;
      if (message) return;
      apply.disabled = false;
      if (commit) {
        if (id) store.dispatch({ type: "editor-text", id, text });
        else store.dispatch({ type: "editor-add", propId, text });
        cleanup(); close(); return;
      }
      preview.render(text);
    }
    for (const control of [content, font, color]) control.oninput = () => {
      apply.disabled = true;
      clearTimeout(timer);
      timer = setTimeout(() => update(), 180);
    };
    shade.querySelector("[data-text-cancel]").onclick = cancel;
    apply.onclick = () => update(true);
    content.focus(); content.select();
    update();
  }, cleanup);
}
