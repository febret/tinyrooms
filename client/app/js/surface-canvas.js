export const SIGN_STYLE_IDS = Object.freeze(["wood", "chalk", "brass", "paper", "neon"]);
export const SIGN_WIDTH = 1024;
export const SIGN_HEIGHT = 512;
export const WHITEBOARD_WIDTH = 1024;
export const WHITEBOARD_HEIGHT = 640;

const SIGN_PALETTES = Object.freeze({
  wood: { board: "#8a5a33", border: "#5c3a20", ink: "#f8ecd2", plaque: "#a66f40", font: '700 76px Georgia, serif' },
  chalk: { board: "#21362f", border: "#59452f", ink: "#eef7ee", plaque: "#2b463d", font: '700 76px "Trebuchet MS", sans-serif' },
  brass: { board: "#b08d57", border: "#6b4f24", ink: "#2a2115", plaque: "#c7a66d", font: '700 72px Georgia, serif' },
  paper: { board: "#efe6cf", border: "#b59b6a", ink: "#2b3340", plaque: "#f7f0dd", font: '700 72px "Segoe UI", sans-serif' },
  neon: { board: "#15121f", border: "#2e2945", ink: "#54f2ff", plaque: "#1d1930", font: '700 76px "Segoe UI", sans-serif' },
});

export function renderSignCanvas(surface, styleId = "wood") {
  const style = SIGN_PALETTES[styleId] || SIGN_PALETTES.wood;
  const canvas = document.createElement("canvas");
  canvas.width = SIGN_WIDTH;
  canvas.height = SIGN_HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) return canvas;
  context.fillStyle = style.board;
  context.fillRect(0, 0, SIGN_WIDTH, SIGN_HEIGHT);
  drawSignTexture(context, styleId, style);
  context.strokeStyle = style.border;
  context.lineWidth = 28;
  context.strokeRect(14, 14, SIGN_WIDTH - 28, SIGN_HEIGHT - 28);
  const text = typeof surface?.text === "string" ? surface.text : "New sign";
  context.fillStyle = style.ink;
  context.font = style.font;
  context.textAlign = "center";
  context.textBaseline = "middle";
  if (styleId === "neon") {
    context.shadowColor = style.ink;
    context.shadowBlur = 22;
  }
  const lines = wrapLines(context, text, SIGN_WIDTH - 160, 8);
  const lineHeight = 92;
  const startY = SIGN_HEIGHT / 2 - ((lines.length - 1) * lineHeight) / 2;
  lines.forEach((line, index) => {
    context.fillText(line, SIGN_WIDTH / 2, startY + index * lineHeight, SIGN_WIDTH - 160);
  });
  context.shadowBlur = 0;
  return canvas;
}

function drawSignTexture(context, styleId, style) {
  if (styleId === "wood") {
    for (let x = 0; x < SIGN_WIDTH; x += 96) {
      context.fillStyle = x % 192 === 0 ? "#8e5d36" : "#83552f";
      context.fillRect(x, 0, 92, SIGN_HEIGHT);
    }
    context.strokeStyle = "rgba(60, 35, 17, 0.35)";
    context.lineWidth = 3;
    for (let x = 96; x < SIGN_WIDTH; x += 96) {
      context.beginPath();
      context.moveTo(x, 0);
      context.lineTo(x, SIGN_HEIGHT);
      context.stroke();
    }
    context.fillStyle = "rgba(255, 235, 200, 0.08)";
    context.fillRect(0, SIGN_HEIGHT * 0.12, SIGN_WIDTH, SIGN_HEIGHT * 0.5);
  } else if (styleId === "chalk") {
    const gradient = context.createLinearGradient(0, 0, SIGN_WIDTH, SIGN_HEIGHT);
    gradient.addColorStop(0, "#1c2f29");
    gradient.addColorStop(1, "#263f36");
    context.fillStyle = gradient;
    context.fillRect(0, 0, SIGN_WIDTH, SIGN_HEIGHT);
    context.fillStyle = "rgba(255, 255, 255, 0.045)";
    for (let index = 0; index < 90; index += 1) {
      context.beginPath();
      context.arc((index * 137) % SIGN_WIDTH, (index * 83) % SIGN_HEIGHT, 1.5, 0, Math.PI * 2);
      context.fill();
    }
  } else if (styleId === "brass") {
    const gradient = context.createLinearGradient(0, 0, 0, SIGN_HEIGHT);
    gradient.addColorStop(0, "#c5a56f");
    gradient.addColorStop(0.45, style.board);
    gradient.addColorStop(1, "#92713f");
    context.fillStyle = gradient;
    context.fillRect(0, 0, SIGN_WIDTH, SIGN_HEIGHT);
    context.strokeStyle = "rgba(90, 65, 25, 0.35)";
    context.lineWidth = 8;
    context.strokeRect(52, 52, SIGN_WIDTH - 104, SIGN_HEIGHT - 104);
  } else if (styleId === "paper") {
    context.fillStyle = "#f4ecd9";
    context.fillRect(0, 0, SIGN_WIDTH, SIGN_HEIGHT);
    context.strokeStyle = "rgba(125, 150, 175, 0.22)";
    context.lineWidth = 2;
    for (let y = 96; y < SIGN_HEIGHT; y += 64) {
      context.beginPath();
      context.moveTo(70, y);
      context.lineTo(SIGN_WIDTH - 70, y);
      context.stroke();
    }
  } else if (styleId === "neon") {
    context.fillStyle = "#0d0b15";
    context.fillRect(0, 0, SIGN_WIDTH, SIGN_HEIGHT);
    context.strokeStyle = "rgba(84, 242, 255, 0.35)";
    context.lineWidth = 10;
    context.strokeRect(48, 48, SIGN_WIDTH - 96, SIGN_HEIGHT - 96);
  }
  context.fillStyle = style.plaque;
  context.globalAlpha = 0.16;
  context.fillRect(40, 40, SIGN_WIDTH - 80, SIGN_HEIGHT - 80);
  context.globalAlpha = 1;
}

