// Per-job look for the Job Office minigames.
//
// A skin turns one theme (palette, target pattern, edge style, HUD pip, frame
// corners, marker, font) into drawing helpers. Game rules never read a skin, so
// every job keeps the same six game structures with a different costume.

import { imageReady } from "./core.js";
import { THEMES } from "./themes.js";

export const DEFAULT_THEME = {
  good: "#7fe0a4",
  soft: "rgba(127, 224, 164, 0.3)",
  deep: "#16382a",
  tint: "rgba(14, 10, 6, 0.62)",
  accent: "#ffd479",
  pattern: "hatch",
  edge: "dashed",
  pip: "circle",
  corner: "brackets",
  marker: "line",
  font: "ui",
};

export const PATTERNS = ["hatch", "stripes", "dots", "checker", "stars", "grid", "ledger", "bricks", "waves", "zigzag"];
export const EDGES = ["dashed", "solid", "double", "dotted", "bracket"];
export const PIPS = ["circle", "square", "diamond", "star", "hex", "heart", "triangle", "drop"];
export const CORNERS = ["brackets", "rivets", "tape", "stitch", "notch"];

const BAD = "#ff8a73";
const BAD_SOFT = "rgba(255, 138, 115, 0.34)";
const INK = "#fff8e8";
const TILE = 24;
const TAU = Math.PI * 2;

const FONTS = {
  display: "'Bodoni Moda', 'Times New Roman', serif",
  body: "'Newsreader', Georgia, serif",
  ui: "'Archivo', 'Segoe UI', sans-serif",
  mono: "ui-monospace, 'Cascadia Mono', Consolas, monospace",
};

export function themeFor(jobId) {
  return THEMES[jobId] || DEFAULT_THEME;
}

function drawTilePattern(ctx, kind, color) {
  const size = TILE;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2.4;
  ctx.lineCap = "round";
  ctx.beginPath();
  if (kind === "hatch") {
    ctx.moveTo(-2, size + 2);
    ctx.lineTo(size + 2, -2);
    ctx.moveTo(-2, size / 2 + 2);
    ctx.lineTo(size / 2 + 2, -2);
    ctx.moveTo(size / 2 - 2, size + 2);
    ctx.lineTo(size + 2, size / 2 - 2);
    ctx.stroke();
  } else if (kind === "stripes") {
    ctx.lineWidth = size * 0.28;
    ctx.moveTo(-2, size + 2);
    ctx.lineTo(size + 2, -2);
    ctx.stroke();
  } else if (kind === "dots") {
    ctx.arc(size / 4, size / 4, 2.6, 0, TAU);
    ctx.moveTo(size * 0.75 + 2.6, size * 0.75);
    ctx.arc(size * 0.75, size * 0.75, 2.6, 0, TAU);
    ctx.fill();
  } else if (kind === "checker") {
    ctx.rect(0, 0, size / 2, size / 2);
    ctx.rect(size / 2, size / 2, size / 2, size / 2);
    ctx.fill();
  } else if (kind === "stars") {
    const c = size / 2;
    ctx.moveTo(c, c - 7);
    ctx.quadraticCurveTo(c + 1.5, c - 1.5, c + 7, c);
    ctx.quadraticCurveTo(c + 1.5, c + 1.5, c, c + 7);
    ctx.quadraticCurveTo(c - 1.5, c + 1.5, c - 7, c);
    ctx.quadraticCurveTo(c - 1.5, c - 1.5, c, c - 7);
    ctx.fill();
  } else if (kind === "grid") {
    ctx.lineWidth = 1.4;
    ctx.moveTo(0, 0.7);
    ctx.lineTo(size, 0.7);
    ctx.moveTo(0.7, 0);
    ctx.lineTo(0.7, size);
    ctx.stroke();
  } else if (kind === "ledger") {
    ctx.lineWidth = 1.6;
    ctx.moveTo(0, size * 0.3);
    ctx.lineTo(size, size * 0.3);
    ctx.moveTo(0, size * 0.8);
    ctx.lineTo(size, size * 0.8);
    ctx.stroke();
  } else if (kind === "bricks") {
    ctx.lineWidth = 1.6;
    ctx.moveTo(0, 0.8);
    ctx.lineTo(size, 0.8);
    ctx.moveTo(0, size / 2);
    ctx.lineTo(size, size / 2);
    ctx.moveTo(size / 2, 0);
    ctx.lineTo(size / 2, size / 2);
    ctx.moveTo(0, size / 2);
    ctx.lineTo(0, size);
    ctx.moveTo(size, size / 2);
    ctx.lineTo(size, size);
    ctx.stroke();
  } else if (kind === "waves") {
    ctx.lineWidth = 2;
    ctx.moveTo(0, size * 0.35);
    ctx.bezierCurveTo(size * 0.25, size * 0.05, size * 0.75, size * 0.65, size, size * 0.35);
    ctx.moveTo(0, size * 0.85);
    ctx.bezierCurveTo(size * 0.25, size * 0.55, size * 0.75, size * 1.15, size, size * 0.85);
    ctx.stroke();
  } else {
    ctx.lineWidth = 2;
    ctx.moveTo(0, size * 0.75);
    ctx.lineTo(size * 0.25, size * 0.25);
    ctx.lineTo(size * 0.5, size * 0.75);
    ctx.lineTo(size * 0.75, size * 0.25);
    ctx.lineTo(size, size * 0.75);
    ctx.stroke();
  }
}

