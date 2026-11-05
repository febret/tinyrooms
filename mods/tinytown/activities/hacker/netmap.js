// Seeded network map renderer. Pure drawing plus hit-testing; the node list in
// the sidebar is the accessible way to open a node.

import { hexToRgba } from "./hacker-model.js";

const RADIUS = 21;

export function createNetmap({ canvas, reducedMotion = false, onPick = () => {} }) {
  const ctx = canvas.getContext("2d");
  let run = null;
  let frame = 0;
  let last = 0;
  let clock = 0;
  let width = 1;
  let height = 1;
  let positions = new Map();
  let hovered = "";
  const pulses = [];

  function colours() {
    const palette = run?.corp?.palette || {};
    return {
      phosphor: palette.phosphor || "#4bff7e",
      accent: palette.accent || "#b6ffc9",
      ink: palette.ink || "#03110a",
      deep: palette.deep || "#0a2a16",
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

  function layout() {
    positions = new Map();
    if (!run) return;
    const padX = Math.max(54, width * 0.1);
    const padY = Math.max(58, height * 0.14);
    const innerWidth = width - padX * 2;
    const innerHeight = height - padY * 2;
    for (const node of run.nodes) {
      positions.set(node.id, {
        x: padX + node.x * innerWidth,
        y: padY + node.y * innerHeight,
      });
    }
    const central = run.central || {};
    positions.set("central", {
      x: Math.min(width - padX * 0.7, padX + (central.x ?? 1) * innerWidth),
      y: padY + (central.y ?? 0.5) * innerHeight,
    });
  }

  function statusOf(id) {
    if (id === "central") return run?.central?.status || "locked";
    return run?.nodes?.find(node => node.id === id)?.status || "locked";
  }

  function drawBackground(palette) {
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.strokeStyle = hexToRgba(palette.deep, 0.85);
    ctx.lineWidth = 1;
    const step = 34;
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
    if (reducedMotion) return;
    ctx.save();
    ctx.globalAlpha = 0.12;
    ctx.fillStyle = palette.phosphor;
    for (let index = 0; index < 14; index += 1) {
      const x = (index * 73 + clock * 12) % width;
      const y = (index * 41 + clock * 7) % height;
      ctx.fillRect(x, y, 2, 2);
    }
    ctx.restore();
  }

  function drawEdges(palette) {
    if (!run) return;
    for (const edge of run.edges || []) {
      const from = positions.get(edge.from);
      const to = positions.get(edge.to);
      if (!from || !to) continue;
      const childStatus = statusOf(edge.to);
      const parentStatus = statusOf(edge.from);
      const live = childStatus === "open" || childStatus === "cleared";
      ctx.save();
      ctx.strokeStyle = hexToRgba(palette.phosphor, live ? 0.35 : 0.14);
      ctx.lineWidth = live ? 1.5 : 1;
      ctx.setLineDash(live ? [] : [3, 6]);
      ctx.beginPath();
      ctx.moveTo(from.x, from.y);
      ctx.lineTo(to.x, to.y);
      ctx.stroke();
      ctx.restore();
      if (!reducedMotion && (live || parentStatus === "cleared")) {
        const offset = reducedMotion ? 0.5 : (clock * 0.35 + (edge.from.length * 0.13)) % 1;
        const x = from.x + (to.x - from.x) * offset;
        const y = from.y + (to.y - from.y) * offset;
        ctx.save();
        ctx.fillStyle = hexToRgba(palette.accent, live ? 0.85 : 0.3);
        ctx.beginPath();
        ctx.arc(x, y, 2.4, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      }
    }
  }

  function hexPath(x, y, radius) {
    ctx.beginPath();
    for (let index = 0; index < 6; index += 1) {
      const angle = (index / 6) * Math.PI * 2 - Math.PI / 2;
      const px = x + Math.cos(angle) * radius;
      const py = y + Math.sin(angle) * radius;
      if (index) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
    }
    ctx.closePath();
  }

  function drawGlyph(kind, x, y, palette, bright) {
    ctx.save();
    ctx.strokeStyle = bright ? palette.accent : hexToRgba(palette.phosphor, 0.5);
    ctx.lineWidth = 1.6;
    if (kind === "database") {
      for (let index = 0; index < 3; index += 1) {
        ctx.beginPath();
        ctx.ellipse(x, y - 5 + index * 5, 7, 2.6, 0, 0, Math.PI * 2);
        ctx.stroke();
      }
    } else if (kind === "mail") {
      ctx.strokeRect(x - 7, y - 5, 14, 10);
      ctx.beginPath();
      ctx.moveTo(x - 7, y - 5);
      ctx.lineTo(x, y + 1);
      ctx.lineTo(x + 7, y - 5);
      ctx.stroke();
    } else if (kind === "maintenance") {
      ctx.beginPath();
      ctx.arc(x, y, 6, 0, Math.PI * 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x, y, 2, 0, Math.PI * 2);
      ctx.stroke();
    } else if (kind === "legacy") {
      ctx.strokeRect(x - 8, y - 6, 16, 11);
      ctx.beginPath();
      ctx.moveTo(x - 4, y + 7);
      ctx.lineTo(x + 4, y + 7);
      ctx.stroke();
    } else if (kind === "core") {
      ctx.strokeRect(x - 6, y - 7, 12, 14);
      for (let index = 0; index < 2; index += 1) {
        ctx.strokeRect(x - 4, y - 4 + index * 6, 8, 3);
      }
    } else {
      ctx.beginPath();
      ctx.moveTo(x, y - 7);
      ctx.lineTo(x + 7, y - 3);
      ctx.lineTo(x + 7, y + 4);
      ctx.lineTo(x, y + 8);
      ctx.lineTo(x - 7, y + 4);
      ctx.lineTo(x - 7, y - 3);
      ctx.closePath();
      ctx.stroke();
    }
    ctx.restore();
  }

  function drawNodes(palette) {
    if (!run) return;
    const all = [...(run.nodes || []), { ...(run.central || {}), id: "central" }];
    for (const node of all) {
      const point = positions.get(node.id);
      if (!point) continue;
      const status = statusOf(node.id);
      const central = node.id === "central";
      const radius = central ? RADIUS + 7 : RADIUS;
      const active = status === "open";
      const pulse = active && !reducedMotion ? 0.7 + 0.3 * Math.sin(clock * 4 + point.x * 0.02) : 1;
      ctx.save();
      ctx.globalAlpha = status === "locked" ? 0.4 : 1;
      ctx.translate(point.x, point.y);
      if (central) {
        ctx.rotate(Math.PI / 6);
        hexPath(0, 0, radius);
        ctx.rotate(-Math.PI / 6);
      } else {
        hexPath(0, 0, radius);
      }
      ctx.fillStyle = status === "cleared" ? hexToRgba(palette.deep, 0.9) : hexToRgba(palette.ink, 0.85);
      ctx.fill();
      ctx.lineWidth = active ? 2.6 : 1.4;
      ctx.strokeStyle = status === "cleared"
        ? hexToRgba(palette.phosphor, 0.55)
        : hexToRgba(palette.phosphor, active ? 0.95 * pulse : 0.3);
      ctx.stroke();
      if (hovered === node.id && active) {
        ctx.strokeStyle = hexToRgba(palette.accent, 0.5);
        ctx.lineWidth = 4;
        ctx.stroke();
      }
      ctx.restore();

      if (status === "cleared") {
        ctx.save();
        ctx.strokeStyle = hexToRgba(palette.accent, 0.85);
        ctx.lineWidth = 2.4;
        ctx.beginPath();
        ctx.moveTo(point.x - 6, point.y);
        ctx.lineTo(point.x - 1, point.y + 5);
        ctx.lineTo(point.x + 7, point.y - 6);
        ctx.stroke();
        ctx.restore();
      } else if (status === "open") {
        drawGlyph(central ? "core" : node.kind, point.x, point.y, palette, true);
        if (!reducedMotion) {
          ctx.save();
          ctx.strokeStyle = hexToRgba(palette.phosphor, 0.22);
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(point.x, point.y, radius + 5 + ((clock * 14) % 22), 0, Math.PI * 2);
          ctx.stroke();
          ctx.restore();
        }
      } else {
        drawGlyph(central ? "core" : node.kind, point.x, point.y, palette, false);
        ctx.save();
        ctx.strokeStyle = hexToRgba(palette.phosphor, 0.38);
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.rect(point.x - 3, point.y - 2, 6, 6);
        ctx.arc(point.x, point.y - 2, 2.4, Math.PI, 0);
        ctx.stroke();
        ctx.restore();
      }

      ctx.save();
      ctx.font = "600 9.5px ui-monospace, Consolas, monospace";
      ctx.textAlign = "center";
      ctx.fillStyle = hexToRgba(active ? palette.accent : palette.phosphor, active ? 0.95 : 0.55);
      ctx.fillText(node.label || node.name || "", point.x, point.y + radius + 14);
      ctx.restore();
    }
  }

  function draw() {
    resize();
    const palette = colours();
    layout();
    drawBackground(palette);
    drawEdges(palette);
    drawNodes(palette);
  }

  function tick(now) {
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    clock += dt;
    draw();
    frame = window.requestAnimationFrame(tick);
  }

  function pointFor(event) {
    const bounds = canvas.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  function findNode(point) {
    for (const [id, position] of positions) {
      if (Math.hypot(position.x - point.x, position.y - point.y) <= RADIUS + 8) return id;
    }
    return "";
  }

  canvas.addEventListener("pointermove", event => {
    const point = pointFor(event);
    const id = findNode(point);
    const status = id ? statusOf(id) : "locked";
    hovered = status === "open" ? id : "";
    canvas.style.cursor = hovered ? "pointer" : "default";
  });

  canvas.addEventListener("pointerdown", event => {
    const point = pointFor(event);
    const id = findNode(point);
    if (!id) return;
    if (statusOf(id) !== "open") return;
    onPick(id);
  });

  window.addEventListener("resize", draw);

  return {
    setRun(value) {
      run = value;
      draw();
    },
    start() {
      draw();
      if (reducedMotion || frame) return;
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
