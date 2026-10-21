import {
  checkbox,
  escapeHtml,
  field,
  numberInput,
  panelHeader,
  selectOptions,
  textInput,
} from "./util.js";

function vecRow(label, path, value) {
  const vec = Array.isArray(value) ? value : [0, 0, 0];
  return `
    <div class="pe-field-row pe-vec">
      <span class="pe-vec-label">${escapeHtml(label)}</span>
      ${[0, 1, 2].map(axis => numberInput(vec[axis] ?? 0, `data-pe-effect="${path}.${axis}" data-pe-kind="number"`)).join("")}
    </div>
  `;
}

function rangeRow(label, path, value) {
  const range = Array.isArray(value) ? value : [0, 0];
  return `
    <div class="pe-field-row pe-vec">
      <span class="pe-vec-label">${escapeHtml(label)}</span>
      ${[0, 1].map(index => numberInput(range[index] ?? 0, `data-pe-effect="${path}.${index}" data-pe-kind="number"`)).join("")}
    </div>
  `;
}

function transformLayer(layer, index, enums) {
  return `
    ${field("Motion", `<select data-pe-effect="layers.${index}.motion" data-pe-kind="text">${selectOptions(enums.transform_motions || [], layer.motion)}</select>`)}
    <div class="pe-field-row">
      ${field("Amplitude", numberInput(layer.amplitude ?? 0.08, `data-pe-effect="layers.${index}.amplitude" data-pe-kind="number"`))}
      ${field("Period", numberInput(layer.period ?? 3, `data-pe-effect="layers.${index}.period" data-pe-kind="number"`))}
      ${field("Phase", numberInput(layer.phase ?? 0, `data-pe-effect="layers.${index}.phase" data-pe-kind="number"`))}
    </div>
    ${vecRow("Axis", `layers.${index}.axis`, layer.axis)}
  `;
}

function materialLayer(layer, index) {
  return `
    <div class="pe-field-row">
      ${field("Emissive", textInput(layer.emissive || "", `data-pe-effect="layers.${index}.emissive" data-pe-kind="text"`, "#ff9a4d"))}
      ${field("Intensity", numberInput(layer.emissive_intensity ?? 1, `data-pe-effect="layers.${index}.emissive_intensity" data-pe-kind="number"`))}
    </div>
    <div class="pe-field-row">
      ${field("Color", textInput(layer.color || "", `data-pe-effect="layers.${index}.color" data-pe-kind="text"`, "#ffffff"))}
      ${field("Opacity", numberInput(layer.opacity ?? 1, `data-pe-effect="layers.${index}.opacity" data-pe-kind="number"`))}
    </div>
    <div class="pe-field-row">
      ${field("Flicker", numberInput(layer.flicker ?? 0, `data-pe-effect="layers.${index}.flicker" data-pe-kind="number"`))}
      ${field("Flicker Hz", numberInput(layer.flicker_hz ?? 6, `data-pe-effect="layers.${index}.flicker_hz" data-pe-kind="number"`))}
    </div>
  `;
}

function particleLayer(layer, index, enums) {
  return `
    <div class="pe-field-row">
      ${field("Preset", `<select data-pe-effect="layers.${index}.preset" data-pe-kind="text">${selectOptions(enums.particle_presets || [], layer.preset)}</select>`)}
      ${field("Texture", `<select data-pe-effect="layers.${index}.texture" data-pe-kind="text">${selectOptions(enums.textures || [], layer.texture)}</select>`)}
      ${field("Anchor", `<select data-pe-effect="layers.${index}.anchor" data-pe-kind="text">${selectOptions(enums.particle_anchors || [], layer.anchor || "top")}</select>`)}
    </div>
    <div class="pe-field-row">
      ${field("Rate", numberInput(layer.rate ?? 6, `data-pe-effect="layers.${index}.rate" data-pe-kind="number"`))}
      ${field("Speed", numberInput(layer.speed ?? 0.3, `data-pe-effect="layers.${index}.speed" data-pe-kind="number"`))}
      ${field("Spread", numberInput(layer.spread ?? 30, `data-pe-effect="layers.${index}.spread" data-pe-kind="number"`))}
      ${field("Gravity", numberInput(layer.gravity ?? 0, `data-pe-effect="layers.${index}.gravity" data-pe-kind="number"`))}
    </div>
    ${rangeRow("Lifetime", `layers.${index}.lifetime`, layer.lifetime)}
    ${rangeRow("Size", `layers.${index}.size`, layer.size)}
    ${rangeRow("Opacity", `layers.${index}.opacity`, layer.opacity)}
    <div class="pe-field-row">
      ${field("Color", textInput(layer.color || "#ffffff", `data-pe-effect="layers.${index}.color" data-pe-kind="text"`))}
      ${field("Max particles", numberInput(layer.max_particles ?? 40, `data-pe-effect="layers.${index}.max_particles" data-pe-kind="int"`, "1"))}
      <label class="pe-check">${checkbox(Boolean(layer.additive), `data-pe-effect="layers.${index}.additive" data-pe-kind="bool"`)} additive</label>
    </div>
    ${vecRow("Offset", `layers.${index}.offset`, layer.offset)}
  `;
}

