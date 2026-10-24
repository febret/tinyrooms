import * as THREE from "three";

import { cardModelKey, detachBoardTree, positionKey } from "./board-helpers.js";

const SPRITE_HEIGHT = 0.95;
const SPRITE_LIFT = 0.03;
const FALLBACK_ASPECT = 0.78;

let shadowGeometry = null;
let shadowMaterial = null;
let shadowTexture = null;

function groundShadowTexture() {
  if (shadowTexture) return shadowTexture;
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(64, 64, 6, 64, 64, 62);
  gradient.addColorStop(0, "rgba(0,0,0,0.42)");
  gradient.addColorStop(0.55, "rgba(0,0,0,0.22)");
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  shadowTexture = new THREE.CanvasTexture(canvas);
  return shadowTexture;
}

/** One shared ground ellipse so dropped cards sit on the floor like peep stickers. */
function groundShadow() {
  if (!shadowGeometry) shadowGeometry = new THREE.PlaneGeometry(0.85, 0.55);
  if (!shadowMaterial) {
    shadowMaterial = new THREE.MeshBasicMaterial({
      map: groundShadowTexture(),
      transparent: true,
      depthWrite: false,
    });
  }
  const mesh = new THREE.Mesh(shadowGeometry, shadowMaterial);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.y = 0.004;
  return mesh;
}

function applyAspect(sprite, map) {
  const image = map?.image;
  const width = Number(image?.width) || 0;
  const height = Number(image?.height) || 0;
  const aspect = width > 0 && height > 0 ? width / height : FALLBACK_ASPECT;
  sprite.scale.set(SPRITE_HEIGHT * aspect, SPRITE_HEIGHT, 1);
}

/** Room-card scene lifecycle, split out of board.js to keep the renderer small. */
export function createBoardCards({ register, texture, setRecordTarget, invalidateScene, onRemoveGroup }) {
  function add(entry, card) {
    invalidateScene();
    const group = new THREE.Group();
    register(entry, group, "room-card", card.stackId, card.position);
    // Dropped cards render like peep stickers: a camera-facing sprite of the
    // transparent subject art over a soft ground shadow. The card container
    // (background + frame) stays in the inventory/inspection faces.
    const spriteMaterial = new THREE.SpriteMaterial({
      transparent: true,
      alphaTest: 0.05,
      depthWrite: false,
      toneMapped: false,
    });
    const sprite = new THREE.Sprite(spriteMaterial);
    sprite.center.set(0.5, 0);
    sprite.position.y = SPRITE_LIFT;
    sprite.userData = { kind: "room-card", id: card.stackId };
    applyAspect(sprite, null);
    group.add(sprite);
    group.add(groundShadow());
    entry.cards.set(card.stackId, {
      id: card.stackId, group, card, sprite, spriteMaterial, modelKey: cardModelKey(card), positionKey: positionKey(card.position),
      target: group.position.clone(),
    });
    texture(entry, card.definition?.imageUrl, `${card.definition?.label || "Card"} illustration`, map => {
      const record = entry.cards.get(card.stackId);
      if (!record || record.spriteMaterial !== spriteMaterial) return;
      map.colorSpace = THREE.SRGBColorSpace;
      spriteMaterial.map = map;
      spriteMaterial.needsUpdate = true;
      applyAspect(sprite, map);
      invalidateScene();
    });
  }

  function update(entry, record, card) {
    record.card = card;
    setRecordTarget(record, card.position);
  }

  function remove(entry, id) {
    const record = entry.cards.get(id);
    if (!record) return;
    invalidateScene();
    entry.root.remove(record.group);
    detachBoardTree(record.group);
    // The sprite material is this card's own; the shadow mesh and the loaded
    // texture draw on shared caches and stay alive for other copies.
    record.spriteMaterial?.dispose();
    const index = entry.pickables.indexOf(record.group);
    if (index >= 0) entry.pickables.splice(index, 1);
    entry.cards.delete(id);
    onRemoveGroup?.(record.group);
  }

  return { add, update, remove };
}
