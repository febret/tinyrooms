// Canvas painter for the Job Office scene model.

import { clamp, drawSprite, imageReady } from "../minigames/core.js";
import { pileRows, pileSlot } from "./model.js";

const TAU = Math.PI * 2;
const INK = "#29251f";
const CREAM = "#fff8e8";
const TONES = {
  good: "#3f7d5d",
  win: "#3f7d5d",
  bad: "#a33a2e",
  lose: "#a33a2e",
  intro: "#d7795c",
  ready: "#d7795c",
  go: "#d7795c",
};
const FONT = "'Archivo', 'Segoe UI', sans-serif";

function drawBackdrop(ctx, model, assets, w, h) {
  const art = assets.art;
  if (imageReady(art)) {
    const drift = model.reducedMotion ? 0 : Math.sin(model.time * 0.12);
    const zoom = model.reducedMotion ? 1.02 : 1.05 + 0.025 * Math.sin(model.time * 0.09);
    const scale = Math.max(w / art.naturalWidth, h / art.naturalHeight) * zoom;
    const dw = art.naturalWidth * scale;
    const dh = art.naturalHeight * scale;
    const slackX = Math.max(0, dw - w);
    ctx.drawImage(art, -slackX * (0.5 + drift * 0.3), (h - dh) * 0.6, dw, dh);
  } else {
    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, assets.accent || "#d7795c");
    gradient.addColorStop(1, "#2a211a");
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);
  }
  const vignette = ctx.createRadialGradient(w / 2, h * 0.45, h * 0.25, w / 2, h * 0.5, Math.max(w, h) * 0.75);
  vignette.addColorStop(0, "rgba(14, 10, 6, 0)");
  vignette.addColorStop(1, "rgba(14, 10, 6, 0.5)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, w, h);
  const floor = ctx.createLinearGradient(0, h - model.layout.pad * 2.4, 0, h);
  floor.addColorStop(0, "rgba(14, 10, 6, 0)");
  floor.addColorStop(1, "rgba(14, 10, 6, 0.62)");
  ctx.fillStyle = floor;
  ctx.fillRect(0, h - model.layout.pad * 2.4, w, model.layout.pad * 2.4);
}

function leadCenter(model) {
  const lead = model.figures.find(figure => figure.id === model.leadId);
  if (!lead) return { x: model.layout.leadX, y: model.layout.groundY - model.layout.leadH * 0.5, radius: model.layout.leadH * 0.8 };
  return { x: lead.x, y: lead.y - lead.h * 0.5, radius: lead.h * 0.85 };
}

function drawGlow(ctx, model) {
  const center = leadCenter(model);
  if (model.phase === "win") {
    const fade = clamp(model.phaseTime / 0.4, 0, 1);
    ctx.save();
    ctx.translate(center.x, center.y);
    ctx.rotate(model.reducedMotion ? 0 : model.time * 0.35);
    ctx.fillStyle = `rgba(255, 212, 121, ${0.2 * fade})`;
    const rays = 12;
    for (let index = 0; index < rays; index += 1) {
      const angle = (index / rays) * TAU;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.arc(0, 0, center.radius * 1.5, angle, angle + TAU / rays / 2);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();
  }
  const age = model.flash.age;
  if (age < 0.5 && model.flash.tone) {
    const alpha = (1 - age / 0.5) * (model.flash.tone === "good" ? 0.34 : 0.3);
    const gradient = ctx.createRadialGradient(center.x, center.y, 4, center.x, center.y, center.radius * 1.3);
    const color = model.flash.tone === "good" ? "255, 212, 121" : "255, 96, 72";
    gradient.addColorStop(0, `rgba(${color}, ${alpha})`);
    gradient.addColorStop(1, `rgba(${color}, 0)`);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, model.layout.w, model.layout.h);
  }
}

