import { CARD_FACE_HEIGHT, CARD_FACE_STYLE_VERSION, CARD_FACE_WIDTH, cardFaceFields, cardFaceSvg } from "./card-face.js";
import { cardTheme } from "./card-style.js";

// SVG drawn as an image cannot fetch external resources, so art is inlined.
const dataUrls = new Map();
const canvases = new Map();
const surfaceCanvases = new Map();
const CACHE_LIMIT = 24;
const SURFACE_WIDTH = 256;
const SURFACE_HEIGHT = 364;
let paperBump = null;

function artDataUrl(url) {
  if (!url) return Promise.resolve("");
  if (!dataUrls.has(url)) {
    const pending = fetch(url)
      .then(response => {
        if (!response.ok) throw new Error(`Card art ${url} returned ${response.status}`);
        return response.blob();
      })
      .then(blob => new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
      }))
      .catch(error => {
        dataUrls.delete(url);
        console.warn(`[Tinyrooms] ${error.message}`);
        return "";
      });
    dataUrls.set(url, pending);
  }
  return dataUrls.get(url);
}

function decodeSvg(markup) {
  const url = URL.createObjectURL(new Blob([markup], { type: "image/svg+xml" }));
  const image = new Image();
  image.decoding = "async";
  image.src = url;
  return image.decode().then(() => image, () => new Promise((resolve, reject) => {
    if (image.complete && image.naturalWidth) resolve(image);
    else reject(new Error("Card face SVG could not be decoded."));
  })).finally(() => URL.revokeObjectURL(url));
}

/** Cache key covering every value the face draws plus the layout version. */
export function cardFaceKey(definition, scale = 2) {
  return JSON.stringify([CARD_FACE_STYLE_VERSION, scale, cardFaceFields(definition)]);
}

/**
 * Rasterize a card face to a canvas, deduplicating concurrent requests.
 * Callers own any GPU texture they build from it; the canvas itself is shared.
 */
export function cardFaceCanvas(definition, { scale = 2 } = {}) {
  const key = cardFaceKey(definition, scale);
  if (canvases.has(key)) {
    const pending = canvases.get(key);
    canvases.delete(key);
    canvases.set(key, pending);
    return pending;
  }
  const fields = cardFaceFields(definition);
  const theme = cardTheme(fields);
  const pending = artDataUrl(fields.imageUrl)
    .then(imageHref => decodeSvg(cardFaceSvg(fields, { imageHref, idPrefix: "tex" })))
    .then(image => {
      const canvas = document.createElement("canvas");
      canvas.width = CARD_FACE_WIDTH * scale;
      canvas.height = CARD_FACE_HEIGHT * scale;
      const context = canvas.getContext("2d");
      // Match the rarity-tinted edge material so rounded corners read as card stock.
      context.fillStyle = theme.rarity.outline;
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      return canvas;
    })
    .catch(error => {
      canvases.delete(key);
      throw error;
    });
  canvases.set(key, pending);
  while (canvases.size > CACHE_LIMIT) canvases.delete(canvases.keys().next().value);
  return pending;
}

function noise(x, y) {
  const value = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

/**
 * Build a subtle roughness map from the printed face: ink reads glossier than
 * the card stock, with fine grain breaking up the clearcoat highlight.
 */
export function cardSurfaceCanvas(definition) {
  const key = cardFaceKey(definition, "surface");
  if (surfaceCanvases.has(key)) {
    const pending = surfaceCanvases.get(key);
    surfaceCanvases.delete(key);
    surfaceCanvases.set(key, pending);
    return pending;
  }
  const pending = cardFaceCanvas(definition).then(faceCanvas => {
    const canvas = document.createElement("canvas");
    canvas.width = SURFACE_WIDTH;
    canvas.height = SURFACE_HEIGHT;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    context.drawImage(faceCanvas, 0, 0, SURFACE_WIDTH, SURFACE_HEIGHT);
    const image = context.getImageData(0, 0, SURFACE_WIDTH, SURFACE_HEIGHT);
    const data = image.data;
    for (let index = 0; index < data.length; index += 4) {
      const x = (index / 4) % SURFACE_WIDTH;
      const y = Math.floor(index / 4 / SURFACE_WIDTH);
      const luminance = (data[index] * 0.299 + data[index + 1] * 0.587 + data[index + 2] * 0.114) / 255;
      const grain = (noise(x, y) - 0.5) * 0.16;
      const roughness = Math.max(0.14, Math.min(0.86, 0.3 + (1 - luminance) * 0.34 + grain));
      const value = Math.round(roughness * 255);
      data[index] = value;
      data[index + 1] = value;
      data[index + 2] = value;
      data[index + 3] = 255;
    }
    context.putImageData(image, 0, 0);
    return canvas;
  }).catch(error => {
    surfaceCanvases.delete(key);
    throw error;
  });
  surfaceCanvases.set(key, pending);
  while (surfaceCanvases.size > CACHE_LIMIT) surfaceCanvases.delete(surfaceCanvases.keys().next().value);
  return pending;
}

/** Shared micro-grain bump map for card stock. */
export function paperBumpCanvas() {
  if (paperBump) return paperBump;
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  const image = context.createImageData(128, 128);
  for (let index = 0; index < image.data.length; index += 4) {
    const x = (index / 4) % 128;
    const y = Math.floor(index / 4 / 128);
    const value = 120 + Math.floor((noise(x * 3, y * 3) + noise(x, y) * 0.5) * 68);
    image.data[index] = value;
    image.data[index + 1] = value;
    image.data[index + 2] = value;
    image.data[index + 3] = 255;
  }
  context.putImageData(image, 0, 0);
  paperBump = canvas;
  return paperBump;
}
