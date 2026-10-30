import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import { GRID_SIZE, GRID_SPACING, planShowcase, selectShowcaseProps } from "./entry-showcase-layout.js";
import { withBase } from "../../app/js/base-path.js";

const TILE_HEIGHT = 0.2;
const TILE_RADIUS = 0.34;
const MAX_CONCURRENT_LOADS = 3;

function roundedTileGeometry(width, depth, height, radius) {
  const shape = new THREE.Shape();
  const left = -width / 2;
  const right = width / 2;
  const bottom = -depth / 2;
  const top = depth / 2;
  shape.moveTo(left + radius, bottom);
  shape.lineTo(right - radius, bottom);
  shape.quadraticCurveTo(right, bottom, right, bottom + radius);
  shape.lineTo(right, top - radius);
  shape.quadraticCurveTo(right, top, right - radius, top);
  shape.lineTo(left + radius, top);
  shape.quadraticCurveTo(left, top, left, top - radius);
  shape.lineTo(left, bottom + radius);
  shape.quadraticCurveTo(left, bottom, left + radius, bottom);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: height,
    bevelEnabled: true,
    bevelThickness: 0.045,
    bevelSize: 0.045,
    bevelSegments: 2,
    curveSegments: 4,
  });
  geometry.rotateX(-Math.PI / 2);
  geometry.computeVertexNormals();
  return geometry;
}

