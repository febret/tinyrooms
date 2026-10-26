export const WHITEBOARD_ART_WIDTH = 1024;
export const WHITEBOARD_ART_HEIGHT = 640;

export const FRAME_OUTERS = Object.freeze([
  { id: "float", label: "Float" },
  { id: "flat", label: "Flat" },
  { id: "bevel", label: "Bevel" },
  { id: "stepped", label: "Stepped" },
  { id: "ornate", label: "Ornate" },
]);

export const FRAME_INNERS = Object.freeze([
  { id: "none", label: "None" },
  { id: "hairline", label: "Hairline" },
  { id: "bevel", label: "Bevel" },
  { id: "double", label: "Double" },
  { id: "inlay", label: "Inlay" },
]);

export const FRAME_MATTES = Object.freeze([
  { id: "none", label: "No matte" },
  { id: "slim", label: "Slim" },
  { id: "gallery", label: "Gallery" },
  { id: "linen", label: "Linen" },
  { id: "shadowbox", label: "Shadowbox" },
]);

export const FRAME_COLOR_PRESETS = Object.freeze([
  "#7a5230", "#2f3b3a", "#101418", "#8b1e2d", "#14424f", "#c9a45c",
]);

export const DEFAULT_FRAME = Object.freeze({
  outer: "bevel",
  inner: "hairline",
  matte: "gallery",
  main: "#7a5230",
  accent: "#c9a45c",
});

const OUTER_IDS = new Set(FRAME_OUTERS.map(style => style.id));
const INNER_IDS = new Set(FRAME_INNERS.map(style => style.id));
const MATTE_IDS = new Set(FRAME_MATTES.map(style => style.id));

const OUTER_THICKNESS = Object.freeze({
  float: 14, flat: 18, bevel: 24, stepped: 28, ornate: 34,
});
const MATTE_THICKNESS = Object.freeze({
  none: 0, slim: 26, gallery: 52, linen: 46, shadowbox: 68,
});
const INNER_THICKNESS = Object.freeze({
  none: 0, hairline: 3, bevel: 7, double: 10, inlay: 6,
});

export function normalizeColor(value, fallback) {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value)
    ? value.toLowerCase()
    : fallback;
}

export function normalizeFrame(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  return {
    outer: OUTER_IDS.has(source.outer) ? source.outer : DEFAULT_FRAME.outer,
    inner: INNER_IDS.has(source.inner) ? source.inner : DEFAULT_FRAME.inner,
    matte: MATTE_IDS.has(source.matte) ? source.matte : DEFAULT_FRAME.matte,
    main: normalizeColor(source.main, DEFAULT_FRAME.main),
    accent: normalizeColor(source.accent, DEFAULT_FRAME.accent),
  };
}

export function frameLayout(frame) {
  const normalized = normalizeFrame(frame);
  const outer = OUTER_THICKNESS[normalized.outer] || 0;
  const matte = MATTE_THICKNESS[normalized.matte] || 0;
  const inner = INNER_THICKNESS[normalized.inner] || 0;
  const margin = outer + matte + inner;
  return {
    frame: normalized,
    outer,
    matte,
    inner,
    margin,
    width: WHITEBOARD_ART_WIDTH + margin * 2,
    height: WHITEBOARD_ART_HEIGHT + margin * 2,
    artX: margin,
    artY: margin,
    artWidth: WHITEBOARD_ART_WIDTH,
    artHeight: WHITEBOARD_ART_HEIGHT,
  };
}

function parseHex(color) {
  return [
    parseInt(color.slice(1, 3), 16),
    parseInt(color.slice(3, 5), 16),
    parseInt(color.slice(5, 7), 16),
  ];
}

function shade(color, amount) {
  const [red, green, blue] = parseHex(color);
  const adjust = value => Math.max(0, Math.min(255, Math.round(value + amount)));
  return `#${[adjust(red), adjust(green), adjust(blue)].map(part => part.toString(16).padStart(2, "0")).join("")}`;
}

function strokeRect(context, x, y, width, height) {
  context.strokeRect(x + 0.5, y + 0.5, Math.max(1, width - 1), Math.max(1, height - 1));
}