function drawToken(ctx, sprite, x, y, size, options = {}) {
  drawSprite(ctx, sprite, x, y, size, { fallback: 0.92, outline: 0.07, ...options });
}

function drawPile(ctx, model, assets) {
  const layout = model.layout;
  const size = layout.tokenSize;
  for (let index = 0; index < Math.min(model.pile, 10); index += 1) {
    const slot = pileSlot(layout, index);
    const pop = index === model.pile - 1 ? 1 + model.pilePulse * 0.28 : 1;
    ctx.fillStyle = "rgba(14, 10, 6, 0.3)";
    ctx.beginPath();
    ctx.ellipse(slot.x, slot.y + size * 0.46, size * 0.4, size * 0.1, 0, 0, TAU);
    ctx.fill();
    drawToken(ctx, assets.sprite, slot.x, slot.y, size * pop);
  }
  const rows = pileRows(Math.min(model.pile, 10));
  const lose = model.phase === "lose";
  const win = model.phase === "win";
  const base = layout.emblemSize;
  const bob = model.reducedMotion ? 0 : Math.sin(model.time * 2.4) * 3;
  const restY = layout.groundY - rows * size * 0.88 - base * 0.7 - size * 0.4;
  const fallY = layout.groundY - base * 0.4;
  const y = (lose ? restY + (fallY - restY) * model.emblemFall : restY) + (lose ? 0 : bob);
  const growth = (win ? 1.3 : 1) * (1 + Math.min(model.pile, 10) * 0.015);
  const emblem = base * growth;
  const x = layout.pileX;
  const required = Math.max(1, model.challenge.required);
  const progress = model.phase === "pick" ? 0 : clamp(model.hits / required, 0, 1);
  if (!lose) {
    const halo = ctx.createRadialGradient(x, y, emblem * 0.2, x, y, emblem * 0.95);
    halo.addColorStop(0, `rgba(255, 212, 121, ${0.35 + progress * 0.3})`);
    halo.addColorStop(1, "rgba(255, 212, 121, 0)");
    ctx.fillStyle = halo;
    ctx.beginPath();
    ctx.arc(x, y, emblem * 0.95, 0, TAU);
    ctx.fill();
  }
  drawToken(ctx, assets.sprite, x, y, emblem, {
    alpha: lose ? 0.7 : 1,
    rotation: lose ? 0.6 * model.emblemFall : model.reducedMotion || !win ? 0 : Math.sin(model.time * 5) * 0.12,
    tint: lose ? "rgba(70, 60, 55, 0.45)" : "",
  });
  if (model.phase !== "pick" && model.phase !== "ready") {
    ctx.lineCap = "round";
    ctx.lineWidth = Math.max(3, emblem * 0.07);
    ctx.strokeStyle = "rgba(255, 248, 232, 0.28)";
    ctx.beginPath();
    ctx.arc(x, y, emblem * 0.58, 0, TAU);
    ctx.stroke();
    ctx.strokeStyle = model.secured || win ? "#7fe0a4" : "#ffd479";
    ctx.beginPath();
    ctx.arc(x, y, emblem * 0.58, -Math.PI / 2, -Math.PI / 2 + TAU * progress);
    ctx.stroke();
  }
}

