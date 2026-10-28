// Procedural canvas textures for the TinyTown tabletop diorama.
//
// Kept separate from board-diorama.js so the board file stays focused on
// scene assembly. All noise uses seeded randomness for a stable look.

import * as THREE from "three";

import { seededRandom } from "./board-diorama-terrain.js";

export function makeCanvasTexture(width, height, draw, { repeatX = 1, repeatY = 1 } = {}) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  draw(context, width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeatX, repeatY);
  texture.anisotropy = 4;
  return texture;
}

export function makeGroundTexture() {
  return makeCanvasTexture(512, 512, (context, width, height) => {
    context.fillStyle = "#f3f2e9";
    context.fillRect(0, 0, width, height);
    const random = seededRandom(8127);
    for (let index = 0; index < 3600; index += 1) {
      const x = random() * width;
      const y = random() * height;
      const size = 0.6 + random() * 2.2;
      context.fillStyle = random() > 0.55
        ? `rgba(83,101,60,${0.05 + random() * 0.1})`
        : `rgba(255,255,245,${0.06 + random() * 0.12})`;
      context.beginPath();
      context.ellipse(x, y, size, size * (0.5 + random() * 0.8), random() * Math.PI, 0, Math.PI * 2);
      context.fill();
    }
    context.lineWidth = 0.8;
    for (let blade = 0; blade < 520; blade += 1) {
      const x = random() * width;
      const y = random() * height;
      const lean = (random() - 0.5) * 5;
      context.strokeStyle = `rgba(72,92,54,${0.08 + random() * 0.12})`;
      context.beginPath();
      context.moveTo(x, y + 3);
      context.quadraticCurveTo(x + lean * 0.4, y, x + lean, y - 3 - random() * 3);
      context.stroke();
    }
  }, { repeatX: 5, repeatY: 4 });
}

export function makeDetailTexture() {
  return makeCanvasTexture(256, 256, (context, width, height) => {
    const image = context.createImageData(width, height);
    for (let index = 0; index < image.data.length; index += 4) {
      const value = 112 + Math.floor(Math.random() * 46);
      image.data[index] = value;
      image.data[index + 1] = value;
      image.data[index + 2] = value;
      image.data[index + 3] = 255;
    }
    context.putImageData(image, 0, 0);
  }, { repeatX: 18, repeatY: 15 });
}

export function makeCobbleTexture() {
  return makeCanvasTexture(512, 512, (context, width, height) => {
    context.fillStyle = "#a99c84";
    context.fillRect(0, 0, width, height);
    const random = seededRandom(3319);
    const rowHeight = 52;
    for (let row = 0; row < 11; row += 1) {
      const offset = row % 2 ? -28 : 0;
      for (let column = 0; column < 11; column += 1) {
        const x = column * 52 + offset + random() * 10;
        const y = row * rowHeight + random() * 8;
        const radiusX = 20 + random() * 7;
        const radiusY = 17 + random() * 6;
        context.fillStyle = `hsl(${31 + random() * 13} ${10 + random() * 9}% ${53 + random() * 16}%)`;
        context.beginPath();
        context.moveTo(x, y - radiusY);
        context.bezierCurveTo(x + radiusX, y - radiusY, x + radiusX * 1.05, y + radiusY * 0.2, x + radiusX * 0.55, y + radiusY);
        context.bezierCurveTo(x + radiusX * 0.1, y + radiusY * 1.15, x - radiusX * 0.7, y + radiusY * 0.9, x - radiusX, y + radiusY * 0.2);
        context.bezierCurveTo(x - radiusX * 1.05, y - radiusY * 0.5, x - radiusX * 0.4, y - radiusY * 1.1, x, y - radiusY);
        context.fill();
        context.strokeStyle = "rgba(66,55,40,0.28)";
        context.lineWidth = 2;
        context.stroke();
        context.fillStyle = "rgba(255,250,228,0.16)";
        context.beginPath();
        context.ellipse(x - radiusX * 0.28, y - radiusY * 0.36, radiusX * 0.5, radiusY * 0.28, -0.3, 0, Math.PI * 2);
        context.fill();
      }
    }
  }, { repeatX: 3, repeatY: 2.2 });
}

