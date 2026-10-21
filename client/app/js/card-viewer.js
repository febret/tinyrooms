import * as THREE from "three";
import { cardFaceCanvas, cardSurfaceCanvas, paperBumpCanvas } from "./card-face-texture.js";
import { cardTheme } from "./card-style.js";
import { createViewerStage } from "./viewer-stage.js";

const CARD_WIDTH = 0.62;
const CARD_HEIGHT = 0.88;
const CARD_DEPTH = 0.005;
const textureLoader = new THREE.TextureLoader();

function studioCanvas() {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 256;
  const context = canvas.getContext("2d");
  const background = context.createLinearGradient(0, 0, 0, canvas.height);
  background.addColorStop(0, "#6a7d86");
  background.addColorStop(0.45, "#26343b");
  background.addColorStop(1, "#080d10");
  context.fillStyle = background;
  context.fillRect(0, 0, canvas.width, canvas.height);

  const key = context.createRadialGradient(120, 48, 4, 120, 48, 118);
  key.addColorStop(0, "#fff8e8");
  key.addColorStop(0.35, "#ffe2b8cc");
  key.addColorStop(1, "#ffe2b800");
  context.fillStyle = key;
  context.fillRect(0, 0, canvas.width, canvas.height);

  const fill = context.createRadialGradient(394, 96, 4, 394, 96, 138);
  fill.addColorStop(0, "#d9f2ff");
  fill.addColorStop(0.4, "#a8d4ff99");
  fill.addColorStop(1, "#a8d4ff00");
  context.fillStyle = fill;
  context.fillRect(0, 0, canvas.width, canvas.height);

  const rim = context.createRadialGradient(256, 242, 4, 256, 242, 150);
  rim.addColorStop(0, "#ffd59a");
  rim.addColorStop(0.4, "#ffb86688");
  rim.addColorStop(1, "#ffb86600");
  context.fillStyle = rim;
  context.fillRect(0, 0, canvas.width, canvas.height);
  return canvas;
}

function createEnvironment(renderer) {
  const texture = new THREE.CanvasTexture(studioCanvas());
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.mapping = THREE.EquirectangularReflectionMapping;
  const pmrem = new THREE.PMREMGenerator(renderer);
  const target = pmrem.fromEquirectangular(texture);
  texture.dispose();
  pmrem.dispose();
  return target;
}

function haloCanvas() {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 256;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(128, 128, 10, 128, 128, 126);
  gradient.addColorStop(0, "#ffffff");
  gradient.addColorStop(0.34, "#ffffff8c");
  gradient.addColorStop(0.62, "#ffffff2e");
  gradient.addColorStop(1, "#ffffff00");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 256, 256);
  return canvas;
}

function cardThemeFromFaceKey(faceKey) {
  try {
    return cardTheme(JSON.parse(faceKey || "null") || {});
  } catch {
    return cardTheme({});
  }
}

