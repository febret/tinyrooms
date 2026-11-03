import * as THREE from "three";

import { lightingTint, lightingTintKey } from "./board-lighting.js";
import { boardPosition } from "./board-helpers.js";
import { loadSharedTexture, sharedTexture } from "./board-resources.js";
import { decalCanvas, stinkCanvas } from "../decals.js";

const TOP = 0.045;
const SPRITE_HEIGHT = 1.8;
const FALLBACK_ASPECT = 0.78;

/**
 * Build static billboarded 2D NPC sprites for sprite-mode rooms.
 *
 * Sprites use `THREE.Sprite`, so they always face the camera. Their center sits
 * at the bottom edge so the sticker rests directly on the board floor, matching
 * the authoritative `[x%, y%]` position the server assigns. Sprites never move
 * within a room.
 */
export function createBoardSprites({ textureLoader, invalidate }) {
  function contentRoot(entry) {
    return entry?.content || entry?.root;
  }

  function positionFor(actor) {
    const position = Array.isArray(actor?.spritePosition) ? actor.spritePosition : null;
    if (!position || position.length < 2) return null;
    const target = new THREE.Vector3(...boardPosition(position));
    target.y += TOP;
    return target;
  }

  function syncOverlayTransforms(record) {
    if (!record.sprite) return;
    for (const overlay of [record.decalOverlay, record.stinkOverlay]) {
      if (!overlay) continue;
      overlay.position.copy(record.sprite.position);
      overlay.scale.copy(record.sprite.scale);
    }
  }

  function applyPosition(record, actor) {
    const target = positionFor(actor);
    if (!target) return false;
    record.sprite.position.copy(target);
    syncOverlayTransforms(record);
    return true;
  }

  function applyScale(entry, record, map) {
    const image = map?.image;
    const width = Number(image?.width) || 0;
    const height = Number(image?.height) || 0;
    const aspect = width > 0 && height > 0 ? width / height : FALLBACK_ASPECT;
    const scale = SPRITE_HEIGHT * (Number(entry.spriteScale) > 0 ? Number(entry.spriteScale) : 1);
    record.sprite.scale.set(scale * aspect, scale, 1);
    syncOverlayTransforms(record);
  }

  function applyTint(record) {
    const tint = record.lighting || { color: "#ffffff", opacity: 1 };
    record.material.color.set(tint.color);
    record.material.opacity = tint.opacity;
    for (const overlay of [record.decalOverlay, record.stinkOverlay]) {
      if (!overlay) continue;
      overlay.material.color.set(tint.color);
      overlay.material.opacity = tint.opacity;
    }
  }

  function applyLighting(entry, lighting) {
    if (!entry?.sprites) return false;
    const tint = lightingTint(lighting);
    const key = lightingTintKey(tint);
    let changed = false;
    for (const record of entry.sprites.values()) {
      if (record.lightingKey === key) continue;
      record.lighting = tint;
      record.lightingKey = key;
      applyTint(record);
      changed = true;
    }
    return changed;
  }

  function build(record, entry, actor) {
    const sprite = new THREE.Sprite(record.material);
    sprite.center.set(0.5, 0);
    sprite.visible = false;
    sprite.userData = { kind: "peep", id: record.id };
    contentRoot(entry).add(sprite);
    record.sprite = sprite;
    applyPosition(record, actor);
    applyScale(entry, record, record.material.map);
  }

  function makePickable(entry, record) {
    const sprite = record.sprite;
    if (sprite && !entry.pickables.includes(sprite)) entry.pickables.push(sprite);
  }

  function loadTexture(record, entry, url) {
    record.url = url;
    const cached = sharedTexture(url);
    if (cached) {
      record.material.map = cached;
      record.material.needsUpdate = true;
      record.sprite.visible = true;
      applyScale(entry, record, cached);
      makePickable(entry, record);
      invalidate();
      return;
    }
    loadSharedTexture(url, textureLoader).then(map => {
      if (entry.sprites.get(record.id) !== record) return;
      map.colorSpace = THREE.SRGBColorSpace;
      record.material.map = map;
      record.material.needsUpdate = true;
      record.sprite.visible = true;
      applyScale(entry, record, map);
      makePickable(entry, record);
      invalidate();
    }, () => {
      if (entry.sprites.get(record.id) !== record) return;
      record.failed = true;
      invalidate();
    });
  }

  function add(entry, actor) {
    const id = String(actor.id);
    const material = new THREE.SpriteMaterial({
      transparent: true,
      alphaTest: 0.04,
      depthWrite: false,
      toneMapped: false,
      color: "#ffffff",
      opacity: 1,
    });
    const record = {
      id,
      actor,
      material,
      sprite: null,
      url: "",
      failed: false,
      lighting: null,
      lightingKey: "",
      decalOverlay: null,
      decalKey: "",
      stinkOverlay: null,
      stinkKey: "",
    };
    entry.sprites.set(id, record);
    build(record, entry, actor);
    applyTint(record);
    const url = String(actor.stickerUrl || "");
    if (url) loadTexture(record, entry, url);
    return record;
  }

  function disposeOverlay(entry, record, kind) {
    const overlay = kind === "stink" ? record.stinkOverlay : record.decalOverlay;
    if (!overlay) return;
    contentRoot(entry).remove(overlay);
    overlay.material.map?.dispose();
    overlay.material.dispose();
    if (kind === "stink") {
      record.stinkOverlay = null;
      record.stinkKey = "";
    } else {
      record.decalOverlay = null;
      record.decalKey = "";
    }
  }

  function attachOverlay(entry, record, canvas, kind) {
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const material = new THREE.SpriteMaterial({
      map: texture,
      transparent: true,
      depthWrite: false,
      toneMapped: false,
    });
    const overlay = new THREE.Sprite(material);
    overlay.center.set(0.5, 0);
    overlay.position.copy(record.sprite.position);
    overlay.scale.copy(record.sprite.scale);
    overlay.renderOrder = kind === "stink" ? 2 : 1;
    contentRoot(entry).add(overlay);
    if (kind === "stink") record.stinkOverlay = overlay;
    else record.decalOverlay = overlay;
    applyTint(record);
  }

  function clearDecalOverlay(entry, record) {
    disposeOverlay(entry, record, "decal");
  }

  function clearStinkOverlay(entry, record) {
    disposeOverlay(entry, record, "stink");
  }

  function syncDecalOverlay(entry, record, actor) {
    const decals = Array.isArray(actor.decals) ? actor.decals : [];
    const key = decals.length ? JSON.stringify(decals) : "";
    if (key === record.decalKey) return;
    clearDecalOverlay(entry, record);
    if (!key || !record.sprite) return;
    const canvas = decalCanvas(record.id, decals);
    if (!canvas) return;
    attachOverlay(entry, record, canvas, "decal");
    record.decalKey = key;
  }

  function syncStinkOverlay(entry, record, actor) {
    const stinky = Array.isArray(actor.statuses) && actor.statuses.includes("stinky");
    const key = stinky ? "stinky" : "";
    if (key === record.stinkKey) return;
    clearStinkOverlay(entry, record);
    if (!key || !record.sprite) return;
    attachOverlay(entry, record, stinkCanvas(record.id), "stink");
    record.stinkKey = key;
  }

  function remove(entry, id) {
    const record = entry.sprites.get(id);
    if (!record) return;
    clearDecalOverlay(entry, record);
    clearStinkOverlay(entry, record);
    contentRoot(entry).remove(record.sprite);
    const index = entry.pickables.indexOf(record.sprite);
    if (index >= 0) entry.pickables.splice(index, 1);
    record.material.dispose();
    entry.sprites.delete(id);
    invalidate();
  }

  function update(entry, record, actor) {
    record.actor = actor;
    applyPosition(record, actor);
    const url = String(actor.stickerUrl || "");
    if (url !== record.url) {
      record.failed = false;
      if (url) loadTexture(record, entry, url);
      else {
        record.sprite.visible = false;
        record.url = "";
      }
    }
    syncDecalOverlay(entry, record, actor);
    syncStinkOverlay(entry, record, actor);
  }

  function sync(entry, actors, spriteScale = 1) {
    const nextScale = Number(spriteScale) > 0 ? Number(spriteScale) : 1;
    if (entry.spriteScale !== nextScale) {
      entry.spriteScale = nextScale;
      for (const record of entry.sprites.values()) {
        if (record.sprite) applyScale(entry, record, record.material.map);
      }
    }
    const wanted = new Map();
    for (const actor of Array.isArray(actors) ? actors : []) {
      if (!Array.isArray(actor?.spritePosition) || actor.spritePosition.length < 2) continue;
      const id = String(actor.id || "");
      if (id) wanted.set(id, actor);
    }
    for (const id of [...entry.sprites.keys()]) {
      if (!wanted.has(id)) remove(entry, id);
    }
    for (const [id, actor] of wanted) {
      const existing = entry.sprites.get(id);
      if (existing) update(entry, existing, actor);
      else {
        const record = add(entry, actor);
        syncDecalOverlay(entry, record, actor);
        syncStinkOverlay(entry, record, actor);
      }
    }
  }

  function clear(entry) {
    if (!entry?.sprites) return;
    for (const id of [...entry.sprites.keys()]) remove(entry, id);
  }

  return { sync, clear, applyLighting };
}
