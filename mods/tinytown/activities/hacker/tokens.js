// Vector token painters used as the `sprite` for the reused jobs minigames.
// Each painter draws a centred phosphor glyph inside the token footprint.

const TAU = Math.PI * 2;

export function tokenPainter(kind, palette) {
  const phosphor = palette?.phosphor || "#4bff7e";
  const accent = palette?.accent || "#b6ffc9";
  const ink = palette?.ink || "#03110a";

  function frame(ctx, size, draw) {
    ctx.save();
    const radius = size * 0.4;
    ctx.fillStyle = ink;
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, TAU);
    ctx.fill();
    ctx.strokeStyle = phosphor;
    ctx.lineWidth = Math.max(1.4, size * 0.035);
    ctx.shadowColor = phosphor;
    ctx.shadowBlur = size * 0.16;
    ctx.beginPath();
    ctx.arc(0, 0, radius, 0, TAU);
    ctx.stroke();
    ctx.shadowBlur = 0;
    draw(ctx, size * 0.56);
    ctx.restore();
  }

  return {
    kind,
    paint(ctx, size) {
      frame(ctx, size, (inner, scale) => {
        ctx.strokeStyle = accent;
        ctx.fillStyle = accent;
        ctx.lineWidth = Math.max(1.2, scale * 0.08);
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        if (kind === "database") {
          for (let index = 0; index < 3; index += 1) {
            ctx.beginPath();
            ctx.ellipse(0, -scale * 0.5 + index * scale * 0.5, scale * 0.72, scale * 0.22, 0, 0, TAU);
            ctx.stroke();
          }
        } else if (kind === "mail") {
          ctx.strokeRect(-scale * 0.8, -scale * 0.5, scale * 1.6, scale);
          ctx.beginPath();
          ctx.moveTo(-scale * 0.8, -scale * 0.5);
          ctx.lineTo(0, scale * 0.08);
          ctx.lineTo(scale * 0.8, -scale * 0.5);
          ctx.stroke();
        } else if (kind === "maintenance") {
          for (let index = 0; index < 8; index += 1) {
            const angle = (index / 8) * TAU;
            ctx.beginPath();
            ctx.moveTo(Math.cos(angle) * scale * 0.55, Math.sin(angle) * scale * 0.55);
            ctx.lineTo(Math.cos(angle) * scale * 0.9, Math.sin(angle) * scale * 0.9);
            ctx.stroke();
          }
          ctx.beginPath();
          ctx.arc(0, 0, scale * 0.5, 0, TAU);
          ctx.stroke();
          ctx.beginPath();
          ctx.arc(0, 0, scale * 0.16, 0, TAU);
          ctx.fill();
        } else if (kind === "legacy") {
          ctx.strokeRect(-scale * 0.85, -scale * 0.65, scale * 1.7, scale * 1.2);
          ctx.beginPath();
          ctx.moveTo(-scale * 0.3, scale * 0.55);
          ctx.lineTo(scale * 0.3, scale * 0.55);
          ctx.stroke();
          ctx.fillRect(-scale * 0.55, -scale * 0.4, scale * 0.5, scale * 0.16);
        } else if (kind === "core") {
          ctx.strokeRect(-scale * 0.6, -scale * 0.85, scale * 1.2, scale * 1.7);
          for (let index = 0; index < 3; index += 1) {
            ctx.strokeRect(-scale * 0.42, -scale * 0.6 + index * scale * 0.52, scale * 0.84, scale * 0.28);
          }
        } else {
          ctx.beginPath();
          ctx.moveTo(0, -scale * 0.9);
          ctx.lineTo(scale * 0.78, -scale * 0.35);
          ctx.lineTo(scale * 0.78, scale * 0.42);
          ctx.lineTo(0, scale * 0.9);
          ctx.lineTo(-scale * 0.78, scale * 0.42);
          ctx.lineTo(-scale * 0.78, -scale * 0.35);
          ctx.closePath();
          ctx.stroke();
          ctx.beginPath();
          ctx.moveTo(0, -scale * 0.4);
          ctx.lineTo(scale * 0.3, 0);
          ctx.lineTo(0, scale * 0.42);
          ctx.lineTo(-scale * 0.3, 0);
          ctx.closePath();
          ctx.stroke();
        }
      });
    },
  };
}
