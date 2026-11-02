import * as THREE from "three";
import { withBase } from "./base-path.js";

const WALL_RENDER_KIND = "wall";
const TEXTURE_ROOT = "/app/assets/textures";

const WALL_LENGTH = 3.0;
const WALL_HEIGHT = 2.7;
const WALL_THICKNESS = 0.12;
const TRIM_DEPTH = WALL_THICKNESS + 0.05;

const WALL_TEXTURE_FILES = {
  plaster: "wall-plaster.png",
  wallpaper: "wall-wallpaper.png",
  brick: "wall-brick.png",
  "whitewashed-brick": "wall-brick-whitewashed.png",
  stone: "wall-stone.png",
  "river-rock": "wall-river-rock.png",
  concrete: "wall-concrete.png",
  wood: "wall-wood.png",
  bamboo: "wall-bamboo.png",
  "subway-tile": "wall-subway-tile.png",
  beadboard: "wall-beadboard.png",
  bone: "wall-bone.png",
};

const DEFAULT_WALL_STYLE = {
  texture: "plaster",
  finish: "baseboard",
  main: "#f1eadb",
  accent: "#b9a889",
};

const WALL_FINISHES = new Set(["none", "baseboard", "crown", "crown-base", "wainscot"]);

const textureCache = new Map();
let textureLoader = null;

/** Whether a prop is rendered from the built-in procedural wall geometry. */
export function isWallProp(prop) {
  const kind = prop?.renderKind || prop?.render_kind;
  return kind === WALL_RENDER_KIND;
}

/** Merge an authored wall recipe over the built-in defaults. */
export function resolveWallStyle(prop) {
  const recipe = prop?.wallStyle || prop?.wall_style || {};
  return {
    texture: typeof recipe.texture === "string" && recipe.texture ? recipe.texture : DEFAULT_WALL_STYLE.texture,
    finish: typeof recipe.finish === "string" && WALL_FINISHES.has(recipe.finish) ? recipe.finish : DEFAULT_WALL_STYLE.finish,
    main: typeof recipe.main === "string" && recipe.main ? recipe.main : DEFAULT_WALL_STYLE.main,
    accent: typeof recipe.accent === "string" && recipe.accent ? recipe.accent : DEFAULT_WALL_STYLE.accent,
  };
}

/** Key fields that require rebuilding a wall prop's mesh. */
export function wallPropModelKey(prop) {
  return JSON.stringify([prop?.renderKind || prop?.render_kind, resolveWallStyle(prop)]);
}

/** Load (and cache) the baked surface texture for a wall. */
export function loadWallTexture(textureId) {
  if (!textureId || !WALL_TEXTURE_FILES[textureId]) {
    return Promise.resolve(null);
  }
  if (!textureCache.has(textureId)) {
    if (!textureLoader) textureLoader = new THREE.TextureLoader();
    const url = withBase(`${TEXTURE_ROOT}/${WALL_TEXTURE_FILES[textureId]}`);
    textureCache.set(textureId, textureLoader.loadAsync(url).then(texture => {
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.wrapS = THREE.RepeatWrapping;
      texture.wrapT = THREE.RepeatWrapping;
      return texture;
    }).catch(() => null));
  }
  return textureCache.get(textureId);
}

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: options.roughness ?? 0.68,
    metalness: options.metalness ?? 0,
    ...(options.map ? { map: options.map } : {}),
  });
}

function part(geometry, color, x, y, z, options = {}) {
  const mesh = new THREE.Mesh(geometry, material(color, options));
  mesh.position.set(x, y, z);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}

function trimBox(length, height, y, color, z = 0) {
  return part(new THREE.BoxGeometry(length, height, TRIM_DEPTH), color, 0, y, z, { roughness: 0.55 });
}

function addBaseboard(group, style) {
  group.add(trimBox(WALL_LENGTH + 0.04, 0.18, 0.09, style.main));
  group.add(trimBox(WALL_LENGTH + 0.08, 0.045, 0.2, style.accent));
}

function addCrown(group, style) {
  group.add(trimBox(WALL_LENGTH + 0.04, 0.2, WALL_HEIGHT - 0.1, style.main));
  group.add(trimBox(WALL_LENGTH + 0.08, 0.05, WALL_HEIGHT - 0.22, style.accent));
}

function addWainscot(group, style) {
  addBaseboard(group, style);
  group.add(trimBox(WALL_LENGTH + 0.02, 0.88, 0.72, style.accent, 0.004));
  group.add(trimBox(WALL_LENGTH + 0.04, 0.09, 1.2, style.main, 0.008));
  group.add(trimBox(WALL_LENGTH + 0.08, 0.035, 1.26, style.accent, 0.012));
}

function applyFinish(group, style) {
  if (style.finish === "baseboard") addBaseboard(group, style);
  else if (style.finish === "crown") addCrown(group, style);
  else if (style.finish === "crown-base") {
    addBaseboard(group, style);
    addCrown(group, style);
  } else if (style.finish === "wainscot") addWainscot(group, style);
}

/** Tile the shared wall texture by scaling the panel's per-instance UVs. */
function updatePanelUvs(panel, lengthScale) {
  const base = panel?.userData?.wallBaseUv;
  const uv = panel?.geometry?.attributes?.uv;
  if (!base || !uv) return;
  const scale = Number(lengthScale) || 1;
  for (let index = 0; index < uv.count; index += 1) {
    uv.setX(index, base[index * 2] * scale);
    uv.setY(index, base[index * 2 + 1]);
  }
  uv.needsUpdate = true;
}

/** Apply a wall's length multiplier without changing its height or thickness. */
export function applyWallLength(group, lengthScale) {
  const scale = Math.max(0.05, Number(lengthScale) || 1);
  group.scale.set(scale, 1, 1);
  group.traverse(node => {
    if (node.userData?.wallPanel) updatePanelUvs(node, scale);
  });
}

/**
 * Build a procedural wall panel, grounded on y=0 with its long axis on local X.
 * `textures` maps texture ids to loaded THREE textures (or null).
 */
export function createWallProp(prop, textures = {}) {
  const style = resolveWallStyle(prop);
  const group = new THREE.Group();
  const geometry = new THREE.BoxGeometry(WALL_LENGTH, WALL_HEIGHT, WALL_THICKNESS);
  const panel = part(geometry, "#ffffff", 0, WALL_HEIGHT / 2, 0, { map: textures[style.texture] || null, roughness: 0.72 });
  panel.userData.wallPanel = true;
  panel.userData.wallBaseUv = Float32Array.from(geometry.attributes.uv.array);
  group.add(panel);
  applyFinish(group, style);
  return group;
}
