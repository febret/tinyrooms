// Rasterize a sticker design by stacking recolored SVG part layers.
//
// To keep the editor responsive (and cheap under software rendering) the layers
// are merged into a single SVG document and rasterized once per unique design.

import { resolveLayers } from "./parts.js";

export const AUTHOR_WIDTH = 200;
export const AUTHOR_HEIGHT = 220;

const PART_ROOT = new URL("./parts/", import.meta.url);
const svgTextCache = new Map();
const imageCache = new Map();

function loadSvgText(file) {
  if (!svgTextCache.has(file)) {
    const promise = fetch(new URL(file, PART_ROOT)).then(response => {
      if (!response.ok) throw new Error(`Missing sticker part: ${file}`);
      return response.text();
    });
    svgTextCache.set(file, promise);
  }
  return svgTextCache.get(file);
}

function paint(svgText, colors) {
  return svgText.replace(/\{\{(\w+)\}\}/g, (match, key) => colors[key] || "#000000");
}

function innerSvg(svgText) {
  const match = /<svg[^>]*>([\s\S]*?)<\/svg>/i.exec(svgText);
  return match ? match[1] : svgText;
}

async function composedSvg(design) {
  const pieces = await Promise.all(resolveLayers(design).map(async file => {
    const painted = paint(await loadSvgText(file), design.colors);
    return `<g>${innerSvg(painted)}</g>`;
  }));
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${AUTHOR_WIDTH}" height="${AUTHOR_HEIGHT}" viewBox="0 0 ${AUTHOR_WIDTH} ${AUTHOR_HEIGHT}">${pieces.join("")}</svg>`;
}

function rasterize(svgText) {
  return new Promise((resolve, reject) => {
    const blob = new Blob([svgText], { type: "image/svg+xml" });
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error("A sticker part failed to load."));
    };
    image.src = url;
  });
}

function stickerImage(design) {
  const key = JSON.stringify(design);
  if (!imageCache.has(key)) {
    imageCache.set(key, composedSvg(design).then(rasterize));
  }
  return imageCache.get(key);
}

export async function renderSticker(canvas, design) {
  const image = await stickerImage(design);
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(image, 0, 0, canvas.width, canvas.height);
}

export function exportSticker(canvas) {
  return canvas.toDataURL("image/png");
}
