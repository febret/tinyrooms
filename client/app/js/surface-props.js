import * as THREE from "three";
import {
  SIGN_STYLE_IDS,
  renderSignCanvas,
  renderWhiteboardCanvas,
} from "./surface-canvas.js";

/** Whether a prop is rendered procedurally from stored surface content. */
export function isSurfaceProp(prop) {
  const kind = prop?.renderKind || prop?.render_kind;
  return kind === "sign" || kind === "whiteboard";
}

/** Key fields that require rebuilding a surface prop's mesh. */
export function surfaceModelKey(prop) {
  const surface = prop?.surface || {};
  return JSON.stringify([
    prop?.renderKind || prop?.render_kind,
    prop?.signStyle || prop?.sign_style || "wood",
    surface.revision || 0,
    surface.content || {},
  ]);
}

/** Build a framed procedural sign; the board grounds and transforms the group. */
export function createSignProp(prop) {
  const style = SIGN_STYLE_IDS.includes(prop?.signStyle || prop?.sign_style)
    ? (prop.signStyle || prop.sign_style)
    : "wood";
  const canvas = renderSignCanvas(prop?.surface?.content || {}, style);
  return framedSurface(canvas, 2.5, 1.25, style === "paper" ? 0.07 : 0.1);
}

/** Build a framed whiteboard whose texture mirrors the shared vector surface. */
export function createWhiteboardProp(prop) {
  const canvas = renderWhiteboardCanvas(prop?.surface?.content || {});
  return framedSurface(canvas, 2.6, 1.625, 0.09);
}

function framedSurface(canvas, width, height, frameDepth) {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  const group = new THREE.Group();
  const backing = new THREE.Mesh(
    new THREE.BoxGeometry(width + 0.18, height + 0.18, frameDepth),
    new THREE.MeshStandardMaterial({ color: "#332820", roughness: 0.85 }),
  );
  backing.position.y = height / 2;
  backing.castShadow = backing.receiveShadow = true;
  group.add(backing);
  const face = new THREE.Mesh(
    new THREE.PlaneGeometry(width, height),
    new THREE.MeshStandardMaterial({ map: texture, roughness: 0.72 }),
  );
  face.position.set(0, height / 2, frameDepth / 2 + 0.002);
  face.castShadow = face.receiveShadow = true;
  group.add(face);
  return group;
}
