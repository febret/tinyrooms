import * as THREE from "three";
import {
  SIGN_STYLE_IDS,
  renderSignCanvas,
  renderWhiteboardCanvas,
} from "./surface-canvas.js";
import { frameLayout, normalizeColor, normalizeFrame } from "./whiteboard-frame.js";

/** Whether a prop is rendered procedurally from stored surface content. */
export function isSurfaceProp(prop) {
  const kind = prop?.renderKind || prop?.render_kind;
  return kind === "sign" || kind === "whiteboard";
}

/** Key fields that require rebuilding a surface prop's mesh. */
export function surfaceModelKey(prop) {
  const kind = prop?.renderKind || prop?.render_kind;
  const surface = prop?.surface || {};
  if (kind === "whiteboard") {
    const content = surface.content || {};
    return JSON.stringify([
      kind,
      surface.revision || 0,
      content.image_hash || content.image_url || "",
      content.image ? content.image.length : 0,
      content.frame || {},
    ]);
  }
  return JSON.stringify([
    kind,
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

/** Build a framed whiteboard whose texture mirrors the shared board image. */
export async function createWhiteboardProp(prop) {
  const content = prop?.surface?.content || {};
  const frame = normalizeFrame(content.frame);
  const layout = frameLayout(frame);
  const canvas = await renderWhiteboardCanvas(content);
  const worldWidth = 2.6;
  const worldHeight = worldWidth * (layout.height / layout.width);
  return framedSurface(canvas, worldWidth, worldHeight, 0.12, normalizeColor(frame.main, "#332820"));
}

function framedSurface(canvas, width, height, frameDepth, backingColor = "#332820") {
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  texture.needsUpdate = true;
  const group = new THREE.Group();
  const backing = new THREE.Mesh(
    new THREE.BoxGeometry(width + 0.18, height + 0.18, frameDepth),
    new THREE.MeshStandardMaterial({ color: backingColor, roughness: 0.85 }),
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
