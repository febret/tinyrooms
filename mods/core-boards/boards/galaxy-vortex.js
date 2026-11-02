// Abstract particle galaxy/vortex board design.
//
// Selected with `board_design: galaxy-vortex` on a `board_type: diorama`
// room. Four additive particle fields (bright arms, mid stars, dust haze,
// large sparkles) orbit a warm core in the room palette, over a baked nebula
// backdrop. The room's own props (e.g. the tutorial dollhouse) float in the
// eye. Reduced motion freezes the swirl.

import * as THREE from "three";

import { registerBoardDesign } from "#tinyrooms/board/board-designs/registry.js";

export const GALAXY_VORTEX_DESIGN = "galaxy-vortex";

const BASE_PARTICLES = 4500;
const TILT_X = 0.42;
const SPIN_BASE = 0.1;

const LAYER_SPECS = [
  {
    name: "arms", weight: 0.24, seed: 20261101, size: 0.34, opacity: 0.9,
    radius: [0.5, 6.1], radialPower: 0.62, scatter: 0.85, height: 0.34,
    color: "bright", arms: 2, twist: 2.1,
  },
  {
    name: "stars", weight: 0.3, seed: 20261102, size: 0.19, opacity: 0.9,
    radius: [0.35, 6.6], radialPower: 0.78, scatter: 1.25, height: 0.55,
    color: "palette", arms: 2, twist: 1.85,
  },
  {
    name: "dust", weight: 0.4, seed: 20261103, size: 0.1, opacity: 0.62,
    radius: [0.2, 6.9], radialPower: 0.92, scatter: 1.15, height: 0.8,
    color: "cool", arms: 0, twist: 0,
  },
  {
    name: "sparkles", weight: 0.06, seed: 20261104, size: 0.68, opacity: 0.9,
    radius: [0.9, 6.2], radialPower: 1.0, scatter: 1.4, height: 0.9,
    color: "bright", arms: 0, twist: 0,
  },
];

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function mulberry32(seed) {
  let value = seed >>> 0;
  return () => {
    value += 0x6d2b79f5;
    let result = Math.imul(value ^ (value >>> 15), 1 | value);
    result ^= result + Math.imul(result ^ (result >>> 7), 61 | result);
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296;
  };
}