function drawOuter(context, layout, main, accent) {
  const { width, height, outer } = layout;
  if (outer <= 0) return;
  context.save();
  context.fillStyle = main;
  context.fillRect(0, 0, width, height);
  if (layout.frame.outer === "float") {
    context.fillStyle = "rgba(0, 0, 0, 0.34)";
    context.fillRect(0, 0, width, 5);
    context.fillRect(0, height - 5, width, 5);
    context.strokeStyle = shade(main, 42);
    context.lineWidth = 2;
    strokeRect(context, outer - 3, outer - 3, width - (outer - 3) * 2, height - (outer - 3) * 2);
  } else if (layout.frame.outer === "bevel") {
    const gradient = context.createLinearGradient(0, 0, width, height);
    gradient.addColorStop(0, shade(main, 46));
    gradient.addColorStop(0.5, main);
    gradient.addColorStop(1, shade(main, -46));
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
    context.strokeStyle = shade(main, -58);
    context.lineWidth = 3;
    strokeRect(context, 2, 2, width - 4, height - 4);
    context.strokeStyle = accent;
    context.lineWidth = 2;
    strokeRect(context, outer - 4, outer - 4, width - (outer - 4) * 2, height - (outer - 4) * 2);
  } else if (layout.frame.outer === "stepped") {
    context.strokeStyle = accent;
    context.lineWidth = 3;
    strokeRect(context, 5, 5, width - 10, height - 10);
    strokeRect(context, outer - 5, outer - 5, width - (outer - 5) * 2, height - (outer - 5) * 2);
  } else if (layout.frame.outer === "ornate") {
    context.strokeStyle = accent;
    context.lineWidth = 2;
    strokeRect(context, 4, 4, width - 8, height - 8);
    strokeRect(context, 9, 9, width - 18, height - 18);
    context.strokeStyle = shade(main, 34);
    context.lineWidth = 3;
    strokeRect(context, outer - 4, outer - 4, width - (outer - 4) * 2, height - (outer - 4) * 2);
  } else {
    context.strokeStyle = shade(main, -34);
    context.lineWidth = 2;
    strokeRect(context, 1, 1, width - 2, height - 2);
  }
  context.restore();
}

function drawMatte(context, layout) {
  const { outer, matte, width, height } = layout;
  if (matte <= 0) return;
  const x = outer;
  const y = outer;
  const matteWidth = width - outer * 2;
  const matteHeight = height - outer * 2;
  context.save();
  context.fillStyle = "#f3ecdd";
  context.fillRect(x, y, matteWidth, matteHeight);
  context.strokeStyle = "rgba(90, 70, 45, 0.22)";
  context.lineWidth = 2;
  strokeRect(context, x + 1, y + 1, matteWidth - 2, matteHeight - 2);
  if (layout.frame.matte === "linen") {
    context.strokeStyle = "rgba(120, 95, 60, 0.20)";
    context.lineWidth = 1;
    for (let lineX = x + 4; lineX < x + matteWidth; lineX += 7) {
      context.beginPath();
      context.moveTo(lineX, y);
      context.lineTo(lineX, y + matteHeight);
      context.stroke();
    }
    for (let lineY = y + 4; lineY < y + matteHeight; lineY += 7) {
      context.beginPath();
      context.moveTo(x, lineY);
      context.lineTo(x + matteWidth, lineY);
      context.stroke();
    }
  } else if (layout.frame.matte === "shadowbox") {
    const gradient = context.createLinearGradient(0, y + matteHeight, 0, y + matteHeight - 24);
    gradient.addColorStop(0, "rgba(45, 30, 18, 0.34)");
    gradient.addColorStop(1, "rgba(45, 30, 18, 0)");
    context.fillStyle = gradient;
    context.fillRect(x, y + matteHeight - 24, matteWidth, 24);
  }
  context.restore();
}

function drawInner(context, layout, main, accent) {
  const { artX, artY, artWidth, artHeight, inner } = layout;
  if (inner <= 0) return;
  context.save();
  if (layout.frame.inner === "hairline") {
    context.strokeStyle = accent;
    context.lineWidth = 2;
    strokeRect(context, artX - 1, artY - 1, artWidth + 2, artHeight + 2);
  } else if (layout.frame.inner === "double") {
    context.strokeStyle = accent;
    context.lineWidth = 2;
    strokeRect(context, artX - 2, artY - 2, artWidth + 4, artHeight + 4);
    strokeRect(context, artX - 7, artY - 7, artWidth + 14, artHeight + 14);
  } else if (layout.frame.inner === "inlay") {
    context.strokeStyle = main;
    context.lineWidth = inner;
    context.strokeRect(artX - inner / 2, artY - inner / 2, artWidth + inner, artHeight + inner);
    context.strokeStyle = accent;
    context.lineWidth = 2;
    strokeRect(context, artX - inner - 1, artY - inner - 1, artWidth + (inner + 1) * 2, artHeight + (inner + 1) * 2);
  } else {
    context.strokeStyle = shade(main, -38);
    context.lineWidth = 3;
    strokeRect(context, artX - 2, artY - 2, artWidth + 4, artHeight + 4);
    context.strokeStyle = shade(main, 38);
    context.lineWidth = 2;
    strokeRect(context, artX - 6, artY - 6, artWidth + 12, artHeight + 12);
  }
  context.restore();
}

export function drawWhiteboardFrame(context, frame, width, height) {
  const layout = frameLayout(frame);
  context.save();
  context.clearRect(0, 0, width, height);
  // The destination canvas may be displayed at CSS size; map frame pixels onto it.
  context.scale(width / layout.width, height / layout.height);
  drawOuter(context, layout, layout.frame.main, layout.frame.accent);
  drawMatte(context, layout);
  drawInner(context, layout, layout.frame.main, layout.frame.accent);
  context.restore();
  return layout;
}