function pipPath(ctx, kind, x, y, r) {
  ctx.beginPath();
  if (kind === "square") {
    ctx.rect(x - r * 0.85, y - r * 0.85, r * 1.7, r * 1.7);
  } else if (kind === "diamond") {
    ctx.moveTo(x, y - r * 1.15);
    ctx.lineTo(x + r * 1.05, y);
    ctx.lineTo(x, y + r * 1.15);
    ctx.lineTo(x - r * 1.05, y);
    ctx.closePath();
  } else if (kind === "star") {
    for (let index = 0; index < 10; index += 1) {
      const radius = index % 2 ? r * 0.52 : r * 1.2;
      const angle = -Math.PI / 2 + (index * Math.PI) / 5;
      const px = x + Math.cos(angle) * radius;
      const py = y + Math.sin(angle) * radius;
      if (index) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
    }
    ctx.closePath();
  } else if (kind === "hex") {
    for (let index = 0; index < 6; index += 1) {
      const angle = (index * Math.PI) / 3;
      const px = x + Math.cos(angle) * r * 1.05;
      const py = y + Math.sin(angle) * r * 1.05;
      if (index) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
    }
    ctx.closePath();
  } else if (kind === "heart") {
    ctx.moveTo(x, y + r * 0.95);
    ctx.bezierCurveTo(x - r * 1.6, y - r * 0.1, x - r * 0.7, y - r * 1.1, x, y - r * 0.35);
    ctx.bezierCurveTo(x + r * 0.7, y - r * 1.1, x + r * 1.6, y - r * 0.1, x, y + r * 0.95);
    ctx.closePath();
  } else if (kind === "triangle") {
    ctx.moveTo(x, y - r * 1.05);
    ctx.lineTo(x + r * 1.1, y + r * 0.85);
    ctx.lineTo(x - r * 1.1, y + r * 0.85);
    ctx.closePath();
  } else if (kind === "drop") {
    ctx.moveTo(x, y - r * 1.25);
    ctx.bezierCurveTo(x + r * 1.2, y - r * 0.1, x + r * 1.05, y + r * 1.0, x, y + r * 1.0);
    ctx.bezierCurveTo(x - r * 1.05, y + r * 1.0, x - r * 1.2, y - r * 0.1, x, y - r * 1.25);
    ctx.closePath();
  } else {
    ctx.arc(x, y, r, 0, TAU);
  }
}