function drawFlights(ctx, model, assets) {
  const size = model.layout.tokenSize * 1.25;
  for (const flight of model.flights) {
    const unit = clamp(flight.t / flight.dur, 0, 1);
    const eased = 1 - (1 - unit) * (1 - unit);
    const arc = Math.sin(unit * Math.PI) * model.layout.h * (flight.kind === "hit" ? 0.2 : 0.12);
    const x = flight.from.x + (flight.to.x - flight.from.x) * eased;
    const y = flight.from.y + (flight.to.y - flight.from.y) * unit * unit - arc;
    if (flight.kind === "hit") {
      for (let trail = 1; trail <= 3; trail += 1) {
        const back = Math.max(0, unit - trail * 0.06);
        const be = 1 - (1 - back) * (1 - back);
        const tx = flight.from.x + (flight.to.x - flight.from.x) * be;
        const ty = flight.from.y + (flight.to.y - flight.from.y) * back * back - Math.sin(back * Math.PI) * model.layout.h * 0.2;
        drawToken(ctx, assets.sprite, tx, ty, size * (1 - trail * 0.18), { alpha: 0.22 / trail });
      }
    }
    drawToken(ctx, assets.sprite, x, y, size, {
      rotation: unit * (flight.kind === "hit" ? 4 : -5),
      tint: flight.kind === "miss" ? "rgba(255, 90, 70, 0.35)" : "",
    });
  }
  for (const item of model.dropped) {
    const fade = clamp(1 - item.age / item.ttl, 0, 1);
    const bounce = Math.abs(Math.sin(item.age * 9)) * Math.max(0, 0.45 - item.age) * model.layout.tokenSize;
    drawToken(ctx, assets.sprite, item.x + item.age * 16, item.y - bounce, model.layout.tokenSize, {
      alpha: fade * 0.85,
      rotation: item.spin + item.age * 3,
      tint: "rgba(120, 90, 80, 0.5)",
    });
  }
}