/** Create one rotatable WebGL card viewer showing a composed SVG front and back art. */
function createCardViewer({ canvas, faceKey, backUrl, interactive, reducedMotion }) {
  const stage = createViewerStage({
    canvas,
    interactive,
    // Card stock reads better with strong directional shaping and less ambient
    // fill; the default prop lighting flattens the printed colours.
    lighting: { hemisphere: 0.45, key: 2.05, fill: 0.28 },
  });
  if (stage.controls) {
    // Keep the card upright while allowing a full turn to reach the back face.
    stage.controls.minPolarAngle = Math.PI * 0.3;
    stage.controls.maxPolarAngle = Math.PI * 0.7;
  }
  stage.renderer.toneMapping = THREE.NoToneMapping;
  stage.renderer.toneMappingExposure = 1.0;

  const theme = cardThemeFromFaceKey(faceKey);
  const rarity = theme.rarity;
  const environment = createEnvironment(stage.renderer);
  stage.scene.environment = environment.texture;
  stage.scene.environmentIntensity = 0.64;

  const edge = new THREE.MeshPhysicalMaterial({
    color: new THREE.Color(rarity.outline),
    metalness: 0.5 + rarity.foil * 0.42,
    roughness: 0.42 - rarity.foil * 0.16,
    clearcoat: 1,
    clearcoatRoughness: 0.12,
    envMapIntensity: 1.05,
    emissive: new THREE.Color(rarity.glow),
    emissiveIntensity: rarity.emissive,
  });
  const front = new THREE.MeshPhysicalMaterial({
    color: "#ffffff",
    roughness: 0.52,
    metalness: 0,
    clearcoat: 0.84,
    clearcoatRoughness: 0.2,
    envMapIntensity: 0.76,
    specularIntensity: 0.8,
    sheen: 0.14,
    sheenRoughness: 0.68,
    sheenColor: new THREE.Color(theme.accent),
    iridescence: rarity.iridescence,
    iridescenceIOR: 1.32,
  });
  const back = new THREE.MeshPhysicalMaterial({
    color: "#ffffff",
    roughness: 0.52,
    metalness: 0.04,
    clearcoat: 0.5,
    clearcoatRoughness: 0.24,
    envMapIntensity: 0.8,
  });
  // BoxGeometry's +Z/-Z material slots are the front and back faces.
  const mesh = new THREE.Mesh(
    new THREE.BoxGeometry(CARD_WIDTH, CARD_HEIGHT, CARD_DEPTH),
    [edge, edge, edge, edge, front, back],
  );
  // Seat the card on y=0 so the stage's centered framing matches the model viewer.
  mesh.position.y = CARD_HEIGHT * 0.5;
  // A slight three-quarter pose reveals the foil edge and catches the clearcoat.
  mesh.rotation.set(0.018, -0.11, -0.012);
  stage.pivot.add(mesh);

  const bump = new THREE.CanvasTexture(paperBumpCanvas());
  bump.wrapS = bump.wrapT = THREE.RepeatWrapping;
  bump.repeat.set(2.4, 3.4);
  bump.colorSpace = THREE.NoColorSpace;
  front.bumpMap = bump;
  front.bumpScale = 0.012;
  back.bumpMap = bump;
  back.bumpScale = 0.008;

  const haloTexture = new THREE.CanvasTexture(haloCanvas());
  haloTexture.colorSpace = THREE.SRGBColorSpace;
  const halo = new THREE.Mesh(
    new THREE.PlaneGeometry(CARD_WIDTH * 2.15, CARD_HEIGHT * 2.15),
    new THREE.MeshBasicMaterial({
      map: haloTexture,
      color: new THREE.Color(rarity.glow),
      transparent: true,
      opacity: rarity.haloOpacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide,
    }),
  );
  halo.position.set(0, CARD_HEIGHT * 0.5, -CARD_DEPTH * 2.4);
  halo.visible = rarity.haloOpacity > 0;
  stage.pivot.add(halo);

  const rim = new THREE.PointLight(new THREE.Color(rarity.glow), rarity.glowStrength * 1.8, 2.8, 2);
  rim.position.set(-CARD_WIDTH * 0.8, CARD_HEIGHT * 0.82, 0.56);
  stage.scene.add(rim);
  const rimBase = rim.intensity;

  stage.frame(CARD_WIDTH, CARD_HEIGHT);
  // Keep the card centered; the slight mesh tilt supplies the physical depth.
  const center = CARD_HEIGHT * 0.5;
  stage.camera.position.set(0, center, Math.max(CARD_WIDTH, CARD_HEIGHT) * 1.8);
  stage.camera.lookAt(0, center, 0);
  if (stage.controls) {
    stage.controls.target.set(0, center, 0);
    stage.controls.update();
  }
  stage.resize();

  let disposed = false;
  let pending = 3;
  let elapsed = 0;

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
    map.anisotropy = Math.min(16, stage.renderer.capabilities.getMaxAnisotropy());
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
    cardSurfaceCanvas(definition).then(
      surfaceCanvas => {
        if (disposed) return;
        const roughness = new THREE.CanvasTexture(surfaceCanvas);
        roughness.colorSpace = THREE.NoColorSpace;
        front.roughnessMap = roughness;
        front.needsUpdate = true;
        settle();
      },
      error => {
        console.warn(`[Tinyrooms] ${error.message}`);
        if (!disposed) settle();
      },
    );
  } else {
    settle();
    settle();
  }
  loadTexture(backUrl, back);

  return {
    faceKey,
    backUrl,
    render(delta) {
      if (disposed) return;
      if (!reducedMotion && rarity.haloOpacity > 0) {
        elapsed += delta;
        const pulse = rarity.key === "legendary" ? 0.2 : rarity.key === "epic" ? 0.14 : 0.06;
        halo.material.opacity = rarity.haloOpacity * (1 + Math.sin(elapsed * 1.7) * pulse);
        rim.intensity = rimBase * (1 + Math.sin(elapsed * 1.7 + 1) * 0.16);
      }
      stage.renderFrame(delta, !interactive && !reducedMotion);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      stage.scene.environment = null;
      environment.dispose();
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
    // Drop viewers whose canvas left the DOM (inventory closed or replaced).
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