function makeSoftDotTexture() {
  if (typeof document === "undefined" || typeof document.createElement !== "function") {
    const texture = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    texture.needsUpdate = true;
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
  }
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.3, "rgba(255,255,255,0.85)");
  gradient.addColorStop(0.65, "rgba(255,255,255,0.24)");
  gradient.addColorStop(1, "rgba(255,255,255,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function makeRadialMaskTexture() {
  if (typeof document === "undefined" || typeof document.createElement !== "function") {
    const texture = new THREE.DataTexture(new Uint8Array([255, 255, 255, 255]), 1, 1);
    texture.needsUpdate = true;
    return texture;
  }
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  gradient.addColorStop(0, "#ffffff");
  gradient.addColorStop(0.45, "#e8e8e8");
  gradient.addColorStop(0.72, "#6a6a6a");
  gradient.addColorStop(1, "#000000");
  context.fillStyle = gradient;
  context.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

function assetUrl(board, name) {
  const clean = String(name || "").trim();
  if (!clean) return "";
  if (/^(?:https?:)?\//.test(clean)) return clean;
  const base = String(board?.imageUrl || "");
  const slash = base.lastIndexOf("/");
  return slash >= 0 ? `${base.slice(0, slash + 1)}${clean}` : clean;
}

function paletteColors(board, options) {
  const palette = Array.isArray(board?.palette) && board.palette.length > 0
    ? board.palette
    : ["#ebcfaa", "#b97262", "#6faea4"];
  return {
    cream: new THREE.Color(palette[0] || "#ebcfaa"),
    ember: new THREE.Color(palette[1] || "#b97262"),
    tide: new THREE.Color(palette[2] || "#6faea4"),
    white: new THREE.Color("#fff6e6"),
    accent: options?.accent ? new THREE.Color(String(options.accent)) : null,
  };
}

function pickColor(colors, kind, random, target) {
  const pick = random();
  if (kind === "bright") {
    if (pick < 0.1) target.copy(colors.white);
    else if (pick < 0.4) target.copy(colors.cream).lerp(colors.white, 0.22);
    else if (pick < 0.72) target.copy(colors.ember).lerp(colors.white, 0.08);
    else target.copy(colors.tide).lerp(colors.white, 0.16);
  } else if (kind === "cool") {
    if (pick < 0.58) target.copy(colors.tide).lerp(colors.white, 0.14);
    else if (pick < 0.85) target.copy(colors.ember).lerp(colors.white, 0.08);
    else target.copy(colors.cream);
  } else if (pick < 0.3) {
    target.copy(colors.cream);
  } else if (pick < 0.66) {
    target.copy(colors.ember);
  } else {
    target.copy(colors.tide);
  }
  if (colors.accent && random() < 0.12) target.lerp(colors.accent, 0.55);
  target.offsetHSL((random() - 0.5) * 0.04, (random() - 0.5) * 0.18, (random() - 0.5) * 0.12);
}

function createParticleLayer(spec, count, colors, dotTexture, sizeScale) {
  const random = mulberry32(spec.seed);
  const positions = new Float32Array(count * 3);
  const vertexColors = new Float32Array(count * 3);
  const radii = new Float32Array(count);
  const angles = new Float32Array(count);
  const heights = new Float32Array(count);
  const speeds = new Float32Array(count);
  const [radiusMin, radiusMax] = spec.radius;
  const scratch = new THREE.Color();

  for (let index = 0; index < count; index += 1) {
    const radius = radiusMin + Math.pow(random(), spec.radialPower) * (radiusMax - radiusMin);
    if (spec.arms > 0) {
      const arm = index % spec.arms;
      const jitter = (random() - 0.5) * spec.scatter * (0.55 + radius * 0.18);
      angles[index] = (arm / spec.arms) * Math.PI * 2 + radius * spec.twist + jitter;
    } else {
      angles[index] = random() * Math.PI * 2;
    }
    radii[index] = radius;
    heights[index] = (random() - 0.5) * spec.height * (1.15 - radius / radiusMax);
    speeds[index] = SPIN_BASE * (1.9 / (0.4 + radius * 0.4)) * (0.8 + random() * 0.45);
    pickColor(colors, spec.color, random, scratch);
    vertexColors[index * 3] = scratch.r;
    vertexColors[index * 3 + 1] = scratch.g;
    vertexColors[index * 3 + 2] = scratch.b;
  }

  const geometry = new THREE.BufferGeometry();
  const positionAttribute = new THREE.BufferAttribute(positions, 3);
  positionAttribute.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute("position", positionAttribute);
  geometry.setAttribute("color", new THREE.BufferAttribute(vertexColors, 3));
  geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), radiusMax + 1.5);

  const material = new THREE.PointsMaterial({
    size: spec.size * sizeScale,
    map: dotTexture,
    vertexColors: true,
    transparent: true,
    opacity: spec.opacity,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    sizeAttenuation: true,
  });
  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;

  return {
    geometry,
    material,
    points,
    baseSize: spec.size * sizeScale,
    baseOpacity: spec.opacity,
    update(elapsed) {
      for (let index = 0; index < count; index += 1) {
        const angle = angles[index] + elapsed * speeds[index];
        const radius = radii[index];
        positions[index * 3] = Math.cos(angle) * radius;
        positions[index * 3 + 1] = heights[index]
          + Math.sin(elapsed * 0.8 + radius * 1.7 + index * 0.37) * 0.06;
        positions[index * 3 + 2] = Math.sin(angle) * radius;
      }
      positionAttribute.needsUpdate = true;
    },
    dispose() {
      geometry.dispose();
      material.dispose();
    },
  };
}

