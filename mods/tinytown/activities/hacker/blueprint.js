// Wireframe megacorp blueprint. Draws ten floors and lights the open one.

import { hexToRgba } from "./hacker-model.js";

export function createBlueprint({ canvas, reducedMotion = false }) {
  const ctx = canvas.getContext("2d");
  let corp = null;
  let lit = 1;
  let frame = 0;
  let last = 0;
  let clock = 0;
  let width = 1;
  let height = 1;

  function palette() {
    return {
      phosphor: corp?.palette?.phosphor || "#4bff7e",
      accent: corp?.palette?.accent || "#b6ffc9",
      ink: corp?.palette?.ink || "#03110a",
      deep: corp?.palette?.deep || "#0a2a16",
    };
  }

  function resize() {
    const bounds = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    width = Math.max(1, bounds.width);
    height = Math.max(1, bounds.height);
    const pixelWidth = Math.round(width * ratio);
    const pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) {
      canvas.width = pixelWidth;
      canvas.height = pixelHeight;
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function drawGrid(colours) {
    ctx.save();
    ctx.strokeStyle = hexToRgba(colours.deep, 0.7);
    ctx.lineWidth = 1;
    const step = 32;
    for (let x = 0; x < width; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y < height; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
    ctx.restore();
  }

  function draw() {
    resize();
    const colours = palette();
    ctx.clearRect(0, 0, width, height);
    drawGrid(colours);

    const floors = corp?.floors || [];
    const count = Math.max(floors.length, 10);
    const top = Math.max(104, height * 0.22);
    const bottom = height - Math.max(22, height * 0.07);
    const usable = Math.max(120, bottom - top);
    const floorHeight = usable / count;
    const bodyWidth = Math.min(Math.max(150, width * 0.46), 300);
    const left = Math.max(30, width * 0.12);
    const right = left + bodyWidth;
    const skew = Math.min(40, bodyWidth * 0.14);

    ctx.save();
    ctx.strokeStyle = hexToRgba(colours.phosphor, 0.35);
    ctx.setLineDash([4, 6]);
    ctx.beginPath();
    ctx.moveTo(left - 14, top);
    ctx.lineTo(left - 14, bottom + 12);
    ctx.moveTo(right + 14, top);
    ctx.lineTo(right + 14, bottom + 12);
    ctx.stroke();
    ctx.restore();

    floors.forEach((floor, index) => {
      const y = bottom - (index + 1) * floorHeight;
      const active = floor.level === lit;
      const available = floor.available && !floor.locked;
      const alpha = active ? 1 : available ? 0.6 : 0.3;
      const pulse = active && !reducedMotion ? 0.78 + 0.22 * Math.sin(clock * 3.2) : 1;

      ctx.save();
      ctx.globalAlpha = alpha * pulse;
      ctx.strokeStyle = active ? colours.phosphor : hexToRgba(colours.phosphor, available ? 0.7 : 0.42);
      ctx.fillStyle = active ? hexToRgba(colours.phosphor, 0.2) : hexToRgba(colours.deep, 0.5);
      ctx.lineWidth = active ? 3 : 1.2;

      ctx.beginPath();
      ctx.moveTo(left, y);
      ctx.lineTo(right, y);
      ctx.lineTo(right - skew, y + floorHeight * 0.22);
      ctx.lineTo(right - skew, y + floorHeight);
      ctx.lineTo(left - skew, y + floorHeight);
      ctx.lineTo(left, y + floorHeight * 0.22);
      ctx.closePath();
      if (active) ctx.fill();
      ctx.stroke();

      const windows = 6;
      const innerWidth = bodyWidth - skew - 36;
      const windowWidth = innerWidth / windows;
      ctx.fillStyle = active ? hexToRgba(colours.accent, 0.8) : hexToRgba(colours.phosphor, 0.22);
      for (let column = 0; column < windows; column += 1) {
        if (!active && (column + index) % 3 === 0) continue;
        const wx = left + 12 + column * windowWidth;
        const wy = y + floorHeight * 0.34;
        const ww = Math.max(4, windowWidth * 0.5);
        const wh = Math.max(2, floorHeight * 0.2);
        ctx.fillRect(wx, wy, ww, wh);
      }

      ctx.font = "600 9px ui-monospace, Consolas, monospace";
      ctx.fillStyle = hexToRgba(colours.accent, active ? 0.95 : 0.5);
      ctx.textAlign = "right";
      ctx.fillText(`F${String(floor.level).padStart(2, "0")}`, left - 10, y + floorHeight * 0.7);
      ctx.textAlign = "left";
      ctx.fillStyle = hexToRgba(colours.phosphor, active ? 0.95 : 0.5);
      const label = floor.title.toUpperCase();
      const room = Math.max(40, width - right - 18);
      let text = label;
      while (text.length > 4 && ctx.measureText(text).width > room) {
        text = text.slice(0, -2);
      }
      ctx.fillText(text, right + 8, y + floorHeight * 0.7);
      ctx.restore();
      if (active) {
        ctx.save();
        ctx.fillStyle = colours.phosphor;
        const blink = reducedMotion ? 1 : 0.4 + 0.6 * Math.abs(Math.sin(clock * 4));
        ctx.globalAlpha = blink;
        ctx.beginPath();
        ctx.moveTo(right - skew - 12, y + floorHeight / 2 - 5);
        ctx.lineTo(right - skew - 2, y + floorHeight / 2);
        ctx.lineTo(right - skew - 12, y + floorHeight / 2 + 5);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
      }
    });

    ctx.save();
    ctx.strokeStyle = hexToRgba(colours.accent, 0.55);
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(left - skew, bottom + 6);
    ctx.lineTo(right - skew, bottom + 6);
    ctx.moveTo(left, bottom + 6);
    ctx.lineTo(left, top - 8);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(left - 6, top - 8);
    ctx.lineTo(left + 6, top - 8);
    ctx.stroke();
    ctx.restore();

    if (!reducedMotion) {
      const scanY = top + ((clock * 46) % usable);
      ctx.save();
      ctx.globalAlpha = 0.18;
      ctx.fillStyle = colours.phosphor;
      ctx.fillRect(left - skew, scanY, bodyWidth, 2);
      ctx.restore();

      ctx.save();
      const animation = (clock * 0.6) % 1;
      for (let index = 0; index < 12; index += 1) {
        const x = ((index * 97) % width) + Math.sin(clock + index) * 4;
        const y = (index * 53) % height;
        ctx.globalAlpha = 0.12 + 0.12 * Math.sin(clock * 2 + index);
        ctx.fillStyle = colours.accent;
        ctx.fillRect(x, y, 2, 2);
      }
      ctx.globalAlpha = 0.5 * (1 - animation);
      ctx.strokeStyle = colours.phosphor;
      ctx.beginPath();
      ctx.arc(width / 2, height / 2, 4 + animation * Math.min(width, height) * 0.6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    }
  }

  function tick(now) {
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    clock += dt;
    draw();
    frame = window.requestAnimationFrame(tick);
  }

  window.addEventListener("resize", draw);

  return {
    setCorp(value) {
      corp = value;
      draw();
    },
    setFloor(level) {
      lit = Number(level) || 1;
      draw();
    },
    start() {
      if (reducedMotion || frame) {
        draw();
        return;
      }
      frame = window.requestAnimationFrame(tick);
    },
    stop() {
      window.cancelAnimationFrame(frame);
      frame = 0;
      last = 0;
    },
    destroy() {
      this.stop();
      window.removeEventListener("resize", draw);
    },
  };
}
