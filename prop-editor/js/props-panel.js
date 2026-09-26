import {
  checkbox,
  escapeHtml,
  field,
  numberInput,
  panelHeader,
  selectOptions,
  textarea,
  textInput,
} from "./util.js";

function effectSetEditor(prop, effects) {
  const sets = Object.entries(prop.effects || {});
  const options = effects.map(effect => ({ value: effect.id, label: effect.label || effect.id }));
  return `
    <fieldset class="pe-subgroup">
      <legend>Effect sets</legend>
      <p class="pe-hint">Each named set is an ordered list of effect ids. Rooms can switch a prop between sets.</p>
      ${sets.map(([name, ids], index) => `
        <div class="pe-set">
          <div class="pe-set-head">
            <input type="text" data-pe-set-name="${index}" value="${escapeHtml(name)}" aria-label="Effect set name">
            <button type="button" class="pe-icon" data-pe-remove-set="${index}" aria-label="Remove set">✕</button>
          </div>
          <div class="pe-chips">
            ${options.map(effect => `
              <label class="pe-chip">
                <input type="checkbox" data-pe-set-toggle="${index}:${escapeHtml(effect.value)}"
                  ${(ids || []).includes(effect.value) ? "checked" : ""}>
                ${escapeHtml(effect.label)}
              </label>
            `).join("") || '<span class="pe-hint">No effects are defined.</span>'}
          </div>
        </div>
      `).join("") || '<p class="pe-hint">No effect sets.</p>'}
      <button type="button" class="pe-quiet" data-pe-add-set>Add effect set</button>
    </fieldset>
  `;
}

export function renderPropsPanel(state) {
  const prop = state.propDraft;
  if (!prop) {
    return `<p class="pe-empty">Select a prop from the library to edit its definition.</p>`;
  }
  const file = state.file || {};
  const enums = state.enums || {};
  const setNames = Object.keys(prop.effects || {});
  const models = file.models || [];
  const modelOptions = models.includes(prop.model) || !prop.model
    ? models
    : [prop.model, ...models];
  return `
    ${panelHeader(prop.label || state.selected?.id || "Prop", `${state.selected?.id || ""} · ${file.kind || ""}/${file.source || ""}`)}
    <div class="pe-panel-body">
      ${field("Label", textInput(prop.label, `data-pe-prop="label" data-pe-kind="text"`))}
      ${field("Description", textarea(prop.description, `data-pe-prop="description" data-pe-kind="text"`, 3))}
      ${field("Model", `<select data-pe-prop="model" data-pe-kind="text">${selectOptions(modelOptions, prop.model)}</select>`)}
      <div class="pe-field-row">
        ${field("Animation", textInput(prop.animation || "", `data-pe-prop="animation" data-pe-kind="text"`, "auto"))}
        ${field("Scale", numberInput(prop.scale ?? 1, `data-pe-prop="scale" data-pe-kind="number"`))}
      </div>
      <div class="pe-field-row">
        ${field("Editor min", numberInput(prop.editor_scale_min ?? 0.25, `data-pe-prop="editor_scale_min" data-pe-kind="number"`))}
        ${field("Editor max", numberInput(prop.editor_scale_max ?? 4, `data-pe-prop="editor_scale_max" data-pe-kind="number"`))}
        ${field("Price", numberInput(prop.price ?? 5, `data-pe-prop="price" data-pe-kind="int"`, "1"))}
      </div>
      <div class="pe-field-row pe-checks">
        <label class="pe-check">${checkbox(Boolean(prop.decorative), `data-pe-prop="decorative" data-pe-kind="bool"`)} decorative</label>
        <label class="pe-check">${checkbox(Boolean(prop.editable), `data-pe-prop="editable" data-pe-kind="bool"`)} editable</label>
        <label class="pe-check">${checkbox(Boolean(prop.locked), `data-pe-prop="locked" data-pe-kind="bool"`)} locked</label>
        <label class="pe-check" title="Hide from the room editor, prop shop, and all in-game prop lists and renders.">${checkbox(Boolean(prop.hidden), `data-pe-prop="hidden" data-pe-kind="bool"`)} hidden</label>
      </div>
      ${prop.hidden ? '<p class="pe-hint">Hidden: this prop is excluded from the room editor, the prop shop, and every in-game render and list, but stays in its room definitions.</p>' : ""}
      ${field("Tags (comma-separated)", textInput((prop.tags || []).join(", "), `data-pe-prop="tags" data-pe-kind="csv"`))}
      ${effectSetEditor(prop, state.effects || [])}
      ${field("Active effect set", `<select data-pe-prop="active_effect" data-pe-kind="text">
        <option value="">(first set)</option>
        ${selectOptions(setNames, prop.active_effect || "")}
      </select>`)}
      <fieldset class="pe-subgroup">
        <legend>File settings</legend>
        ${field("CONFIG scale_adjust", numberInput(file.scale_adjust ?? 1, `data-pe-file="scale_adjust" data-pe-kind="number"`))}
        <p class="pe-hint">Multiplies every prop's scale in <code>${escapeHtml(file.path || "")}</code>. Current effective scale: ${escapeHtml(state.propScale ?? "")}.</p>
      </fieldset>
      <details class="pe-advanced">
        <summary>Advanced (raw JSON)</summary>
        <textarea data-pe-json="prop" rows="10">${escapeHtml(JSON.stringify(prop, null, 2))}</textarea>
        <div class="pe-actions">
          <button type="button" class="pe-quiet" data-pe-json-apply="prop">Apply JSON</button>
          <button type="button" class="pe-quiet" data-pe-json-reset="prop">Reset</button>
        </div>
      </details>
      <div class="pe-actions">
        <button type="button" class="pe-primary" data-pe-save-prop ${state.propDirty ? "" : "disabled"}>Save prop</button>
        <button type="button" class="pe-quiet" data-pe-reset-prop ${state.propDirty ? "" : "disabled"}>Revert changes</button>
        <span class="pe-status" role="status">${state.propDirty ? "Unsaved changes" : "Saved"}</span>
      </div>
    </div>
  `;
}

export { escapeHtml };
