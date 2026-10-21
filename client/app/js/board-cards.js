import * as THREE from "three";

import { cardModelKey, detachBoardTree, positionKey } from "./board-helpers.js";
import { material, sharedCardGeometry, sharedCardMaterial } from "./board-resources.js";

/** Room-card scene lifecycle, split out of board.js to keep the renderer small. */
export function createBoardCards({ cardBackUrl, register, texture, setRecordTarget, invalidateScene, onRemoveGroup }) {
  function add(entry, card) {
    invalidateScene();
    const group = new THREE.Group();
    register(entry, group, "room-card", card.stackId, card.position);
    // The edge and back materials are identical for every card, so they are
    // shared; only the front carries a card-specific texture and owns its
    // material, so the record keeps a handle to release it.
    const edge = sharedCardMaterial("#d5b887");
    const back = sharedCardMaterial("#193e55");
    const front = material("#fff7e3");
    entry.cards.set(card.stackId, {
      id: card.stackId, group, card, front, modelKey: cardModelKey(card), positionKey: positionKey(card.position),
      target: group.position.clone(),
    });
    // BoxGeometry's +Y/-Y groups are the upper/lower faces, not +Z/-Z.
    // Room cards are square illustration tiles; the full composed face is
    // reserved for inspection, previews, and the inventory (card-face.js).
    const mesh = new THREE.Mesh(sharedCardGeometry(), [edge, front, back]);
    mesh.position.set(0, 0.028, 0);
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.rotation.y = -0.08;
    group.add(mesh);
    texture(entry, card.definition?.imageUrl, `${card.definition?.label || "Card"} illustration`, map => {
      if (entry.cards.get(card.stackId)?.front !== front) return;
      front.map = map;
      front.color.set("#ffffff");
      front.needsUpdate = true;
    });
    texture(entry, cardBackUrl, "card back artwork", map => {
      if (entry.cards.get(card.stackId)?.front !== front) return;
      back.map = map;
      back.color.set("#ffffff");
      back.needsUpdate = true;
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
    // The card's own front material is the one thing in the group the shared
    // caches did not hand out, so it is the one thing to release.
    record.front?.dispose();
    const index = entry.pickables.indexOf(record.group);
    if (index >= 0) entry.pickables.splice(index, 1);
    entry.cards.delete(id);
    onRemoveGroup?.(record.group);
  }

  return { add, update, remove };
}
