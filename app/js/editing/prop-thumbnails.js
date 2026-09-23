import * as THREE from "three";
import { GLTFLoader } from "../../vendor/three/examples/jsm/loaders/GLTFLoader.js";
import { disposeBoardTree } from "../board-helpers.js";

const SIZE = 128;
const loader = new GLTFLoader();
const cache = new Map();
const inflight = new Map();
let renderer = null;
let scene = null;
let camera = null;
let pivot = null;

function cacheKey(modelUrl, scale) {
  return `${modelUrl}|${scale}`;
}

/** Lazily create the single offscreen renderer shared by every library thumbnail. */
function ensureRenderer() {
  if (renderer) return;
  const canvas = document.createElement("canvas");
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(1);
  renderer.setSize(SIZE, SIZE, false);
  renderer.setClearColor(0x000000, 0);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(38, 1, 0.05, 200);
  pivot = new THREE.Group();
  scene.add(pivot);
  scene.add(new THREE.HemisphereLight("#fff2d5", "#496e69", 1.5));
  const key = new THREE.DirectionalLight("#fff4de", 1.7);
  key.position.set(4, 7, 6);
  scene.add(key);
  const fill = new THREE.DirectionalLight("#bcd9ff", 0.7);
  fill.position.set(-5, 3, -4);
  scene.add(fill);
}

/** Return an already-rendered thumbnail data URL, or null when it must be built. */
export function cachedThumbnail(modelUrl, scale = 1) {
  return cache.get(cacheKey(modelUrl, scale)) || null;
}

/**
 * Render one static prop thumbnail through the shared context.
 *
 * A single WebGL context serves every library tile; per-tile renderers would
 * churn contexts on each editor re-render and evict the room board.
 */
export function thumbnailFor(modelUrl, scale = 1) {
  const key = cacheKey(modelUrl, scale);
  if (cache.has(key)) return Promise.resolve(cache.get(key));
  if (inflight.has(key)) return inflight.get(key);
  const promise = new Promise(resolve => {
    ensureRenderer();
    loader.load(modelUrl, gltf => {
      const model = gltf.scene;
      try {
        const bounds = new THREE.Box3().setFromObject(model);
        if (bounds.isEmpty()) {
          disposeBoardTree(gltf.scenes || [model]);
          resolve("");
          return;
        }
        const size = bounds.getSize(new THREE.Vector3()).multiplyScalar(scale);
        const center = bounds.getCenter(new THREE.Vector3());
        const visual = new THREE.Group();
        visual.scale.setScalar(scale);
        visual.position.set(-center.x * scale, -bounds.min.y * scale, -center.z * scale);
        visual.add(model);
        pivot.add(visual);
        const radius = Math.max(size.x, size.z, size.y, 0.5);
        camera.position.set(radius * 1.05, size.y * 0.55, radius * 1.6);
        camera.lookAt(0, size.y * 0.5, 0);
        renderer.render(scene, camera);
        const dataUrl = renderer.domElement.toDataURL("image/png");
        pivot.remove(visual);
        disposeBoardTree([visual, ...(gltf.scenes || [model])]);
        cache.set(key, dataUrl);
        resolve(dataUrl);
      } catch {
        disposeBoardTree([model, ...(gltf.scenes || [])]);
        resolve("");
      }
    }, undefined, () => resolve(""));
  }).finally(() => inflight.delete(key));
  inflight.set(key, promise);
  return promise;
}

/** Keep `img[data-thumb-model]` tiles in sync with cached or freshly rendered thumbnails. */
export function createThumbnailManager() {
  const assigned = new WeakMap();

  function apply(image, modelUrl, scale) {
    const key = cacheKey(modelUrl, scale);
    if (assigned.get(image) === key) return;
    assigned.set(image, key);
    const cached = cachedThumbnail(modelUrl, scale);
    if (cached) {
      image.src = cached;
      image.dataset.thumbReady = "true";
      return;
    }
    thumbnailFor(modelUrl, scale).then(async url => {
      if (!image.isConnected) return;
      if (!url) {
        image.dataset.thumbError = "true";
        return;
      }
      image.src = url;
      try {
        await image.decode();
      } catch {
        // Decoding may fail if the tile was removed before paint.
      }
      if (image.isConnected) image.dataset.thumbReady = "true";
    }).catch(() => {
      image.dataset.thumbError = "true";
    });
  }

  return {
    sync(root) {
      for (const image of root.querySelectorAll("img[data-thumb-model]")) {
        apply(image, image.dataset.thumbModel, Number(image.dataset.thumbScale) || 1);
      }
    },
  };
}