export function createGalaxyVortexBoard({
  board = {},
  environment = {},
  options = {},
  requestShadow = () => {},
  setExposure = () => {},
} = {}) {
  void environment;
  void requestShadow;
  const group = new THREE.Group();
  group.name = "galaxy-vortex";

  const colors = paletteColors(board, options);
  const dotTexture = makeSoftDotTexture();
  const sizeScale = clamp(Number(options.size) || 1, 0.4, 3);
  const budget = clamp(Number(options.particles) || BASE_PARTICLES, 600, 12000);

  const plane = new THREE.Group();
  plane.rotation.x = TILT_X;
  group.add(plane);

  const backdropUrl = assetUrl(board, options.backdrop);
  const discGeometry = new THREE.CircleGeometry(7.2, 128);
  const maskTexture = makeRadialMaskTexture();
  const discMaterial = new THREE.MeshBasicMaterial({
    color: new THREE.Color("#ffffff"),
    transparent: true,
    opacity: 0.66,
    alphaMap: maskTexture,
    depthWrite: false,
  });
  const disc = new THREE.Mesh(discGeometry, discMaterial);
  disc.rotation.x = -Math.PI / 2;
  disc.visible = false;
  disc.position.y = -0.02;
  plane.add(disc);

  let backdropTexture = null;
  if (backdropUrl) {
    new THREE.TextureLoader().load(
      backdropUrl,
      texture => {
        backdropTexture = texture;
        texture.colorSpace = THREE.SRGBColorSpace;
        discMaterial.map = texture;
        discMaterial.needsUpdate = true;
        disc.visible = true;
      },
      undefined,
      () => {
        backdropTexture = null;
        disc.visible = false;
      },
    );
  }

  const layers = LAYER_SPECS.map(spec => {
    const count = Math.max(40, Math.round(budget * spec.weight));
    const layer = createParticleLayer(spec, count, colors, dotTexture, sizeScale);
    layer.points.rotation.x = 0;
    plane.add(layer.points);
    return layer;
  });

  const glowTexture = makeSoftDotTexture();
  const coreMaterial = new THREE.SpriteMaterial({
    map: glowTexture,
    color: colors.white.clone().lerp(colors.cream, 0.4),
    transparent: true,
    opacity: 0.95,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const core = new THREE.Sprite(coreMaterial);
  core.scale.setScalar(2.2 * sizeScale);
  core.position.y = 0.12;
  group.add(core);

  const glowLight = new THREE.PointLight(colors.cream.clone(), 18, 16, 1.4);
  glowLight.position.set(0, 1.4, 0);
  group.add(glowLight);
  const tealLight = new THREE.PointLight(colors.tide.clone(), 10, 14, 1.6);
  tealLight.position.set(2.6, 0.6, -2.2);
  group.add(tealLight);

  const daylight = {
    sky: new THREE.Color("#171017"),
    ground: new THREE.Color("#08070c"),
    spriteColor: "#ffffff",
    spriteOpacity: 1,
  };

  let roomDark = false;
  let disposed = false;
  let elapsed = 0;

  function layout(time) {
    for (const layer of layers) layer.update(time);
  }

  layout(0);

  function update(delta, { reducedMotion = false } = {}) {
    if (disposed) return {};
    if (!reducedMotion) elapsed += Math.min(Math.max(delta, 0), 0.1);
    layout(elapsed);
    const pulse = 1 + Math.sin(elapsed * 1.4) * 0.08;
    const flicker = 1 + Math.sin(elapsed * 2.1 + 0.7) * 0.05;
    core.scale.setScalar(2.2 * sizeScale * pulse);
    coreMaterial.opacity = (roomDark ? 0.5 : 0.78) * flicker;
    glowLight.intensity = (roomDark ? 9 : 18) * pulse;
    tealLight.intensity = (roomDark ? 5 : 10) * flicker;
    for (const [index, layer] of layers.entries()) {
      const wave = Math.sin(elapsed * (0.7 + index * 0.23) + index * 1.7);
      layer.material.size = layer.baseSize * (1 + wave * 0.07);
      layer.material.opacity = layer.baseOpacity * (roomDark ? 0.7 : 1) * (0.94 + wave * 0.06);
    }
    disc.rotation.z = elapsed * 0.012;
    return {};
  }

  function setSceneLights(lights) {
    setExposure(1.05);
    lights.hemisphere.color.set("#9a86ad");
    lights.hemisphere.groundColor.set("#0c0a10");
    lights.hemisphere.intensity = roomDark ? 0.4 : 0.9;
    lights.sunlight.color.set("#ffd9b0");
    lights.sunlight.intensity = roomDark ? 0.2 : 0.7;
    lights.sunlight.position.set(2.5, 6, 1.5);
    lights.fill.color.set("#6faea4");
    lights.fill.intensity = roomDark ? 0.14 : 0.45;
  }

  return {
    group,
    pickables: [],
    update,
    setSceneLights,
    setRoomDark(value) {
      roomDark = Boolean(value);
    },
    get daylight() {
      return daylight;
    },
    dispose() {
      disposed = true;
      group.remove(plane, core, glowLight, tealLight);
      for (const layer of layers) layer.dispose();
      discGeometry.dispose();
      discMaterial.dispose();
      maskTexture.dispose();
      backdropTexture?.dispose();
      coreMaterial.dispose();
      glowTexture.dispose();
      dotTexture.dispose();
    },
  };
}

registerBoardDesign(GALAXY_VORTEX_DESIGN, createGalaxyVortexBoard);
