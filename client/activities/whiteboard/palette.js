const RECENT_KEY = "tinyrooms:whiteboard:recent-colors";

const CURATED_COLORS = Object.freeze([
  "#101418", "#1f2933", "#3d4852", "#5b6770", "#9aa5b1", "#e8eaed",
  "#7a1f1f", "#d64545", "#e08a1e", "#f3c969", "#f6efd8", "#8b1e2d",
  "#14424f", "#2f6fdb", "#7cc4e8", "#bfe3f0", "#123f2c", "#2f8f5b",
  "#9fd3a8", "#e6f2df", "#5b2d82", "#9b6dd6", "#e6b8d6", "#f6e3ee",
]);

export function hexToRgb(hex) {
  return [
    parseInt(hex.slice(1, 3), 16),
    parseInt(hex.slice(3, 5), 16),
    parseInt(hex.slice(5, 7), 16),
  ];
}

export function rgbToHex(red, green, blue) {
  return `#${[red, green, blue].map(part => Math.max(0, Math.min(255, Math.round(part))).toString(16).padStart(2, "0")).join("")}`;
}

export function hexToHsv(hex) {
  const [red, green, blue] = hexToRgb(hex).map(part => part / 255);
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  let hue = 0;
  if (delta) {
    if (max === red) hue = ((green - blue) / delta) % 6;
    else if (max === green) hue = (blue - red) / delta + 2;
    else hue = (red - green) / delta + 4;
    hue *= 60;
    if (hue < 0) hue += 360;
  }
  return {
    h: Math.round(hue),
    s: max === 0 ? 0 : Math.round((delta / max) * 100),
    v: Math.round(max * 100),
  };
}

export function hsvToHex(h, s, v) {
  const saturation = Math.max(0, Math.min(100, s)) / 100;
  const value = Math.max(0, Math.min(100, v)) / 100;
  const chroma = value * saturation;
  const sector = ((h % 360) / 60 + 6) % 6;
  const middle = chroma * (1 - Math.abs((sector % 2) - 1));
  let red = 0;
  let green = 0;
  let blue = 0;
  if (sector < 1) [red, green] = [chroma, middle];
  else if (sector < 2) [red, green] = [middle, chroma];
  else if (sector < 3) [green, blue] = [chroma, middle];
  else if (sector < 4) [green, blue] = [middle, chroma];
  else if (sector < 5) [red, blue] = [middle, chroma];
  else [red, blue] = [chroma, middle];
  const lift = value - chroma;
  return rgbToHex((red + lift) * 255, (green + lift) * 255, (blue + lift) * 255);
}

function readRecent() {
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || "[]");
    return Array.isArray(raw) ? raw.filter(color => /^#[0-9a-f]{6}$/i.test(color)).slice(0, 8) : [];
  } catch {
    return [];
  }
}

function writeRecent(colors) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(colors.slice(0, 8)));
  } catch {
    // Recent colors are a convenience; storage failures must not break painting.
  }
}

