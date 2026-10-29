// Shared GPU resources and the scene-graph primitives built on them.
//
// A room routinely holds dozens of copies of the same prop. Without sharing,
// every instance allocated its own geometry, materials and textures, so the
// resident counts -- and the per-frame draw calls -- grew linearly with the prop
// count even though the assets were identical. Sharing means the renderer
// uploads each asset once and the scene graph holds N references to it.
//
// Entries are never evicted: the set of distinct assets in a world is small and
// bounded by content, whereas evicting mid-session would mean re-uploading
// geometry and rebuilding meshes for props that are still on screen. Anything
// that draws on these caches must therefore be unlinked rather than disposed --
// see `detachBoardTree`.

import * as THREE from "three";

import { boardImageRepeat, FLOOR_HEIGHT, FLOOR_WIDTH } from "./board-helpers.js";

const TOP = 0.045;
const CARD_DIMENSIONS = [0.72, 0.045, 0.72];

export const GHOST_MATERIAL = new THREE.MeshStandardMaterial({
  color: "#7f8a8f",
  roughness: 0.95,
  metalness: 0,
});

// Uniform dark-grey silhouette used for props in a dark room: the whole room
// reads as one flat, barely-lit grey while shapes stay readable against shadows.
export const DARK_MATERIAL = new THREE.MeshStandardMaterial({
  color: "#3a3f42",
  roughness: 1,
  metalness: 0,
  emissive: "#1b2023",
  emissiveIntensity: 0.35,
});

const DARK_FLOOR_COLOR = "#3a3f42";
const DARK_FLOOR_TINT = { emissive: "#1b2023", emissiveIntensity: 0.35 };

const resources = {
  geometries: new Map(),
  materials: new Map(),
  textures: new Map(),
  textureLoads: new Map(),
  modelTextures: new Map(),
};

const TEXTURE_SLOTS = [
  "map",
  "emissiveMap",
  "normalMap",
  "roughnessMap",
  "metalnessMap",
  "aoMap",
  "alphaMap",
];

/** A standard material for board scenery. */
export function material(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...extra });
}

/** One `BoxGeometry` per distinct size, so repeated slabs share a buffer. */
export function sharedBoxGeometry(dimensions) {
  const key = dimensions.join(",");
  let geometry = resources.geometries.get(key);
  if (!geometry) {
    geometry = new THREE.BoxGeometry(...dimensions);
    resources.geometries.set(key, geometry);
  }
  return geometry;
}

/**
 * One card slab geometry with the four edge groups coalesced.
 *
 * A BoxGeometry has six material groups. Cards use the same material for all
 * four edges, so merging those index ranges cuts each card from six draw calls
 * to three without changing its visible faces.
 */
export function sharedCardGeometry() {
  const key = "card";
  let geometry = resources.geometries.get(key);
  if (geometry) return geometry;
  geometry = new THREE.BoxGeometry(...CARD_DIMENSIONS);
  const source = geometry.index.array;
  const order = [0, 1, 4, 5, 2, 3];
  const merged = new source.constructor(source.length);
  let offset = 0;
  for (const groupIndex of order) {
    const group = geometry.groups[groupIndex];
    merged.set(source.subarray(group.start, group.start + group.count), offset);
    offset += group.count;
  }
  geometry.setIndex(new THREE.BufferAttribute(merged, 1));
  geometry.clearGroups();
  geometry.addGroup(0, 24, 0);
  geometry.addGroup(24, 6, 1);
  geometry.addGroup(30, 6, 2);
  resources.geometries.set(key, geometry);
  return geometry;
}

/** One material per colour, for the repeated faces of a room card. */
export function sharedCardMaterial(color) {
  let shared = resources.materials.get(color);
  if (!shared) {
    shared = material(color);
    resources.materials.set(color, shared);
  }
  return shared;
}

/** A texture per URL, so every copy of a card back costs one upload. */
export function sharedTexture(url) {
  return resources.textures.get(url) || null;
}

/**
 * Load one texture per URL, including concurrent first-time requests.
 *
 * A plain cache check followed by `TextureLoader.load` starts a fresh upload
 * for every card/back/sticker that appears before the first request resolves.
 * Returning the same in-flight promise makes every owner share one texture.
 */