export function makeWoodTexture() {
  return makeCanvasTexture(512, 256, (context, width, height) => {
    const random = seededRandom(6151);
    const base = context.createLinearGradient(0, 0, width, 0);
    base.addColorStop(0, "#6f4c31");
    base.addColorStop(0.45, "#805b3d");
    base.addColorStop(1, "#67452c");
    context.fillStyle = base;
    context.fillRect(0, 0, width, height);
    for (let line = 0; line < 72; line += 1) {
      const y = random() * height;
      context.strokeStyle = `rgba(${34 + random() * 28},${21 + random() * 18},${12 + random() * 12},${0.16 + random() * 0.3})`;
      context.lineWidth = 0.5 + random() * 2.1;
      context.beginPath();
      context.moveTo(0, y);
      for (let x = 0; x <= width; x += 12) {
        context.lineTo(x, y + Math.sin(x * 0.045 + line * 0.9) * (1.6 + random() * 1.5));
      }
      context.stroke();
    }
    for (let knot = 0; knot < 7; knot += 1) {
      const x = 40 + random() * (width - 80);
      const y = 24 + random() * (height - 48);
      for (let ring = 1; ring <= 4; ring += 1) {
        context.strokeStyle = `rgba(46,29,16,${0.18 - ring * 0.025})`;
        context.lineWidth = 1.2;
        context.beginPath();
        context.ellipse(x, y, ring * 4.5, ring * 2.2, 0.2, 0, Math.PI * 2);
        context.stroke();
      }
    }
  }, { repeatX: 2, repeatY: 1 });
}

export function makePlaqueTexture() {
  return makeCanvasTexture(512, 128, (context, width, height) => {
    const gradient = context.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#d8b86a");
    gradient.addColorStop(0.48, "#a97b33");
    gradient.addColorStop(1, "#745022");
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "rgba(65,39,12,0.9)";
    context.lineWidth = 8;
    context.strokeRect(6, 6, width - 12, height - 12);
    context.fillStyle = "#2f2114";
    context.textAlign = "center";
    context.font = "700 49px Georgia, serif";
    context.fillText("TINYTOWN", width / 2, 68);
    context.font = "600 17px Georgia, serif";
    context.letterSpacing = "4px";
    context.fillText("EST. 2026 · POPULATION: MANY PEEPS", width / 2, 101);
  });
}

export function makeGlowTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 62);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.22, "rgba(255,239,190,0.78)");
  gradient.addColorStop(1, "rgba(255,190,94,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export function makeStarTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  const glow = context.createRadialGradient(64, 64, 1, 64, 64, 62);
  glow.addColorStop(0, "rgba(255,252,225,1)");
  glow.addColorStop(0.25, "rgba(255,227,138,0.65)");
  glow.addColorStop(0.6, "rgba(255,183,72,0.18)");
  glow.addColorStop(1, "rgba(255,170,60,0)");
  context.fillStyle = glow;
  context.fillRect(0, 0, 128, 128);

  context.save();
  context.translate(64, 64);
  context.beginPath();
  for (let point = 0; point < 10; point += 1) {
    const angle = -Math.PI / 2 + point * Math.PI / 5;
    const radius = point % 2 === 0 ? 43 : 17;
    const x = Math.cos(angle) * radius;
    const y = Math.sin(angle) * radius;
    if (point === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  }
  context.closePath();
  const star = context.createLinearGradient(0, -42, 0, 42);
  star.addColorStop(0, "#fffdf0");
  star.addColorStop(0.5, "#ffe28a");
  star.addColorStop(1, "#f4a83f");
  context.fillStyle = star;
  context.fill();
  context.lineWidth = 3;
  context.strokeStyle = "rgba(255,252,228,0.92)";
  context.stroke();
  context.restore();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}
