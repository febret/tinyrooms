import * as THREE from "three";

const BASE_SCALE = 0.6;
const GIZMO_HEIGHT = 0.06;

function handleMesh(mesh, mode) {
  mesh.userData.editMode = mode;
  return mesh;
}

/** Create the visible move/rotate/scale handles attached to the board scene. */
export function createGizmo() {
  const group = new THREE.Group();
  group.visible = false;

  const moveMaterial = new THREE.MeshBasicMaterial({ color: "#8fd6ff", depthWrite: false, transparent: true, opacity: 0.85 });
  const rotateMaterial = new THREE.MeshBasicMaterial({ color: "#ffd479", depthWrite: false, transparent: true, opacity: 0.9 });
  const scaleMaterial = new THREE.MeshBasicMaterial({ color: "#a6e87a", depthWrite: false, transparent: true, opacity: 0.95 });

  for (const axis of ["x", "z"]) {
    const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.24, 10), moveMaterial);
    arrow.position.set(axis === "x" ? BASE_SCALE : 0, 0.04, axis === "z" ? BASE_SCALE : 0);
    arrow.rotation.set(axis === "z" ? Math.PI / 2 : 0, 0, axis === "x" ? -Math.PI / 2 : 0);
    group.add(arrow);
  }

  const ring = handleMesh(new THREE.Mesh(new THREE.TorusGeometry(BASE_SCALE * 0.72, 0.035, 8, 48), rotateMaterial), "rotate");
  ring.rotation.x = -Math.PI / 2;
  group.add(ring);

  const scaleStem = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.5, 6), scaleMaterial);
  scaleStem.position.y = 0.5;
  group.add(scaleStem);
  const scaleCube = handleMesh(new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 0.16), scaleMaterial), "scale");
  scaleCube.position.y = 0.78;
  group.add(scaleCube);

  return {
    group,
    pickables: [ring, scaleCube],
    setTarget(worldPosition, scale) {
      group.position.set(worldPosition[0], worldPosition[1] + GIZMO_HEIGHT, worldPosition[2]);
      const factor = Math.max(0.5, Math.min(2, Number(scale) || 1));
      group.scale.setScalar(factor);
    },
    setVisible(visible) {
      group.visible = Boolean(visible);
    },
    dispose() {
      for (const child of [...group.children]) {
        child.geometry?.dispose();
      }
      moveMaterial.dispose();
      rotateMaterial.dispose();
      scaleMaterial.dispose();
      group.removeFromParent();
    },
  };
}