function createShadowTexture() {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(size / 2, size / 2, 2, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(18, 59, 68, 0.34)");
  gradient.addColorStop(0.55, "rgba(18, 59, 68, 0.16)");
  gradient.addColorStop(1, "rgba(18, 59, 68, 0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createSparkleTexture() {
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255, 255, 255, 1)");
  gradient.addColorStop(0.35, "rgba(255, 247, 214, 0.9)");
  gradient.addColorStop(1, "rgba(255, 255, 255, 0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function lighten(hex, amount = 0.3) {
  return new THREE.Color(hex).lerp(new THREE.Color("#fff8ea"), amount);
}

function createSparkles() {
  const count = 30;
  const positions = [];
  const colors = [];
  for (let index = 0; index < count; index += 1) {
    const angle = (index / count) * Math.PI * 2;
    const radius = 5.5 + (index % 5) * 1.1;
    positions.push(
      Math.cos(angle) * radius + (index % 3) * 0.4,
      1.2 + (index % 7) * 0.72,
      Math.sin(angle) * radius - 1.5,
    );
    const color = new THREE.Color(index % 2 ? "#fff3c4" : "#ffffff");
    colors.push(color.r, color.g, color.b);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  const material = new THREE.PointsMaterial({
    size: 0.16,
    map: createSparkleTexture(),
    transparent: true,
    opacity: 0.8,
    depthWrite: false,
    vertexColors: true,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });
  return new THREE.Points(geometry, material);
}

export function initEntryShowcase({ canvas, props, reducedMotion = false }) {
  if (!canvas) return null;
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: true,
      powerPreference: "high-performance",
    });
  } catch {
    canvas.classList.add("is-unavailable");
    return null;
  }

  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
  const world = new THREE.Group();
  const sparkles = createSparkles();
  scene.add(world);
  world.add(sparkles);

  scene.add(new THREE.HemisphereLight("#fff2cf", "#4b8f85", 1.25));
  const key = new THREE.DirectionalLight("#fff1d0", 2.15);
  key.position.set(6, 10, 8);
  scene.add(key);
  const fill = new THREE.DirectionalLight("#a9d9ff", 0.9);
  fill.position.set(-7, 4, -5);
  scene.add(fill);

  const shadowTexture = createShadowTexture();
  const shadowMaterial = new THREE.MeshBasicMaterial({
    map: shadowTexture,
    transparent: true,
    depthWrite: false,
    opacity: 0.75,
  });
  const shadowGeometry = new THREE.PlaneGeometry(1.7, 1.7);
  const tileGeometry = roundedTileGeometry(GRID_SPACING - 0.22, GRID_SPACING - 0.22, TILE_HEIGHT, TILE_RADIUS);
  const baseGeometry = roundedTileGeometry(
    GRID_SIZE * GRID_SPACING + 0.55,
    GRID_SIZE * GRID_SPACING + 0.55,
    0.42,
    0.7,
  );
  const baseMaterial = new THREE.MeshStandardMaterial({
    color: "#fff1cf",
    roughness: 0.92,
    metalness: 0,
  });
  const base = new THREE.Mesh(baseGeometry, baseMaterial);
  base.position.y = -0.44;
  world.add(base);

  const tiles = [];
  const tileBySlot = new Map();
  const cells = new Map();
  const entries = planShowcase(props);
  const occupied = new Set(entries.map(entry => `${entry.col},${entry.row}`));
  const tileMaterials = new Map();
  const loader = new GLTFLoader();
  const placeholders = [];
  const loadedProps = [];
  let disposed = false;
  let animationFrame = null;
  let lastFrame = 0;
  let startedAt = performance.now();
  let compact = window.innerWidth < 900;

  function tileMaterial(color) {
    const hex = color.getHexString();
    if (!tileMaterials.has(hex)) {
      tileMaterials.set(hex, new THREE.MeshStandardMaterial({
        color,
        roughness: 0.86,
        metalness: 0,
      }));
    }
    return tileMaterials.get(hex);
  }

  for (let row = 0; row < GRID_SIZE; row += 1) {
    for (let col = 0; col < GRID_SIZE; col += 1) {
      const palette = entries.find(entry => entry.col === col && entry.row === row)?.palette;
      const cell = new THREE.Group();
      const offset = (GRID_SIZE - 1) / 2;
      cell.position.set((col - offset) * GRID_SPACING, 0, (row - offset) * GRID_SPACING);
      const tile = new THREE.Mesh(tileGeometry, tileMaterial(lighten(palette?.tile || "#ffe6bf", 0.18)));
      cell.add(tile);
      const shadow = new THREE.Mesh(shadowGeometry, shadowMaterial);
      shadow.rotation.x = -Math.PI / 2;
      shadow.position.y = TILE_HEIGHT + 0.012;
      cell.add(shadow);
      if (!occupied.has(`${col},${row}`)) {
        const pebble = new THREE.Mesh(
          new THREE.IcosahedronGeometry(0.11 + ((col + row) % 3) * 0.035, 0),
          new THREE.MeshStandardMaterial({
            color: lighten(palette?.tile || "#ffe6bf", 0.05),
            emissive: lighten(palette?.glow || "#ffcf5a", 0.1),
            emissiveIntensity: 0.22,
            roughness: 0.5,
          }),
        );
        pebble.position.set((col % 2 ? 0.42 : -0.42), TILE_HEIGHT + 0.12, row % 2 ? 0.35 : -0.35);
        cell.add(pebble);
      }
      world.add(cell);
      tiles.push({ cell, phase: (col + row) * 0.55 });
      tileBySlot.set(`${col},${row}`, cell);
    }
  }

  function createPlaceholder(entry) {
    const group = new THREE.Group();
    const gem = new THREE.Mesh(
      new THREE.IcosahedronGeometry(0.28, 0),
      new THREE.MeshStandardMaterial({
        color: entry.palette.pedestal,
        emissive: entry.palette.glow,
        emissiveIntensity: 0.3,
        roughness: 0.45,
      }),
    );
    gem.position.y = 0.62;
    group.add(gem);
    group.userData.gem = gem;
    return group;
  }

  function normalizeModel(model, entry) {
    const bounds = new THREE.Box3().setFromObject(model);
    if (bounds.isEmpty()) return null;
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const heightScale = entry.targetHeight / Math.max(size.y, 0.001);
    const footprintScale = 1.65 / Math.max(size.x, size.z, 0.001);
    const scale = Math.min(heightScale, footprintScale);
    model.scale.setScalar(scale);
    model.position.set(-center.x * scale, -bounds.min.y * scale, -center.z * scale);
    model.traverse(node => {
      if (node.isMesh) {
        node.castShadow = false;
        node.receiveShadow = false;
      }
    });
    return model;
  }

  async function loadOne(entry) {
    const target = cells.get(entry.id);
    if (!target) return;
    const placeholder = createPlaceholder(entry);
    target.content.add(placeholder);
    placeholders.push(placeholder);
    try {
      const gltf = await loader.loadAsync(withBase(entry.model_url));
      if (disposed) return;
      const model = normalizeModel(gltf.scene, entry);
      if (!model) return;
      const holder = new THREE.Group();
      holder.position.y = TILE_HEIGHT + 0.13;
      holder.add(model);
      holder.scale.setScalar(reducedMotion ? 1 : 0.001);
      target.content.remove(placeholder);
      target.content.add(holder);
      loadedProps.push({ entry, holder, appear: reducedMotion ? 1 : 0 });
      renderFrame(0);
    } catch {
      // Keep the gem placeholder so a missing model never leaves an empty tile.
    }
  }

  async function loadModels() {
    const queue = entries.slice();
    const workers = Array.from({ length: Math.min(MAX_CONCURRENT_LOADS, queue.length) }, async () => {
      while (queue.length && !disposed) {
        const entry = queue.shift();
        await loadOne(entry);
      }
    });
    await Promise.all(workers);
    if (!disposed) renderFrame(0);
  }

  for (const entry of entries) {
    const cell = tileBySlot.get(`${entry.col},${entry.row}`);
    if (!cell) continue;
    const content = new THREE.Group();
    const pedestal = new THREE.Mesh(
      new THREE.CylinderGeometry(0.56, 0.63, 0.1, 24),
      new THREE.MeshStandardMaterial({ color: entry.palette.pedestal, roughness: 0.75 }),
    );
    pedestal.position.y = TILE_HEIGHT + 0.04;
    content.add(pedestal);
    const ring = new THREE.Mesh(
      new THREE.TorusGeometry(0.58, 0.025, 6, 32),
      new THREE.MeshBasicMaterial({ color: entry.palette.glow, transparent: true, opacity: 0.72 }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = TILE_HEIGHT + 0.1;
    content.add(ring);
    cell.add(content);
    cells.set(entry.id, { cell, content, entry });
  }

  function setCompact(value) {
    compact = value;
    const visible = new Set(selectShowcaseProps(props, { compact }).map(prop => prop.id));
    for (const [id, target] of cells) target.cell.visible = !compact || visible.has(id);
  }

  function layout() {
    const width = window.innerWidth;
    const height = window.innerHeight;
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, width < 900 ? 1.5 : 1.75));
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    setCompact(width < 900);
    const card = document.querySelector(".entry-card");
    if (width >= 900 && card) {
      const rect = card.getBoundingClientRect();
      const distance = 19;
      const visibleHeight = 2 * distance * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
      const worldPerPixel = visibleHeight / height;
      world.position.set((rect.left / 2 - width / 2) * worldPerPixel, 0, 0);
      world.scale.setScalar(1);
      camera.position.set(0, 11.5, 16.5);
      camera.lookAt(0, 0.4, 0);
    } else {
      world.position.set(0, 1.6, 0);
      world.scale.setScalar(0.84);
      camera.position.set(0, 12.8, 19);
      camera.lookAt(0, 1.2, 1);
    }
    renderFrame(0);
  }

  function easeOutCubic(value) {
    return 1 - Math.pow(1 - Math.min(1, Math.max(0, value)), 3);
  }

  function update(elapsed, delta) {
    for (const tile of tiles) {
      tile.cell.position.y = Math.sin(elapsed * 0.8 + tile.phase) * 0.025;
    }
    for (const placeholder of placeholders) {
      if (!placeholder.parent) continue;
      placeholder.userData.gem.rotation.y += delta * 1.1;
      placeholder.userData.gem.position.y = 0.62 + Math.sin(elapsed * 1.8) * 0.045;
    }
    for (const prop of loadedProps) {
      if (prop.appear < 1) prop.appear = Math.min(1, prop.appear + delta * 2.3);
      prop.holder.scale.setScalar(easeOutCubic(prop.appear));
      prop.holder.rotation.y = prop.entry.phase + elapsed * prop.entry.spin;
      prop.holder.position.y = TILE_HEIGHT + 0.13
        + Math.sin(elapsed * 1.25 + prop.entry.bobPhase) * prop.entry.bobAmount;
    }
    sparkles.rotation.y = elapsed * 0.035;
    sparkles.position.y = Math.sin(elapsed * 0.5) * 0.12;
    world.rotation.y = -0.12 + Math.sin(elapsed * 0.22) * 0.025;
  }

  function renderFrame(delta) {
    if (disposed) return;
    const elapsed = (performance.now() - startedAt) / 1000;
    update(elapsed, delta);
    renderer.render(scene, camera);
  }

  function tick(now) {
    if (disposed) return;
    const delta = Math.min(0.05, Math.max(0, (now - lastFrame) / 1000));
    lastFrame = now;
    renderFrame(delta);
    animationFrame = requestAnimationFrame(tick);
  }

  function start() {
    if (disposed || reducedMotion || animationFrame !== null) return;
    lastFrame = performance.now();
    animationFrame = requestAnimationFrame(tick);
  }

  function stop() {
    if (animationFrame !== null) cancelAnimationFrame(animationFrame);
    animationFrame = null;
  }

  function handleVisibility() {
    if (document.hidden) stop();
    else start();
  }

  layout();
  renderer.render(scene, camera);
  canvas.classList.add("is-ready");
  start();
  void loadModels();

  window.addEventListener("resize", layout);
  document.addEventListener("visibilitychange", handleVisibility);

  return {
    dispose() {
      if (disposed) return;
      disposed = true;
      stop();
      window.removeEventListener("resize", layout);
      document.removeEventListener("visibilitychange", handleVisibility);
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