function layerEditor(layer, index, enums) {
  const type = layer?.type || "";
  let body = "";
  if (type === "transform") body = transformLayer(layer, index, enums);
  else if (type === "material") body = materialLayer(layer, index);
  else if (type === "particle") body = particleLayer(layer, index, enums);
  return `
    <div class="pe-layer">
      <div class="pe-layer-head">
        <strong>${escapeHtml(type || "unknown")}</strong>
        <div class="pe-layer-buttons">
          <button type="button" class="pe-icon" data-pe-move-layer="${index}:-1" aria-label="Move layer up">↑</button>
          <button type="button" class="pe-icon" data-pe-move-layer="${index}:1" aria-label="Move layer down">↓</button>
          <button type="button" class="pe-icon" data-pe-remove-layer="${index}" aria-label="Remove layer">✕</button>
        </div>
      </div>
      ${body}
    </div>
  `;
}

export function renderEffectsPanel(state) {
  const enums = state.enums || {};
  const effects = state.effects || [];
  const options = effects
    .map(effect => ({ value: effect.id, label: `${effect.label || effect.id} (${effect.id})` }));
  const picker = `
    ${field("Effect", `<select data-pe-effect-select data-pe-kind="text">${
      selectOptions([{ value: "", label: effects.length ? "Select an effect…" : "No effects defined" }, ...options], state.selectedEffectId || "")
    }</select>`)}
  `;
  const draft = state.effectDraft;
  const editor = draft ? `
    <div class="pe-panel-body">
      ${field("Label", textInput(draft.label || "", `data-pe-effect="label" data-pe-kind="text"`))}
      <fieldset class="pe-subgroup">
        <legend>Layers</legend>
        ${(draft.layers || []).map((layer, index) => layerEditor(layer, index, enums)).join("") || '<p class="pe-hint">No layers.</p>'}
        <div class="pe-actions">
          <button type="button" class="pe-quiet" data-pe-add-layer="transform">Add transform</button>
          <button type="button" class="pe-quiet" data-pe-add-layer="material">Add material</button>
          <button type="button" class="pe-quiet" data-pe-add-layer="particle">Add particle</button>
        </div>
      </fieldset>
      <details class="pe-advanced">
        <summary>Advanced (raw JSON)</summary>
        <textarea data-pe-json="effect" rows="10">${escapeHtml(JSON.stringify(draft, null, 2))}</textarea>
        <div class="pe-actions">
          <button type="button" class="pe-quiet" data-pe-json-apply="effect">Apply JSON</button>
          <button type="button" class="pe-quiet" data-pe-json-reset="effect">Reset</button>
        </div>
      </details>
      <div class="pe-actions">
        <button type="button" class="pe-primary" data-pe-save-effect ${state.effectDirty ? "" : "disabled"}>Save effect</button>
        <button type="button" class="pe-quiet" data-pe-reset-effect ${state.effectDirty ? "" : "disabled"}>Revert changes</button>
        <span class="pe-status" role="status">${state.effectDirty ? "Unsaved changes" : "Saved"}</span>
      </div>
    </div>
  ` : `<p class="pe-empty">Select an effect to edit its layer stack.</p>`;
  return `
    ${panelHeader("Effects", "data/fx/*.yaml layer stacks")}
    <div class="pe-panel-body">
      ${picker}
      ${editor}
    </div>
  `;
}
