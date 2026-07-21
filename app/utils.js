function resolveBackgroundUrl(backgroundPath) {
  if (!backgroundPath) return "";
  if (backgroundPath.startsWith("/") || backgroundPath.startsWith("http://") || backgroundPath.startsWith("https://")) {
    return backgroundPath;
  }
  return "/world/images/" + backgroundPath;
}

function resolveAssetUrl(assetPath) {
  if (!assetPath) return "";
  if (assetPath.startsWith("/") || assetPath.startsWith("http://") || assetPath.startsWith("https://")) {
    return assetPath;
  }
  return "/world/" + assetPath;
}

// ---------------------------------------------------------------------------
// Editor shared utilities
// ---------------------------------------------------------------------------

// Fetch wrapper for editor API calls. Parses JSON, throws on HTTP errors
// with any server-provided details appended to the message.
async function editorApi(path, options) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options?.headers || {}),
    },
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload?.details ? `\n${payload.details.join("\n")}` : "";
    throw new Error((payload?.error || `HTTP ${response.status}`) + detail);
  }
  return payload;
}

// Promise-based image loader.
function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load image: ${url}`));
    img.src = url;
  });
}

// Parse a CSS hex color string ("#rrggbb" or "rrggbb") into [r, g, b].
// Returns null if the string is missing or invalid.
function parseBgColor(hexStr) {
  if (!hexStr) return null;
  const s = hexStr.trim();
  const m = s.match(/^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if (!m) return null;
  return [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)];
}

// Draw a cropped region of srcImg onto canvas with optional background-color removal.
// The region is scaled to fill canvas dimensions while preserving aspect ratio (centered).
//   canvas  – target HTMLCanvasElement (already sized by caller)
//   srcImg  – source HTMLImageElement
//   sx, sy  – top-left of the source region in image pixels
//   sw, sh  – size of the source region in image pixels
//   bgRgb   – [r, g, b] color to make transparent, or null to skip removal
//   tolerance – per-channel threshold for color matching (default 10)
function drawSpriteThumb(canvas, srcImg, sx, sy, sw, sh, bgRgb = null, tolerance = 10) {
  const tc = canvas.getContext("2d");
  const dw = canvas.width;
  const dh = canvas.height;
  tc.clearRect(0, 0, dw, dh);
  if (!srcImg) return;

  // Rasterise source region at native resolution into a temporary canvas.
  const tmp = document.createElement("canvas");
  tmp.width = sw;
  tmp.height = sh;
  const tmpc = tmp.getContext("2d");
  tmpc.drawImage(srcImg, sx, sy, sw, sh, 0, 0, sw, sh);

  if (bgRgb) {
    const id = tmpc.getImageData(0, 0, sw, sh);
    const d = id.data;
    const [tr, tg, tb] = bgRgb;
    for (let i = 0; i < d.length; i += 4) {
      if (
        Math.abs(d[i]     - tr) <= tolerance &&
        Math.abs(d[i + 1] - tg) <= tolerance &&
        Math.abs(d[i + 2] - tb) <= tolerance
      ) {
        d[i + 3] = 0;
      }
    }
    tmpc.putImageData(id, 0, 0);
  }

  const scale = Math.min(dw / sw, dh / sh, 1);
  const scaledW = Math.round(sw * scale);
  const scaledH = Math.round(sh * scale);
  const dx = Math.floor((dw - scaledW) / 2);
  const dy = Math.floor((dh - scaledH) / 2);
  tc.drawImage(tmp, 0, 0, sw, sh, dx, dy, scaledW, scaledH);
}

// Rename a key in an object while preserving insertion order.
// Returns a new object with the key renamed; the original is not mutated.
function renameKeyInObject(obj, oldKey, newKey) {
  const result = {};
  for (const [k, v] of Object.entries(obj)) {
    result[k === oldKey ? newKey : k] = v;
  }
  return result;
}