function drawPlaceholder(ctx, figure, w) {
  ctx.fillStyle = "#f4e7c8";
  ctx.strokeStyle = "#3e2c1e";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.ellipse(0, -figure.h * 0.5, w * 0.45, figure.h * 0.45, 0, 0, TAU);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = INK;
  ctx.font = `700 ${Math.max(14, figure.h * 0.3)}px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText((figure.name || "?").slice(0, 1).toUpperCase(), 0, -figure.h * 0.5);
}

function drawFigure(ctx, model, assets, figure) {
  if (figure.h < 4) return;
  const pose = model.pose(figure);
  const w = model.figureWidth(figure);
  const layout = model.layout;
  ctx.fillStyle = `rgba(10, 7, 4, ${0.34 * pose.alpha})`;
  ctx.beginPath();
  ctx.ellipse(figure.x, figure.y + 2, w * 0.42, Math.max(3, figure.h * 0.045), 0, 0, TAU);
  ctx.fill();
  ctx.save();
  ctx.globalAlpha = pose.alpha;
  ctx.translate(figure.x + pose.dx, figure.y + pose.dy);
  ctx.rotate(pose.rot);
  ctx.scale(pose.sx, pose.sy);
  const image = assets.figures.get(figure.id);
  if (imageReady(image)) {
    ctx.shadowColor = "rgba(255, 248, 232, 0.55)";
    ctx.shadowBlur = Math.max(5, figure.h * 0.04);
    ctx.drawImage(image, -w / 2, -figure.h, w, figure.h);
  } else {
    drawPlaceholder(ctx, figure, w);
  }
  ctx.restore();
  if (figure.role === "done") {
    const radius = clamp(figure.h * 0.1, 7, 12);
    const cx = figure.x + w * 0.28;
    const cy = figure.y - figure.h * 0.94 + pose.dy;
    ctx.fillStyle = "#3f7d5d";
    ctx.strokeStyle = CREAM;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, TAU);
    ctx.fill();
    ctx.stroke();
    ctx.strokeStyle = CREAM;
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    ctx.moveTo(cx - radius * 0.45, cy);
    ctx.lineTo(cx - radius * 0.1, cy + radius * 0.4);
    ctx.lineTo(cx + radius * 0.5, cy - radius * 0.35);
    ctx.stroke();
  }
  if (figure.role === "lead" || figure.role === "lineup") {
    const fontSize = clamp(layout.h * 0.036, 10, 14);
    drawPlate(ctx, figure.name, figure.x, figure.y + layout.pad * 0.52, fontSize, figure.role === "lead");
  }
}

function drawPlate(ctx, text, x, y, fontSize, emphasized) {
  ctx.font = `700 ${fontSize}px ${FONT}`;
  const label = String(text || "").toUpperCase();
  const width = ctx.measureText(label).width + fontSize * 1.6;
  const height = fontSize * 1.65;
  ctx.fillStyle = emphasized ? "rgba(215, 121, 92, 0.96)" : "rgba(20, 16, 12, 0.78)";
  ctx.beginPath();
  ctx.roundRect(x - width / 2, y - height / 2, width, height, height / 2);
  ctx.fill();
  ctx.fillStyle = emphasized ? "#2a150e" : CREAM;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y + 0.5);
}

function drawCloud(ctx, model) {
  const { head } = model.anchors();
  const x = head.x - 6;
  const y = head.y - 12 + (model.reducedMotion ? 0 : Math.sin(model.time * 2) * 2);
  const size = clamp(model.layout.h * 0.1, 18, 34);
  const grow = clamp(model.phaseTime / 0.35, 0, 1);
  ctx.save();
  ctx.globalAlpha = grow * 0.95;
  ctx.fillStyle = "#6c7480";
  ctx.beginPath();
  ctx.arc(x - size * 0.8, y, size * 0.6, 0, TAU);
  ctx.arc(x - size * 0.2, y - size * 0.4, size * 0.75, 0, TAU);
  ctx.arc(x + size * 0.55, y - size * 0.1, size * 0.65, 0, TAU);
  ctx.arc(x + size * 1.1, y + size * 0.05, size * 0.45, 0, TAU);
  ctx.fill();
  ctx.restore();
}

function drawParticles(ctx, model) {
  for (const particle of model.particles) {
    const life = particle.age / particle.ttl;
    const alpha = clamp(1 - life * life, 0, 1);
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.translate(particle.x, particle.y);
    ctx.rotate(particle.rot);
    ctx.fillStyle = particle.color;
    if (particle.kind === "spark") {
      const s = particle.size * (1 - life * 0.4);
      ctx.beginPath();
      ctx.moveTo(0, -s);
      ctx.quadraticCurveTo(s * 0.2, -s * 0.2, s, 0);
      ctx.quadraticCurveTo(s * 0.2, s * 0.2, 0, s);
      ctx.quadraticCurveTo(-s * 0.2, s * 0.2, -s, 0);
      ctx.quadraticCurveTo(-s * 0.2, -s * 0.2, 0, -s);
      ctx.fill();
    } else if (particle.kind === "confetti") {
      ctx.fillRect(-particle.size / 2, -particle.size / 4, particle.size, particle.size / 2);
    } else if (particle.kind === "zzz") {
      ctx.rotate(-particle.rot);
      ctx.font = `800 ${particle.size * (0.8 + life * 0.6)}px ${FONT}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("z", 0, 0);
    } else if (particle.kind === "drop") {
      ctx.rotate(-particle.rot);
      ctx.beginPath();
      ctx.ellipse(0, 0, particle.size * 0.45, particle.size * 0.75, 0, 0, TAU);
      ctx.fill();
    } else {
      ctx.beginPath();
      ctx.arc(0, 0, particle.size * (0.6 + life), 0, TAU);
      ctx.fill();
    }
    ctx.restore();
  }
}

function drawFloaters(ctx, model) {
  const size = clamp(model.layout.h * 0.058, 14, 22);
  ctx.font = `800 ${size}px ${FONT}`;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.lineJoin = "round";
  for (const item of model.floaters) {
    const life = item.age / item.ttl;
    ctx.globalAlpha = clamp(1.6 - life * 1.6, 0, 1);
    ctx.lineWidth = 4;
    ctx.strokeStyle = "rgba(14, 10, 6, 0.85)";
    ctx.strokeText(item.text, item.x, item.y);
    ctx.fillStyle = item.tone === "good" ? "#9cf0bd" : "#ff9f8a";
    ctx.fillText(item.text, item.x, item.y);
  }
  ctx.globalAlpha = 1;
}