export function loadSharedTexture(url, loader) {
  const cached = resources.textures.get(url);
  if (cached) return Promise.resolve(cached);
  let pending = resources.textureLoads.get(url);
  if (pending) return pending;
  pending = new Promise((resolve, reject) => {
    loader.load(url, texture => {
      resources.textures.set(url, texture);
      resources.textureLoads.delete(url);
      resolve(texture);
    }, undefined, error => {
      resources.textureLoads.delete(url);
      reject(error);
    });
  });
  resources.textureLoads.set(url, pending);
  return pending;
}

/**
 * Share the textures of a freshly loaded model with an earlier load of the same asset.
 *
 * GLTFLoader has no cache of its own, so every copy of a prop re-uploads the
 * same images as independent `Texture` objects. That was the single largest
 * source of resident GPU memory in a crowded room: ninety copies of one prop
 * held ninety textures before this, and one after.
 *
 * The swap is confined to texture residency. Geometry, materials, the scene
 * graph and the loader's own lifecycle are left alone, which keeps this
 * independent of how prop records are created and torn down.
 */
export function shareModelTextures(model, modelUrl) {
  let canonical = resources.modelTextures.get(modelUrl);
  if (!canonical) {
    canonical = new Map();
    resources.modelTextures.set(modelUrl, canonical);
  }
  model.traverse(node => {
    if (!node.isMesh || !node.material) return;
    const materials = Array.isArray(node.material) ? node.material : [node.material];
    for (const item of materials) {
      for (const slot of TEXTURE_SLOTS) {
        const texture = item[slot];
        if (!texture?.isTexture) continue;
        const key = `${item.name || ""}|${slot}|${textureKey(item, texture)}`;
        const existing = canonical.get(key);
        if (existing && existing !== texture) {
          item[slot] = existing;
          item.needsUpdate = true;
          closeTexture(texture);
        } else if (!existing) {
          canonical.set(key, texture);
        }
      }
    }
  });
}

/**
 * A stable identity for a texture slot across independently parsed loads.
 *
 * A GLB embeds its images, so two parses of the same asset produce distinct
 * `ImageBitmap`s with no URL to match on. Within one asset the material name,
 * the slot and the image dimensions identify the texture reliably enough, and
 * the material colour disambiguates same-named materials that differ in tint.
 */
function textureKey(material, texture) {
  const image = texture.image;
  const size = image ? `${image.width}x${image.height}` : "embedded";
  let colour = "";
  try {
    colour = material.color ? material.color.getHexString() : "";
  } catch {
    colour = "";
  }
  return `${size}|${colour}`;
}

/** Release a texture and the decoded image behind it, if it owns one. */
function closeTexture(texture) {
  const data = texture.source?.data;
  texture.dispose();
  if (data && typeof data.close === "function") data.close();
}

/** Add a box mesh, sharing its geometry by size. */
export function box(parent, dimensions, position, materials) {
  const mesh = new THREE.Mesh(sharedBoxGeometry(dimensions), materials);
  mesh.position.set(...position);
  mesh.castShadow = mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}


export function makeFloor(board) {
  const group = new THREE.Group();
  const dark = Boolean(board.dark);
  const slabMaterials = dark
    ? [material(DARK_FLOOR_COLOR, DARK_FLOOR_TINT), material(DARK_FLOOR_COLOR, DARK_FLOOR_TINT), material(DARK_FLOOR_COLOR, DARK_FLOOR_TINT)]
    : [
        material("#62422d"),
        material("#a76e38"),
        material("#bca076"),
      ];
  box(group, [12.45, 0.35, 10.45], [0, -0.24, 0], slabMaterials[0]);
  box(group, [12.5, 0.12, 10.5], [0, -0.08, 0], slabMaterials[1]);
  box(group, [12.12, 0.07, 10.12], [0, -0.005, 0], slabMaterials[2]);
  const geometry = new THREE.PlaneGeometry(FLOOR_WIDTH, FLOOR_HEIGHT);
  const planeMaterial = material(dark ? DARK_FLOOR_COLOR : (board.palette?.[0] || "#d4be94"), dark ? DARK_FLOOR_TINT : {});
  const floor = new THREE.Mesh(geometry, planeMaterial);
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = TOP;
  floor.receiveShadow = true;
  group.add(floor);
  // The slab geometry is the shared box cache and the floor artwork texture is
  // the shared texture cache, so neither is released here; the per-floor
  // materials and the one plane buffer are this floor's own.
  const dispose = () => {
    for (const item of slabMaterials) item.dispose();
    planeMaterial.dispose();
    geometry.dispose();
  };
  return { group, floor, dispose };
}

export function floorKey(board) {
  return JSON.stringify([board.type, board.imageUrl, board.imageStyle, board.palette, board.dark]);
}

