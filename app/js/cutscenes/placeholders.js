import { thumbnailFor } from "../editing/prop-thumbnails.js";
import { withBase } from "../base-path.js";

const PAGE_ORIGIN = typeof window === "undefined" ? "" : window.location.origin;
const elementCache = new Map();
const rejected = new Set();

/** Accept same-origin assets and inline data URLs (including rendered prop art). */
export function isSameOrigin(url) {
  if (typeof url !== "string" || !url) return false;
  if (url.startsWith("data:")) return true;
  try {
    return new URL(url, PAGE_ORIGIN).origin === PAGE_ORIGIN;
  } catch {
    return false;
  }
}

/** Log a rejected or unusable asset URL once per URL. */
function warnOnce(key, message) {
  if (rejected.has(key)) return;
  rejected.add(key);
  console.warn(`[Tinyrooms cutscene] ${message}`);
}

/** Return the still or animated art URL for a resolved asset record. */
export function assetSource(asset) {
  if (!asset) return "";
  // Animation replaces still art when present; a rejected animation URL does
  // not silently fall back to the still image.
  const preferred = asset.animation_url || asset.url;
  if (!isSameOrigin(preferred)) {
    warnOnce(String(preferred), `Rejected image URL ${String(preferred)}.`);
    return "";
  }
  return withBase(preferred);
}

/** Build the neutral box shown while a sprite loads or cannot resolve. */
export function placeholderBox(asset) {
  const box = document.createElement("div");
  box.className = "cutscene-sprite-placeholder";
  box.dataset.spriteKind = asset?.kind || "missing";
  box.textContent = asset?.label || "";
  return box;
}

/** Build a sprite <img> showing `src` for an asset of `kind`. */
function spriteImage(asset, kind, src) {
  const image = document.createElement("img");
  image.className = "cutscene-sprite-image";
  image.dataset.spriteKind = kind;
  image.alt = asset.label || "";
  image.decoding = "async";
  image.src = src;
  return image;
}

/** Build a still <img> for a sticker or card asset. */
function imageElement(asset) {
  const image = spriteImage(asset, asset.kind, assetSource(asset));
  image.addEventListener("error", () => {
    warnOnce(String(asset.url), `Could not load image for ${String(asset.ref)}.`);
    image.replaceWith(placeholderBox(asset));
  });
  return image;
}

/** Build the still <img> for a 3D prop, rendered through the shared offscreen context. */
function propElement(asset) {
  const url = withBase(asset.model_url || "");
  if (!isSameOrigin(url)) {
    warnOnce(String(url), `Rejected model URL ${String(url)}.`);
    return Promise.resolve(placeholderBox(asset));
  }
  return thumbnailFor(url, Number(asset.scale) || 1).then(
    dataUrl => {
      const image = spriteImage(asset, "prop", dataUrl);
      image.dataset.modelUrl = url;
      return image;
    },
    () => {
      warnOnce(String(url), `Could not render a thumbnail for ${String(asset.ref)}.`);
      return placeholderBox(asset);
    },
  );
}

/** Return the element for one resolved asset record, cached by record identity. */
export function elementForAsset(asset) {
  if (!asset) return Promise.resolve(placeholderBox(null));
  const key = `${asset.kind}|${asset.id}|${asset.url || asset.model_url || ""}`;
  if (elementCache.has(key)) return elementCache.get(key);
  const pending = asset.kind === "prop" ? propElement(asset) : Promise.resolve(imageElement(asset));
  elementCache.set(key, pending);
  return pending;
}

/** Clone a prepared sprite so a scene may use the same placeholder twice. */
export async function spriteForAsset(asset) {
  const element = await elementForAsset(asset);
  return element.cloneNode(element.tagName === "IMG" ? true : false);
}

/** Drop every cached sprite, used when a room's content changes. */
export function resetPlaceholders() {
  elementCache.clear();
  rejected.clear();
}