export function createPalette({ root, initialColors = [], onChange }) {
  const state = {
    h: 210, s: 18, v: 12,
    color: "#1f2933",
    swatches: [],
    recent: readRecent(),
  };

  root.innerHTML = `
    <h2>Color</h2>
    <div class="palette-preview"><span id="palette-chip"></span><code id="palette-hex">#1f2933</code></div>
    <canvas id="palette-field" width="220" height="150" aria-label="Saturation and brightness field"></canvas>
    <label class="palette-hue">Hue
      <input id="palette-hue" type="range" min="0" max="359" value="210" aria-label="Hue">
    </label>
    <label class="palette-hex">Hex
      <input id="palette-text" type="text" value="#1f2933" maxlength="7" spellcheck="false" aria-label="Color hex value">
    </label>
    <h3>Palette</h3>
    <div class="swatch-grid" id="palette-swatches" role="group" aria-label="Color swatches"></div>
    <h3>Recent</h3>
    <div class="swatch-grid" id="palette-recent" role="group" aria-label="Recent colors"></div>
  `;

  const field = root.querySelector("#palette-field");
  const fieldContext = field.getContext("2d");
  const hueInput = root.querySelector("#palette-hue");
  const hexInput = root.querySelector("#palette-text");
  const chip = root.querySelector("#palette-chip");
  const hexLabel = root.querySelector("#palette-hex");
  const swatchRoot = root.querySelector("#palette-swatches");
  const recentRoot = root.querySelector("#palette-recent");

  function paintField() {
    const base = hsvToHex(state.h, 100, 100);
    const horizontal = fieldContext.createLinearGradient(0, 0, field.width, 0);
    horizontal.addColorStop(0, "#ffffff");
    horizontal.addColorStop(1, base);
    fieldContext.fillStyle = horizontal;
    fieldContext.fillRect(0, 0, field.width, field.height);
    const vertical = fieldContext.createLinearGradient(0, 0, 0, field.height);
    vertical.addColorStop(0, "rgba(0,0,0,0)");
    vertical.addColorStop(1, "rgba(0,0,0,1)");
    fieldContext.fillStyle = vertical;
    fieldContext.fillRect(0, 0, field.width, field.height);
    fieldContext.strokeStyle = "#ffffff";
    fieldContext.lineWidth = 3;
    fieldContext.beginPath();
    fieldContext.arc((state.s / 100) * field.width, (1 - state.v / 100) * field.height, 8, 0, Math.PI * 2);
    fieldContext.stroke();
    fieldContext.strokeStyle = "rgba(0,0,0,.45)";
    fieldContext.lineWidth = 1.5;
    fieldContext.stroke();
  }

  function commit(color, { remember = false } = {}) {
    const normalized = /^#[0-9a-f]{6}$/i.test(color) ? color.toLowerCase() : state.color;
    state.color = normalized;
    const hsv = hexToHsv(normalized);
    state.h = hsv.h;
    state.s = hsv.s;
    state.v = hsv.v;
    chip.style.background = normalized;
    hexLabel.textContent = normalized;
    if (document.activeElement !== hexInput) hexInput.value = normalized;
    if (String(hueInput.value) !== String(state.h)) hueInput.value = String(state.h);
    paintField();
    markSwatches();
    if (remember) rememberColor(normalized);
    onChange?.(normalized);
  }

  function rememberColor(color) {
    state.recent = [color, ...state.recent.filter(entry => entry !== color)].slice(0, 8);
    writeRecent(state.recent);
    paintRecent();
    markSwatches();
  }

  function makeSwatch(color, group) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "swatch";
    button.style.background = color;
    button.dataset.color = color;
    button.dataset.group = group;
    button.setAttribute("aria-label", `Use ${color}`);
    button.onclick = () => commit(color, { remember: true });
    return button;
  }

  function markSwatches() {
    root.querySelectorAll(".swatch").forEach(swatch => {
      swatch.setAttribute("aria-pressed", String(swatch.dataset.color === state.color));
    });
  }

  function paintSwatches() {
    swatchRoot.replaceChildren();
    const seeds = [...new Set([...(initialColors || []), ...CURATED_COLORS])]
      .filter(color => /^#[0-9a-f]{6}$/i.test(color))
      .slice(0, 30);
    state.swatches = seeds;
    for (const color of seeds) swatchRoot.append(makeSwatch(color.toLowerCase(), "palette"));
    markSwatches();
  }

  function paintRecent() {
    recentRoot.replaceChildren();
    if (!state.recent.length) {
      const empty = document.createElement("p");
      empty.className = "muted smallprint";
      empty.textContent = "Paint to build recent colors.";
      recentRoot.append(empty);
      return;
    }
    for (const color of state.recent) recentRoot.append(makeSwatch(color, "recent"));
    markSwatches();
  }

  let fieldActive = false;
  function fieldColor(event) {
    const rect = field.getBoundingClientRect();
    const saturation = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    const value = 1 - Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height));
    state.s = Math.round(saturation * 100);
    state.v = Math.round(value * 100);
    commit(hsvToHex(state.h, state.s, state.v));
  }
  field.addEventListener("pointerdown", event => {
    fieldActive = true;
    field.setPointerCapture?.(event.pointerId);
    fieldColor(event);
  });
  field.addEventListener("pointermove", event => {
    if (fieldActive) fieldColor(event);
  });
  field.addEventListener("pointerup", () => {
    if (fieldActive) {
      fieldActive = false;
      rememberColor(state.color);
    }
  });
  hueInput.addEventListener("input", () => {
    state.h = Number(hueInput.value);
    commit(hsvToHex(state.h, state.s, state.v));
  });
  hueInput.addEventListener("change", () => rememberColor(state.color));
  hexInput.addEventListener("change", () => commit(hexInput.value.trim(), { remember: true }));

  paintSwatches();
  paintRecent();

  return {
    setColor(color) {
      commit(color);
    },
    getColor() {
      return state.color;
    },
  };
}