/** Apply the room's board image style by wrapping and repeating the floor texture. */
export function applyFloorImageStyle(map, style) {
  const repeat = boardImageRepeat(style, map.image?.width, map.image?.height);
  if (!repeat) return;
  map.wrapS = repeat.wrapWidth ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  map.wrapT = repeat.wrapHeight ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  map.repeat.set(repeat.repeatX, repeat.repeatY);
  map.needsUpdate = true;
}

/**
 * Apply a record's current material override.
 *
 * Ghosting (editor drags) and darkening (unlit rooms) both replace every mesh
 * material, so they share one override slot: the dark silhouette wins in a dark
 * room, otherwise the ghost look applies while dragging. `record` owns `model`,
 * `ghosted`, `darkened`, `materials` and `override`.
 */
function applyMaterialOverride(record) {
  const override = record.darkened ? DARK_MATERIAL : (record.ghosted ? GHOST_MATERIAL : null);
  if (record.override === override) return;
  if (record.materials) {
    for (const [node, original] of record.materials) node.material = original;
    record.materials = null;
  }
  record.override = override;
  if (override && record.model) {
    record.materials = [];
    record.model.traverse(node => {
      if (node.isMesh && node.material) {
        record.materials.push([node, node.material]);
        node.material = override;
      }
    });
  }
}

/** Swap a loaded model's materials for the gray ghost look, or restore the originals. */
export function setGhosted(record, ghosted) {
  if (record.ghosted === ghosted) return;
  record.ghosted = ghosted;
  applyMaterialOverride(record);
}

/** Swap a loaded model's materials for the dark silhouette, or restore the originals. */
export function setDarkened(record, darkened) {
  if (record.darkened === darkened) return;
  record.darkened = darkened;
  applyMaterialOverride(record);
}

export function unavailableMarker(parent) {
  const marker = new THREE.Mesh(
    new THREE.OctahedronGeometry(0.28),
    material("#e89a70", { wireframe: true }),
  );
  marker.position.y = 0.4;
  parent.add(marker);
  return marker;
}

const PROP_LIGHT_GLOW_INTENSITY = 1.4;
const PROP_LIGHT_GLOW_WHITE = new THREE.Color("#ffffff");
const PROP_LIGHT_GLOW_FALLBACK = { fixture: "#ffe2b0", window: "#d8e7ff" };

/**
 * Make a light fixture or window self-illuminated.
 *
 * Scene point lights are often inside the fixture (or behind the window glass),
 * so the prop itself can sit in its own shadow. Driving the mesh's emissive
 * channel keeps the source visibly bright from every angle and camera rotation.
 * Original emissive settings are retained for when the light switches off.
 */
export function setPropLightGlow(record, light) {
  if (!record?.model) return;
  const active = Boolean(light && light.kind && light.on !== false);
  const key = active
    ? `${light.kind}|${light.color || PROP_LIGHT_GLOW_FALLBACK[light.kind] || "#ffffff"}`
    : "";
  if (record.lightGlowKey === key) return;
  record.lightGlowKey = key;
  if (!record.lightGlowMaterials) {
    record.lightGlowMaterials = [];
    const seen = new Set();
    record.model.traverse(node => {
      if (!node.isMesh || !node.material) return;
      for (const item of Array.isArray(node.material) ? node.material : [node.material]) {
        if (seen.has(item) || !item.emissive) continue;
        seen.add(item);
        record.lightGlowMaterials.push({
          material: item,
          emissive: item.emissive.clone(),
          emissiveIntensity: item.emissiveIntensity,
          emissiveMap: item.emissiveMap || null,
        });
      }
    });
  }
  const glow = active
    ? new THREE.Color(light.color || PROP_LIGHT_GLOW_FALLBACK[light.kind] || "#ffffff")
      .lerp(PROP_LIGHT_GLOW_WHITE, 0.45)
    : null;
  for (const saved of record.lightGlowMaterials) {
    const item = saved.material;
    if (glow) {
      item.emissive.copy(glow);
      item.emissiveIntensity = PROP_LIGHT_GLOW_INTENSITY;
      if (item.emissiveMap !== item.map) {
        item.emissiveMap = item.map;
        item.needsUpdate = true;
      }
    } else {
      item.emissive.copy(saved.emissive);
      item.emissiveIntensity = saved.emissiveIntensity;
      if (item.emissiveMap !== saved.emissiveMap) {
        item.emissiveMap = saved.emissiveMap;
        item.needsUpdate = true;
      }
    }
  }
}
