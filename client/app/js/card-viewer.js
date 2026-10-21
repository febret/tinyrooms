import * as THREE from "three";
import { cardFaceCanvas } from "./card-face-texture.js";
import { createViewerStage } from "./viewer-stage.js";

const CARD_WIDTH = 0.62;
const CARD_HEIGHT = 0.88;
const CARD_DEPTH = 0.005;
const textureLoader = new THREE.TextureLoader();

/** Create one rotatable WebGL card viewer showing a composed SVG front and back art. */
function createCardViewer({ canvas, faceKey, backUrl, interactive, reducedMotion }) {
  const stage = createViewerStage({ canvas, interactive });
  if (stage.controls) {
    // Keep the card upright while allowing a full turn to reach the back face.
    stage.controls.minPolarAngle = Math.PI * 0.3;
    stage.controls.maxPolarAngle = Math.PI * 0.7;
  }

  const edge = new THREE.MeshStandardMaterial({ color: "#d5b887", roughness: 0.85 });
  const front = new THREE.MeshStandardMaterial({ color: "#fff7e3", roughness: 0.6 });
  const back = new THREE.MeshStandardMaterial({ color: "#193e55", roughness: 0.6 });
  // BoxGeometry's +Z/-Z material slots are the front and back faces.
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(CARD_WIDTH, CARD_HEIGHT, CARD_DEPTH),
    [edge, edge, edge, edge, front, back],
  );
  // Seat the card on y=0 so the stage's centered framing matches the model viewer.
  mesh.position.y = CARD_HEIGHT * 0.5;
  stage.pivot.add(mesh);
  stage.frame(CARD_WIDTH, CARD_HEIGHT);
  // Flat cards read best head-on; the prop stage's angled camera suits 3D models.
  const center = CARD_HEIGHT * 0.5;
  stage.camera.position.set(0, center, Math.max(CARD_WIDTH, CARD_HEIGHT) * 1.8);
  stage.camera.lookAt(0, center, 0);
  if (stage.controls) {
    stage.controls.target.set(0, center, 0);
    stage.controls.update();
  }
  stage.resize();

  let disposed = false;
  let pending = 2;

  function settle() {
    if (disposed) return;
    pending -= 1;
    if (pending <= 0) {
      stage.renderFrame(0, false);
    }
  }

  function applyTexture(map, material) {
    if (disposed) {
      map.dispose();
      return;
    }
    map.colorSpace = THREE.SRGBColorSpace;
    map.anisotropy = Math.min(8, stage.renderer.capabilities.getMaxAnisotropy());
    material.map = map;
    material.color.set("#ffffff");
    material.needsUpdate = true;
    settle();
  }

  function loadTexture(url, material) {
    if (!url) {
      settle();
      return;
    }
    textureLoader.load(url, map => applyTexture(map, material), undefined, () => {
      if (!disposed) settle();
    });
  }

  let definition = null;
  try {
    definition = JSON.parse(faceKey || "null");
  } catch {
    definition = null;
  }
  if (definition) {
    // Each viewer owns its CanvasTexture; the rasterized canvas is a shared cache entry.
    cardFaceCanvas(definition).then(
      faceCanvas => applyTexture(new THREE.CanvasTexture(faceCanvas), front),
      error => {
        console.warn(`[Tinyrooms] ${error.message}`);
        if (!disposed) settle();
      },
    );
  } else {
    settle();
  }
  loadTexture(backUrl, back);

  return {
    faceKey,
    backUrl,
    render(delta) {
      stage.renderFrame(delta, !interactive && !reducedMotion);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      stage.dispose();
    },
  };
}

/**
 * Keep WebGL card viewers in sync with canvases carrying `data-card-face` JSON.
 * One shared animation frame drives every mounted viewer.
 */
export function createCardViewerManager() {
  const viewers = new Map();
  let frame = null;
  let last = 0;

  function tick(now) {
    const delta = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    for (const viewer of viewers.values()) viewer.render(delta);
    frame = requestAnimationFrame(tick);
  }

  function start() {
    if (frame !== null) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  }

  function stopIfEmpty() {
    if (viewers.size === 0 && frame !== null) {
      cancelAnimationFrame(frame);
      frame = null;
    }
  }

  function sync(root, reducedMotion) {
    const canvases = [...root.querySelectorAll("canvas[data-card-face]")];
    // Drop viewers whose canvas left the DOM (details closed or replaced).
    for (const [canvas, viewer] of viewers) {
      if (!canvas.isConnected) {
        viewer.dispose();
        viewers.delete(canvas);
      }
    }
    for (const canvas of canvases) {
      const faceKey = canvas.dataset.cardFace;
      const backUrl = canvas.dataset.cardBack;
      const existing = viewers.get(canvas);
      if (existing && existing.faceKey === faceKey && existing.backUrl === backUrl) continue;
      existing?.dispose();
      viewers.set(canvas, createCardViewer({
        canvas,
        faceKey,
        backUrl,
        interactive: canvas.dataset.cardInteractive === "true",
        reducedMotion: Boolean(reducedMotion),
      }));
    }
    if (viewers.size) start();
    else stopIfEmpty();
  }

  function dispose() {
    for (const viewer of viewers.values()) viewer.dispose();
    viewers.clear();
    stopIfEmpty();
  }

  return { sync, dispose };
}
