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

export const GHOST_MATERIAL = new THREE.MeshStandardMaterial({
  color: "#7f8a8f",
  roughness: 0.95,
  metalness: 0,
});

const resources = {
  geometries: new Map(),
  materials: new Map(),
  textures: new Map(),
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

export function rememberTexture(url, texture) {
  resources.textures.set(url, texture);
  return texture;
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
  box(group, [12.45, 0.35, 10.45], [0, -0.24, 0], material("#62422d"));
  box(group, [12.5, 0.12, 10.5], [0, -0.08, 0], material("#a76e38"));
  box(group, [12.12, 0.07, 10.12], [0, -0.005, 0], material("#bca076"));
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(FLOOR_WIDTH, FLOOR_HEIGHT),
    material(board.palette?.[0] || "#d4be94"),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = TOP;
  floor.receiveShadow = true;
  group.add(floor);
  return { group, floor };
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

export function unavailableMarker(parent) {
  const marker = new THREE.Mesh(
    new THREE.OctahedronGeometry(0.28),
    material("#e89a70", { wireframe: true }),
  );
  marker.position.y = 0.4;
  parent.add(marker);
  return marker;
}
