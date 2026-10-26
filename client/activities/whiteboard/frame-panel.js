import {
  DEFAULT_FRAME,
  FRAME_COLOR_PRESETS,
  FRAME_INNERS,
  FRAME_MATTES,
  FRAME_OUTERS,
  normalizeFrame,
} from "../../app/js/whiteboard-frame.js";

function styleGroups(options) {
  const styles = options?.frame_styles;
  return {
    outer: Array.isArray(styles?.outer) && styles.outer.length ? styles.outer : FRAME_OUTERS,
    inner: Array.isArray(styles?.inner) && styles.inner.length ? styles.inner : FRAME_INNERS,
    matte: Array.isArray(styles?.matte) && styles.matte.length ? styles.matte : FRAME_MATTES,
  };
}

export function createFramePanel({ root, options = {}, initialFrame = {}, onChange }) {
  const groups = styleGroups(options);
  const presets = Array.isArray(options?.frame_color_presets) && options.frame_color_presets.length
    ? options.frame_color_presets
    : FRAME_COLOR_PRESETS;
  let frame = normalizeFrame({ ...DEFAULT_FRAME, ...initialFrame });

  root.innerHTML = `
    <h2>Frame</h2>
    <h3>Outer border</h3>
    <div class="option-grid" id="frame-outer" role="group" aria-label="Outer border style"></div>
    <h3>Inner border</h3>
    <div class="option-grid" id="frame-inner" role="group" aria-label="Inner border style"></div>
    <h3>Matte</h3>
    <div class="option-grid" id="frame-matte" role="group" aria-label="Matte style"></div>
    <div class="frame-colors">
      <label>Main
        <input id="frame-main" type="color" value="${frame.main}" aria-label="Frame main color">
        <code id="frame-main-hex">${frame.main}</code>
      </label>
      <label>Accent
        <input id="frame-accent" type="color" value="${frame.accent}" aria-label="Frame accent color">
        <code id="frame-accent-hex">${frame.accent}</code>
      </label>
    </div>
    <h3>Frame colors</h3>
    <div class="swatch-grid" id="frame-presets" role="group" aria-label="Frame color presets"></div>
  `;

  const outerRoot = root.querySelector("#frame-outer");
  const innerRoot = root.querySelector("#frame-inner");
  const matteRoot = root.querySelector("#frame-matte");
  const mainInput = root.querySelector("#frame-main");
  const accentInput = root.querySelector("#frame-accent");
  const mainHex = root.querySelector("#frame-main-hex");
  const accentHex = root.querySelector("#frame-accent-hex");
  const presetRoot = root.querySelector("#frame-presets");

  function markOptions() {
    for (const [key, container] of [["outer", outerRoot], ["inner", innerRoot], ["matte", matteRoot]]) {
      container.querySelectorAll("button").forEach(button => {
        button.setAttribute("aria-pressed", String(button.dataset.value === frame[key]));
      });
    }
  }

  function makeOption(container, key, style) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "option";
    button.dataset.value = style.id;
    button.textContent = style.label;
    button.onclick = () => {
      frame = { ...frame, [key]: style.id };
      markOptions();
      onChange?.({ ...frame });
    };
    container.append(button);
  }

  for (const style of groups.outer) makeOption(outerRoot, "outer", style);
  for (const style of groups.inner) makeOption(innerRoot, "inner", style);
  for (const style of groups.matte) makeOption(matteRoot, "matte", style);

  mainInput.oninput = () => {
    frame = { ...frame, main: mainInput.value.toLowerCase() };
    mainHex.textContent = frame.main;
    onChange?.({ ...frame });
  };
  accentInput.oninput = () => {
    frame = { ...frame, accent: accentInput.value.toLowerCase() };
    accentHex.textContent = frame.accent;
    onChange?.({ ...frame });
  };

  for (const color of presets.filter(value => /^#[0-9a-f]{6}$/i.test(value)).slice(0, 12)) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "swatch";
    button.style.background = color;
    button.setAttribute("aria-label", `Frame color ${color}`);
    button.onclick = () => {
      frame = { ...frame, main: color.toLowerCase() };
      mainInput.value = frame.main;
      mainHex.textContent = frame.main;
      onChange?.({ ...frame });
    };
    presetRoot.append(button);
  }

  markOptions();

  return {
    setFrame(next) {
      frame = normalizeFrame(next);
      mainInput.value = frame.main;
      accentInput.value = frame.accent;
      mainHex.textContent = frame.main;
      accentHex.textContent = frame.accent;
      markOptions();
    },
    getFrame() {
      return { ...frame };
    },
  };
}