function wrapLines(ctx, text, maxWidth) {
  const words = String(text).split(/\s+/);
  const lines = [];
  let current = "";
  for (const word of words) {
    const next = current ? `${current} ${word}` : word;
    if (current && ctx.measureText(next).width > maxWidth) {
      lines.push(current);
      current = word;
    } else {
      current = next;
    }
  }
  if (current) lines.push(current);
  return lines;
}

function drawBubble(ctx, model) {
  const bubble = model.bubble;
  if (!bubble) return;
  const layout = model.layout;
  const { head } = model.anchors();
  const fontSize = clamp(layout.h * 0.05, 12, 17);
  ctx.font = `700 ${fontSize}px ${FONT}`;
  const maxWidth = Math.min(layout.w * 0.52, 230);
  const lines = wrapLines(ctx, bubble.text, maxWidth);
  const textWidth = Math.max(...lines.map(entry => ctx.measureText(entry).width));
  const padX = fontSize * 0.85;
  const padY = fontSize * 0.6;
  const lineHeight = fontSize * 1.25;
  const width = textWidth + padX * 2;
  const height = lines.length * lineHeight + padY * 2;
  const lift = model.phase === "lose" ? clamp(layout.h * 0.12, 24, 42) : 0;
  const left = clamp(head.x + 6, 6, layout.w - width - 6);
  const top = Math.max(layout.h > 240 ? 44 : 38, head.y - 14 - lift - height);
  const pop = model.reducedMotion ? 1 : clamp(bubble.age / 0.14, 0.4, 1);
  const fade = clamp((bubble.ttl - bubble.age) / 0.3, 0, 1);
  ctx.save();
  ctx.globalAlpha = fade;
  ctx.translate(left + width * 0.2, top + height);
  ctx.scale(pop, pop);
  ctx.translate(-(left + width * 0.2), -(top + height));
  const tone = TONES[bubble.tone] || INK;
  ctx.fillStyle = "rgba(255, 250, 238, 0.97)";
  ctx.strokeStyle = tone;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  ctx.roundRect(left, top, width, height, Math.min(14, height / 2));
  ctx.fill();
  ctx.stroke();
  const tailX = clamp(head.x, left + 12, left + width - 12);
  ctx.beginPath();
  ctx.moveTo(tailX - 7, top + height - 1);
  ctx.lineTo(tailX, top + height + 9);
  ctx.lineTo(tailX + 7, top + height - 1);
  ctx.closePath();
  ctx.fillStyle = "rgba(255, 250, 238, 0.97)";
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "rgba(255, 250, 238, 0.97)";
  ctx.fillRect(tailX - 6, top + height - 3, 12, 3);
  ctx.fillStyle = INK;
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  lines.forEach((entry, index) => {
    ctx.fillText(entry, left + padX, top + padY + lineHeight * (index + 0.5));
  });
  ctx.restore();
}

export function drawScene(ctx, model, assets, view) {
  const { width: w, height: h, dpr } = view;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  ctx.save();
  if (model.shake > 0) {
    ctx.translate(Math.sin(model.time * 70) * 6 * model.shake, Math.cos(model.time * 53) * 3 * model.shake);
  }
  drawBackdrop(ctx, model, assets, w, h);
  drawGlow(ctx, model);
  drawPile(ctx, model, assets);
  drawFlights(ctx, model, assets);
  const behind = model.figures.filter(figure => figure.role === "bench" || figure.role === "done");
  const front = model.figures.filter(figure => figure.role === "lead" || figure.role === "lineup");
  for (const figure of behind) drawFigure(ctx, model, assets, figure);
  for (const figure of front) drawFigure(ctx, model, assets, figure);
  if (model.phase === "lose") drawCloud(ctx, model);
  drawParticles(ctx, model);
  drawFloaters(ctx, model);
  drawBubble(ctx, model);
  ctx.restore();
}