/** Build the drawing helpers for one theme. */
export function createSkin(theme = DEFAULT_THEME) {
  const look = { ...DEFAULT_THEME, ...theme };
  let patternFill = null;
  let patternBuilt = false;

  function fillStyle(ctx) {
    if (patternBuilt) return patternFill || look.soft;
    patternBuilt = true;
    if (typeof document === "undefined" || !ctx.createPattern) return look.soft;
    try {
      const scale = 2;
      const tile = document.createElement("canvas");
      tile.width = TILE * scale;
      tile.height = TILE * scale;
      const tileCtx = tile.getContext("2d");
      tileCtx.scale(scale, scale);
      tileCtx.fillStyle = look.soft;
      tileCtx.fillRect(0, 0, TILE, TILE);
      drawTilePattern(tileCtx, look.pattern, look.good);
      patternFill = ctx.createPattern(tile, "repeat");
      patternFill?.setTransform?.(new DOMMatrix().scale(1 / scale));
    } catch {
      patternFill = null;
    }
    return patternFill || look.soft;
  }

  function edgeStyle(ctx, trace, width, rect = null) {
    ctx.save();
    ctx.lineJoin = "round";
    ctx.lineCap = "butt";
    if (look.edge === "double") {
      trace(ctx);
      ctx.strokeStyle = look.deep;
      ctx.lineWidth = width * 3;
      ctx.stroke();
      trace(ctx);
      ctx.strokeStyle = look.good;
      ctx.lineWidth = width;
      ctx.stroke();
    } else if (look.edge === "bracket" && rect) {
      const arm = Math.min(rect.w, rect.h, 70) * 0.35;
      ctx.strokeStyle = look.good;
      ctx.lineWidth = width * 1.6;
      ctx.beginPath();
      for (const [cx, cy, dx, dy] of [
        [rect.x, rect.y, 1, 1],
        [rect.x + rect.w, rect.y, -1, 1],
        [rect.x, rect.y + rect.h, 1, -1],
        [rect.x + rect.w, rect.y + rect.h, -1, -1],
      ]) {
        ctx.moveTo(cx + dx * arm, cy);
        ctx.lineTo(cx, cy);
        ctx.lineTo(cx, cy + dy * arm);
      }
      ctx.stroke();
    } else {
      trace(ctx);
      ctx.strokeStyle = look.good;
      ctx.lineWidth = look.edge === "dotted" ? width * 1.5 : width;
      if (look.edge === "dashed") ctx.setLineDash([width * 3.5, width * 2.2]);
      else if (look.edge === "dotted") {
        ctx.lineCap = "round";
        ctx.setLineDash([0.01, width * 2.6]);
      } else if (look.edge === "bracket") ctx.setLineDash([width * 7, width * 5]);
      ctx.stroke();
    }
    ctx.restore();
  }

  const skin = {
    theme: look,
    good: look.good,
    soft: look.soft,
    deep: look.deep,
    accent: look.accent,
    bad: BAD,
    badSoft: BAD_SOFT,
    ink: INK,
    font(size, weight = 700) {
      return `${weight} ${size}px ${FONTS[look.font] || FONTS.ui}`;
    },
    fill(ctx) {
      return fillStyle(ctx);
    },
    fillRect(ctx, x, y, w, h) {
      ctx.save();
      ctx.fillStyle = fillStyle(ctx);
      ctx.fillRect(x, y, w, h);
      ctx.restore();
    },
    edgeRect(ctx, x, y, w, h, width = 3) {
      edgeStyle(ctx, c => {
        c.beginPath();
        c.rect(x, y, w, h);
      }, width, { x, y, w, h });
    },
    edgePath(ctx, trace, width = 3) {
      edgeStyle(ctx, trace, width);
    },
    pip(ctx, x, y, r, state) {
      ctx.save();
      pipPath(ctx, look.pip, x, y, r);
      ctx.lineWidth = 2.4;
      if (state === "hit") {
        ctx.fillStyle = look.good;
        ctx.fill();
      } else if (state === "miss") {
        ctx.fillStyle = BAD;
        ctx.fill();
      } else {
        ctx.strokeStyle = "rgba(255, 248, 232, 0.55)";
        ctx.stroke();
      }
      ctx.restore();
    },
    marker(ctx, x, y, size, angle = 0) {
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(angle);
      ctx.fillStyle = INK;
      ctx.beginPath();
      if (look.marker === "arrow") {
        ctx.moveTo(size, 0);
        ctx.lineTo(-size * 0.5, -size * 0.7);
        ctx.lineTo(-size * 0.2, 0);
        ctx.lineTo(-size * 0.5, size * 0.7);
      } else if (look.marker === "diamond") {
        ctx.moveTo(size, 0);
        ctx.lineTo(0, -size * 0.6);
        ctx.lineTo(-size, 0);
        ctx.lineTo(0, size * 0.6);
      } else {
        ctx.rect(-size, -size * 0.12, size * 2, size * 0.24);
      }
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    },
    /** Paint the baked arena (when loaded) under a dark themed tint. */
    arena(ctx, image, width, height) {
      if (imageReady(image)) {
        const scale = Math.max(width / image.naturalWidth, height / image.naturalHeight);
        const dw = image.naturalWidth * scale;
        const dh = image.naturalHeight * scale;
        ctx.drawImage(image, (width - dw) / 2, (height - dh) / 2, dw, dh);
      } else {
        ctx.fillStyle = look.deep;
        ctx.fillRect(0, 0, width, height);
      }
      ctx.fillStyle = look.tint;
      ctx.fillRect(0, 0, width, height);
      const gradient = ctx.createRadialGradient(width / 2, height / 2, height * 0.25, width / 2, height / 2, width * 0.62);
      gradient.addColorStop(0, "rgba(0, 0, 0, 0)");
      gradient.addColorStop(1, "rgba(0, 0, 0, 0.5)");
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, width, height);
    },
    frame(ctx, width, height) {
      const inset = 9;
      const arm = 26;
      ctx.save();
      ctx.strokeStyle = look.good;
      ctx.fillStyle = look.good;
      ctx.globalAlpha = 0.8;
      ctx.lineWidth = 3;
      ctx.lineCap = "round";
      const corners = [
        [inset, inset, 1, 1],
        [width - inset, inset, -1, 1],
        [inset, height - inset, 1, -1],
        [width - inset, height - inset, -1, -1],
      ];
      if (look.corner === "stitch") {
        ctx.setLineDash([7, 6]);
        ctx.lineWidth = 2;
        ctx.strokeRect(inset, inset, width - inset * 2, height - inset * 2);
      } else {
        for (const [x, y, dx, dy] of corners) {
          ctx.beginPath();
          if (look.corner === "rivets") {
            ctx.arc(x + dx * 5, y + dy * 5, 4, 0, TAU);
            ctx.fill();
            continue;
          }
          if (look.corner === "tape") {
            ctx.globalAlpha = 0.5;
            ctx.lineWidth = 11;
            ctx.lineCap = "butt";
            ctx.moveTo(x - dx * 6, y + dy * 24);
            ctx.lineTo(x + dx * 24, y - dy * 6);
            ctx.stroke();
            ctx.globalAlpha = 0.8;
            continue;
          }
          if (look.corner === "notch") {
            ctx.moveTo(x, y + dy * arm * 0.8);
            ctx.lineTo(x + dx * arm * 0.8, y);
            ctx.stroke();
            continue;
          }
          ctx.moveTo(x + dx * arm, y);
          ctx.lineTo(x, y);
          ctx.lineTo(x, y + dy * arm);
          ctx.stroke();
        }
      }
      ctx.restore();
    },
  };
  return skin;
}
