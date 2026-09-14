import * as THREE from "three";

/** Convert authoritative [horizontal %, depth %, elevation] into board-space XYZ. */
export function boardPosition([x = 50, y = 50, z = 0] = []) {
  return [(x - 50) * 0.105, z * 0.1, (y - 50) * 0.085];
}

/** Identify visual layout changes only; chat, occupants, actions, and selection are excluded. */
export function boardSignature(room) {
  return JSON.stringify([
    room.id, room.label, room.board,
    (room.props || []).map(prop => [prop.id, prop.propId, prop.label, prop.position, prop.rotation, prop.scale, prop.modelUrl]),
    (room.roomCards || []).map(card => [card.stackId, card.position, card.definition?.label, card.definition?.imageUrl]),
  ]);
}

/** Dispose each owned GPU resource once, including GLTF ImageBitmaps and shared materials. */
export function disposeBoardTree(roots) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  const images = new Set();
  const skeletons = new Set();
  for (const root of Array.isArray(roots) ? roots : [roots]) {
    root.traverse(node => {
      if (node.geometry) geometries.add(node.geometry);
      if (node.skeleton) skeletons.add(node.skeleton);
      if (node.material) {
        for (const item of Array.isArray(node.material) ? node.material : [node.material]) materials.add(item);
      }
    });
  }
  for (const item of materials) {
    for (const value of Object.values(item)) {
      if (value?.isTexture) textures.add(value);
    }
    item.dispose();
  }
  for (const texture of textures) {
    for (const image of Array.isArray(texture.source?.data) ? texture.source.data : [texture.source?.data]) {
      if (image?.close) images.add(image);
    }
    texture.dispose();
  }
  for (const image of images) image.close();
  for (const geometry of geometries) geometry.dispose();
  for (const skeleton of skeletons) skeleton.dispose();
}

/** Fit visible mesh bounds, preserving orbit direction and reserving an optional bottom UI inset. */
export function fitBoardCamera(camera, controls, root, {
  resetDirection = false, width = 1000, height = width / camera.aspect, bottomInset = 0,
} = {}) {
  root.updateMatrixWorld(true);
  const bounds = new THREE.Box3().setFromObject(root);
  if (bounds.isEmpty()) return;
  const corners = [];
  root.traverseVisible(object => {
    if (!object.isMesh || !object.geometry) return;
    object.geometry.computeBoundingBox();
    const local = object.geometry.boundingBox;
    if (!local || local.isEmpty()) return;
    for (const x of [local.min.x, local.max.x]) {
      for (const y of [local.min.y, local.max.y]) {
        for (const z of [local.min.z, local.max.z]) {
          corners.push(new THREE.Vector3(x, y, z).applyMatrix4(object.matrixWorld));
        }
      }
    }
  });
  if (!corners.length) return;
  const direction = camera.position.clone().sub(controls.target).normalize();
  if (resetDirection) {
    const elevation = THREE.MathUtils.degToRad(camera.aspect > 1 ? 56 : 66);
    direction.set(0, Math.sin(elevation), Math.cos(elevation));
  }
  const center = bounds.getCenter(new THREE.Vector3());
  const side = Math.max(6, width * 0.015);
  const top = 12;
  const bottom = Math.min(bottomInset, height * 0.4) + 8;
  camera.clearViewOffset();
  controls.target.copy(center);
  camera.far = Math.max(1000, bounds.getSize(new THREE.Vector3()).length() * 200);
  camera.updateProjectionMatrix();
  const projectedBounds = distance => {
    camera.position.copy(center).addScaledVector(direction, distance);
    camera.lookAt(center);
    camera.updateMatrixWorld();
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const corner of corners) {
      const point = corner.clone().project(camera);
      if (point.z < -1 || point.z >= 1) return null;
      const x = (point.x + 1) * width / 2;
      const y = (1 - point.y) * height / 2;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    return { minX, maxX, minY, maxY };
  };
  let near = camera.near;
  let far = camera.far / 4;
  for (let iteration = 0; iteration < 28; iteration += 1) {
    const distance = (near + far) / 2;
    const projected = projectedBounds(distance);
    if (projected && projected.maxX - projected.minX <= width - side * 2
      && projected.maxY - projected.minY <= height - top - bottom) far = distance;
    else near = distance;
  }
  const projected = projectedBounds(far * 1.005);
  if (projected) {
    camera.setViewOffset(width, height,
      (projected.minX + projected.maxX - width) / 2,
      (projected.minY + projected.maxY - height - top + bottom) / 2,
      width, height);
  }
  controls.minDistance = Math.max(3, far * 0.4);
  controls.maxDistance = Math.max(80, far * 3);
}
