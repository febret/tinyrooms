import { CARD_FACE_HEIGHT, CARD_FACE_STYLE_VERSION, CARD_FACE_WIDTH, cardFaceFields, cardFaceSvg } from "./card-face.js";

// SVG drawn as an image cannot fetch external resources, so art is inlined.
const dataUrls = new Map();
const canvases = new Map();
const CACHE_LIMIT = 24;

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
  const pending = artDataUrl(fields.imageUrl)
    .then(imageHref => decodeSvg(cardFaceSvg(fields, { imageHref, idPrefix: "tex" })))
    .then(image => {
      const canvas = document.createElement("canvas");
      canvas.width = CARD_FACE_WIDTH * scale;
      canvas.height = CARD_FACE_HEIGHT * scale;
      const context = canvas.getContext("2d");
      // Match the card's edge material so rounded frame corners read as card stock.
      context.fillStyle = "#d5b887";
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
