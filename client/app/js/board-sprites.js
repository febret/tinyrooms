import * as THREE from "three";

import { boardPosition } from "./board-helpers.js";
import { loadSharedTexture, sharedTexture } from "./board-resources.js";
import { decalCanvas } from "./decals.js";

const TOP = 0.045;
const SPRITE_HEIGHT = 2.5;
const SPRITE_MOVE_SMOOTHING = 5;
const FALLBACK_ASPECT = 0.78;
const BUBBLE_REFERENCE_PX = 100;

/** Keep a bubble at a fixed size ratio to the peep sprite it belongs to. */
export function spriteBubbleScale(pixelHeight) {
  return Math.max(0.01, (Number(pixelHeight) || 0) / BUBBLE_REFERENCE_PX);
}

/**
 * Build billboarded 2D peep sprites for sprite-mode rooms.
 *
 * Sprites use `THREE.Sprite`, so they always face the camera. Their center sits
 * at the bottom edge so the sticker rests directly on the board floor, matching
 * the authoritative `[x%, y%]` position the server assigns.
 */
export function createBoardSprites({ textureLoader, invalidate }) {
  function targetPosition(position) {
    const target = new THREE.Vector3(...boardPosition(position));
    target.y += TOP;
    return target;
  }

  function applyScale(record, map) {
    const image = map?.image;
    const width = Number(image?.width) || 0;
    const height = Number(image?.height) || 0;
    const aspect = width > 0 && height > 0 ? width / height : FALLBACK_ASPECT;
    record.baseScale = [SPRITE_HEIGHT * aspect, SPRITE_HEIGHT];
    record.sprite.scale.set(record.baseScale[0], record.baseScale[1], 1);
  }

  function build(record, entry) {
    const sprite = new THREE.Sprite(record.material);
    sprite.center.set(0.5, 0);
    sprite.position.copy(record.target);
    sprite.visible = false;
    sprite.userData = { kind: "peep", id: record.id };
    entry.root.add(sprite);
    record.sprite = sprite;
    applyScale(record, record.material.map);
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
      applyScale(record, cached);
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
      applyScale(record, map);
      makePickable(entry, record);
      invalidate();
    }, () => {
      if (entry.sprites.get(record.id) !== record) return;
      record.failed = true;
      invalidate();
    });
  }

  function add(entry, actor, dark) {
    const id = String(actor.id);
    const material = new THREE.SpriteMaterial({
      transparent: true,
      alphaTest: 0.04,
      depthWrite: false,
      toneMapped: false,
      color: dark ? "#8b9194" : "#ffffff",
      opacity: dark ? 0.6 : 1,
    });
    const record = {
      id,
      actor,
      material,
      sprite: null,
      target: targetPosition(actor.spritePosition),
      url: "",
      failed: false,
      dark: Boolean(dark),
      baseScale: [SPRITE_HEIGHT, SPRITE_HEIGHT],
      tint: dark ? "#8b9194" : "#ffffff",
      reaction: null,
      decalOverlay: null,
      decalKey: "",
    };
    entry.sprites.set(id, record);
    build(record, entry);
    const url = String(actor.stickerUrl || "");
    if (url) loadTexture(record, entry, url);
    return record;
  }

  function clearDecalOverlay(entry, record) {
    if (!record.decalOverlay) return;
    entry.root.remove(record.decalOverlay);
    record.decalOverlay.material.map?.dispose();
    record.decalOverlay.material.dispose();
    record.decalOverlay = null;
    record.decalKey = "";
  }

  function syncDecalOverlay(entry, record, actor) {
    const decals = Array.isArray(actor.decals) ? actor.decals : [];
    const key = decals.length ? JSON.stringify(decals) : "";
    if (key === record.decalKey) return;
    clearDecalOverlay(entry, record);
    if (!key || !record.sprite) return;
    const canvas = decalCanvas(record.id, decals);
    if (!canvas) return;
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
    overlay.renderOrder = 1;
    entry.root.add(overlay);
    record.decalOverlay = overlay;
    record.decalKey = key;
  }

  function remove(entry, id) {
    const record = entry.sprites.get(id);
    if (!record) return;
    clearDecalOverlay(entry, record);
    entry.root.remove(record.sprite);
    const index = entry.pickables.indexOf(record.sprite);
    if (index >= 0) entry.pickables.splice(index, 1);
    record.material.dispose();
    entry.sprites.delete(id);
    invalidate();
  }

  function update(entry, record, actor, dark) {
    record.actor = actor;
    record.target.copy(targetPosition(actor.spritePosition));
    if (record.dark !== Boolean(dark)) {
      record.dark = Boolean(dark);
      record.tint = dark ? "#8b9194" : "#ffffff";
      if (!record.reaction) record.material.color.set(record.tint);
      record.material.opacity = dark ? 0.6 : 1;
      record.material.needsUpdate = true;
    }
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
  }

  function sync(entry, actors, dark = false) {
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
      if (existing) update(entry, existing, actor, dark);
      else {
        const record = add(entry, actor, dark);
        syncDecalOverlay(entry, record, actor);
      }
    }
  }

  /**
   * Presentational hit reaction for one sprite.
   *
   * The caller passes an authoritative victim id and paint color; this only
   * tints and pulses the sticker, never decides whether a hit happened.
   */
  function react(entry, id, { color = "#ffffff", duration = 0.5 } = {}) {
    const record = entry?.sprites?.get(String(id));
    if (!record) return false;
    record.reaction = {
      color: String(color || "#ffffff"),
      remaining: Math.max(0.05, Number(duration) || 0.5),
      duration: Math.max(0.05, Number(duration) || 0.5),
    };
    record.material.color.set(record.reaction.color);
    record.material.needsUpdate = true;
    invalidate();
    return true;
  }

  function advance(entry, delta, reducedMotion) {
    const alpha = 1 - Math.exp(-delta * SPRITE_MOVE_SMOOTHING);
    for (const record of entry.sprites.values()) {
      const sprite = record.sprite;
      if (!sprite) continue;
      if (record.reaction) {
        record.reaction.remaining -= delta;
        if (record.reaction.remaining <= 0) {
          record.reaction = null;
          record.material.color.set(record.tint);
          record.material.needsUpdate = true;
          if (record.baseScale) sprite.scale.set(record.baseScale[0], record.baseScale[1], 1);
        } else {
          const progress = 1 - record.reaction.remaining / record.reaction.duration;
          const punch = 1 + 0.18 * Math.sin(Math.PI * progress);
          if (record.baseScale) sprite.scale.set(record.baseScale[0] * punch, record.baseScale[1] * punch, 1);
        }
      }
      if (reducedMotion) {
        sprite.position.copy(record.target);
      } else if (!sprite.position.equals(record.target)) {
        sprite.position.lerp(record.target, alpha);
        if (sprite.position.distanceToSquared(record.target) < 1e-6) sprite.position.copy(record.target);
      }
      if (record.decalOverlay) {
        record.decalOverlay.position.copy(sprite.position);
        record.decalOverlay.scale.copy(sprite.scale);
      }
    }
  }

  function isAnimating(entry) {
    for (const record of entry.sprites.values()) {
      if (record.reaction) return true;
      if (record.sprite && !record.sprite.position.equals(record.target)) return true;
    }
    return false;
  }

  function clear(entry) {
    if (!entry?.sprites) return;
    for (const id of [...entry.sprites.keys()]) remove(entry, id);
  }

  /** Project each visible sprite's head into canvas client coordinates. */
  function anchors(entry, camera, canvas) {
    const result = new Map();
    if (!entry?.sprites?.size || !canvas) return result;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return result;
    camera.updateMatrixWorld();
    const world = new THREE.Vector3();
    const view = new THREE.Vector3();
    const projected = new THREE.Vector3();
    const tanHalfFov = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2);
    for (const record of entry.sprites.values()) {
      const sprite = record.sprite;
      if (!sprite?.visible || record.failed) continue;
      sprite.getWorldPosition(world);
      // A Sprite is camera-facing, so its screen height follows view depth, not
      // the world-space vertical axis. Projecting a world-space top point made
      // bubbles shrink toward nothing as the board rotated to top-down.
      view.copy(world).applyMatrix4(camera.matrixWorldInverse);
      const depth = -view.z;
      if (depth <= 0.05) continue;
      const pixelHeight = sprite.scale.y * bounds.height * (camera.zoom || 1) / (2 * depth * tanHalfFov);
      projected.copy(world).project(camera);
      if (![projected.x, projected.y, projected.z].every(Number.isFinite) || projected.z > 1) continue;
      const x = (projected.x + 1) / 2 * bounds.width + bounds.left;
      const feet = (1 - projected.y) / 2 * bounds.height + bounds.top;
      result.set(record.id, {
        x,
        y: feet - pixelHeight,
        scale: spriteBubbleScale(pixelHeight),
      });
    }
    return result;
  }

  return { sync, advance, isAnimating, clear, anchors, react };
}
