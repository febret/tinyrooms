// A phosphor costume for the Job Office minigames. Rules stay identical: this
// only changes the palette, the arena treatment, and the CRT overlay.

import { createSkin } from "../jobs/minigames/skin.js";

function hexToRgba(hex, alpha) {
  const value = String(hex || "").replace("#", "");
  const red = parseInt(value.slice(0, 2), 16) || 75;
  const green = parseInt(value.slice(2, 4), 16) || 255;
  const blue = parseInt(value.slice(4, 6), 16) || 126;
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

export function createHackSkin(palette = {}) {
  const phosphor = palette.phosphor || "#4bff7e";
  const accent = palette.accent || "#b6ffc9";
  const ink = palette.ink || "#03110a";
  const deep = palette.deep || "#0a2a16";
  const base = createSkin({
    good: phosphor,
    soft: hexToRgba(phosphor, 0.2),
    deep,
    tint: hexToRgba(ink, 0.72),
    accent,
    pattern: "grid",
    edge: "bracket",
    pip: "hex",
    corner: "brackets",
    marker: "line",
    font: "mono",
  });

  return {
    ...base,
    theme: base.theme,
    phosphor,
    accent,
    ink: accent,
    arena(ctx, image, width, height) {
      base.arena(ctx, image, width, height);
      ctx.save();
      ctx.fillStyle = hexToRgba(phosphor, 0.06);
      for (let y = 0; y < height; y += 3) {
        ctx.fillRect(0, y, width, 1);
      }
      ctx.restore();
    },
    frame(ctx, width, height) {
      base.frame(ctx, width, height);
      ctx.save();
      ctx.strokeStyle = hexToRgba(accent, 0.35);
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 6]);
      ctx.strokeRect(14, 14, width - 28, height - 28);
      ctx.restore();
    },
  };
}

export function drawCrtOverlay(ctx, { width, height, clock = 0, reducedMotion = false }) {
  ctx.save();
  ctx.fillStyle = "rgba(0, 0, 0, 0.16)";
  for (let y = 0; y < height; y += 3) {
    ctx.fillRect(0, y, width, 1);
  }
  const gradient = ctx.createRadialGradient(width / 2, height / 2, height * 0.32, width / 2, height / 2, width * 0.62);
  gradient.addColorStop(0, "rgba(0, 0, 0, 0)");
  gradient.addColorStop(1, "rgba(0, 0, 0, 0.35)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  if (!reducedMotion) {
    const bandY = (clock * 46) % (height + 80) - 40;
    ctx.fillStyle = "rgba(255, 255, 255, 0.03)";
    ctx.fillRect(0, bandY, width, 42);
    if (Math.sin(clock * 11) > 0.985) {
      ctx.fillStyle = "rgba(255, 255, 255, 0.05)";
      ctx.fillRect(0, 0, width, height);
    }
  }
  ctx.restore();
}
