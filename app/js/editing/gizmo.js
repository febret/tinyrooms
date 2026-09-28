import * as THREE from "three";

const GIZMO_HEIGHT = 0.06;
const SCALE_HANDLE_MARGIN = 0.3;
const SCALE_HANDLE_MIN = 0.5;
const CIRCLE_MIN_RADIUS = 0.42;
const CIRCLE_MARGIN = 0.14;
const ROTATE_KNOB_GAP = 0.18;
const SCALE_FACTOR_MIN = 0.5;
const SCALE_FACTOR_MAX = 2;

/** Degrees the prop turns per pixel the rotate handle is dragged horizontally. */
export const ROTATE_DRAG_DEG_PER_PX = 0.02;

/** Horizontal rotate-handle drag → prop yaw. Dragging right spins clockwise from above. */
export function rotationDeltaForDrag(dx) {
  return -Number(dx || 0) * ROTATE_DRAG_DEG_PER_PX;
}

/** Local-space circle radius that wraps a world-space footprint at the gizmo's clamped scale. */
export function circleLocalRadius(footprintWorld, factor) {
  const clamped = Math.max(SCALE_FACTOR_MIN, Math.min(SCALE_FACTOR_MAX, Number(factor) || 1));
  return Math.max(CIRCLE_MIN_RADIUS, Math.max(Number(footprintWorld) || 0, 0) / clamped) + CIRCLE_MARGIN;
}

/** World-space footprint radius from a model's local bounds and applied scale. */
export function footprintRadius(bounds, scale) {
  if (!bounds) return 0;
  const halfX = (bounds.max.x - bounds.min.x) / 2;
  const halfZ = (bounds.max.z - bounds.min.z) / 2;
  return Math.max(halfX, halfZ) * (Number(scale) || 1);
}

/** Project the drag circle centre, radius and rotate knob into canvas screen space. */
export function projectGizmo(gizmo, center, camera, bounds, ndcToScreen) {
  const project = world => {
    const point = world.clone().project(camera);
    return Number.isFinite(point.x) ? ndcToScreen(point, bounds) : null;
  };
  const screenCenter = project(center.clone());
  const edge = project(new THREE.Vector3(center.x + gizmo.circleRadius, center.y, center.z));
  const rotate = project(gizmo.rotateHandleWorldPosition());
  if (!screenCenter || !edge || !rotate) return null;
  return { center: screenCenter, rotate, radiusPx: Math.hypot(edge.x - screenCenter.x, edge.y - screenCenter.y) };
}

function handleMesh(mesh, mode) {
  mesh.userData.editMode = mode;
  return mesh;
}

/** Create the visible drag/rotate/scale handles attached to the board scene. */
export function createGizmo() {
  const group = new THREE.Group();
  group.visible = false;

  const moveEdgeMaterial = new THREE.MeshBasicMaterial({ color: "#8fd6ff", depthWrite: false, transparent: true, opacity: 0.75 });
  const moveFillMaterial = new THREE.MeshBasicMaterial({ color: "#8fd6ff", depthWrite: false, transparent: true, opacity: 0.16 });
  const rotateMaterial = new THREE.MeshBasicMaterial({ color: "#ffd479", depthWrite: false, transparent: true, opacity: 0.9 });
  const scaleMaterial = new THREE.MeshBasicMaterial({ color: "#a6e87a", depthWrite: false, transparent: true, opacity: 0.95 });

  // Unit-radius drag circle: an outline plus a faint fill, resized per prop in setTarget.
  // It sits under the prop, so dragging anywhere inside it moves the prop.
  const dragEdge = new THREE.Mesh(new THREE.RingGeometry(0.94, 1, 64), moveEdgeMaterial);
  dragEdge.rotation.x = -Math.PI / 2;
  dragEdge.renderOrder = -1;
  group.add(dragEdge);
  const dragFill = new THREE.Mesh(new THREE.CircleGeometry(1, 64), moveFillMaterial);
  dragFill.rotation.x = -Math.PI / 2;
  dragFill.renderOrder = -1;
  group.add(dragFill);

  // The rotate handle sits just outside the drag circle so it never competes with it.
  const rotateKnob = handleMesh(new THREE.Mesh(new THREE.SphereGeometry(0.09, 14, 12), rotateMaterial), "rotate");
  group.add(rotateKnob);

  // Unit-height stem stretched to reach the top of the selected prop.
  const scaleStem = handleMesh(new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 1, 6), scaleMaterial), "scale");
  group.add(scaleStem);
  const scaleCube = handleMesh(new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 0.16), scaleMaterial), "scale");
  group.add(scaleCube);

  let circleRadiusWorld = 0;

  return {
    group,
    // The drag circle is hit-tested by distance in board.js, so only the raised handles raycast.
    pickables: [rotateKnob, scaleStem, scaleCube],
    /** World-space radius of the drag circle from the most recent setTarget. */
    get circleRadius() {
      return circleRadiusWorld;
    },
    /** Current world position of the rotate knob, for projecting its screen point. */
    rotateHandleWorldPosition(target = new THREE.Vector3()) {
      group.updateMatrixWorld(true);
      return rotateKnob.getWorldPosition(target);
    },
    setTarget(worldPosition, scale, propHeight = 0, footprint = 0) {
      group.position.set(worldPosition[0], worldPosition[1] + GIZMO_HEIGHT, worldPosition[2]);
      const factor = Math.max(SCALE_FACTOR_MIN, Math.min(SCALE_FACTOR_MAX, Number(scale) || 1));
      group.scale.setScalar(factor);
      const radiusLocal = circleLocalRadius(footprint, factor);
      circleRadiusWorld = radiusLocal * factor;
      dragEdge.scale.set(radiusLocal, radiusLocal, 1);
      dragFill.scale.set(radiusLocal, radiusLocal, 1);
      rotateKnob.position.set(radiusLocal + ROTATE_KNOB_GAP, 0, 0);
      // Place the scale handle just above the prop so its grab direction reads as "taller".
      const topWorld = Math.max(Number(propHeight) || 0, 0) + SCALE_HANDLE_MARGIN;
      const topLocal = Math.max(SCALE_HANDLE_MIN, topWorld / factor);
      scaleStem.scale.y = topLocal;
      scaleStem.position.y = topLocal / 2;
      scaleCube.position.y = topLocal;
    },
    setVisible(visible) {
      group.visible = Boolean(visible);
    },
    dispose() {
      for (const child of [...group.children]) {
        child.geometry?.dispose();
      }
      moveEdgeMaterial.dispose();
      moveFillMaterial.dispose();
      rotateMaterial.dispose();
      scaleMaterial.dispose();
      group.removeFromParent();
    },
  };
}