export function renderWhiteboardCanvas(surface) {
  const canvas = document.createElement("canvas");
  canvas.width = WHITEBOARD_WIDTH;
  canvas.height = WHITEBOARD_HEIGHT;
  const context = canvas.getContext("2d");
  if (!context) return canvas;
  drawWhiteboard(context, surface);
  return canvas;
}

/** Draw a validated whiteboard surface into any 2D context at its canonical size. */
export function drawWhiteboard(context, surface) {
  context.fillStyle = "#fbfbf7";
  context.fillRect(0, 0, WHITEBOARD_WIDTH, WHITEBOARD_HEIGHT);
  context.strokeStyle = "#d9ded8";
  context.lineWidth = 8;
  context.strokeRect(4, 4, WHITEBOARD_WIDTH - 8, WHITEBOARD_HEIGHT - 8);
  const strokes = Array.isArray(surface?.strokes) ? surface.strokes : [];
  for (const stroke of strokes) {
    const points = Array.isArray(stroke?.points) ? stroke.points : [];
    if (!points.length) continue;
    context.strokeStyle = validColor(stroke?.color, "#1f2933");
    context.lineWidth = clampNumber(stroke?.width, 1, 40, 6);
    context.lineCap = "round";
    context.lineJoin = "round";
    context.beginPath();
    points.forEach((point, index) => {
      const x = clampNumber(point?.[0], 0, WHITEBOARD_WIDTH, 0);
      const y = clampNumber(point?.[1], 0, WHITEBOARD_HEIGHT, 0);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    if (points.length === 1) {
      const point = points[0];
      context.arc(
        clampNumber(point?.[0], 0, WHITEBOARD_WIDTH, 0),
        clampNumber(point?.[1], 0, WHITEBOARD_HEIGHT, 0),
        context.lineWidth / 2,
        0,
        Math.PI * 2,
      );
      context.fillStyle = context.strokeStyle;
      context.fill();
    } else {
      context.stroke();
    }
  }
  const texts = Array.isArray(surface?.texts) ? surface.texts : [];
  for (const item of texts) {
    const text = typeof item?.text === "string" ? item.text : "";
    if (!text) continue;
    const size = clampNumber(item?.size, 12, 120, 48);
    context.fillStyle = validColor(item?.color, "#1f2933");
    context.font = `600 ${size}px "Trebuchet MS", sans-serif`;
    context.textAlign = "left";
    context.textBaseline = "top";
    context.fillText(
      text,
      clampNumber(item?.x, 0, WHITEBOARD_WIDTH, 0),
      clampNumber(item?.y, 0, WHITEBOARD_HEIGHT, 0),
      WHITEBOARD_WIDTH,
    );
  }
}

/** Wrap text to a pixel width while preserving explicit newlines and a line cap. */
export function wrapLines(context, text, maxWidth, maxLines = 8) {
  const lines = [];
  for (const paragraph of String(text || "").split("\n")) {
    const words = paragraph.split(/\s+/).filter(Boolean);
    if (!words.length) {
      lines.push("");
      continue;
    }
    let line = words.shift();
    for (const word of words) {
      const candidate = `${line} ${word}`;
      if (context.measureText(candidate).width <= maxWidth) {
        line = candidate;
      } else {
        lines.push(line);
        line = word;
      }
      if (lines.length >= maxLines) break;
    }
    if (lines.length >= maxLines) break;
    lines.push(line);
  }
  return lines.slice(0, maxLines);
}

export function validColor(value, fallback) {
  return typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) ? value : fallback;
}

export function clampNumber(value, minimum, maximum, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(maximum, Math.max(minimum, number));
}
