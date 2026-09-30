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

/** Authoritative elevation units gained per pixel the top handle is dragged upward. */
export const ELEVATE_DRAG_UNITS_PER_PX = 0.1;

/** Horizontal rotate-handle drag → prop yaw. Dragging right spins clockwise from above. */
export function rotationDeltaForDrag(dx) {
  return -Number(dx || 0) * ROTATE_DRAG_DEG_PER_PX;
}

/** Vertical top-handle drag → elevation delta. Dragging up (negative dy) raises the prop. */
export function elevationDeltaForDrag(dy) {
  return -Number(dy || 0) * ELEVATE_DRAG_UNITS_PER_PX;
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
  const top = project(gizmo.topHandleWorldPosition());
  if (!screenCenter || !edge || !rotate || !top) return null;
  return { center: screenCenter, rotate, top, radiusPx: Math.hypot(edge.x - screenCenter.x, edge.y - screenCenter.y) };
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
  const elevateMaterial = new THREE.MeshBasicMaterial({ color: "#ff9f6e", depthWrite: false, transparent: true, opacity: 0.95 });

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
  // Shift swaps the box for an up-pointing arrow that reads as "raise the prop".
  const elevateArrow = handleMesh(new THREE.Mesh(new THREE.ConeGeometry(0.13, 0.26, 16), elevateMaterial), "elevate");
  elevateArrow.visible = false;
  group.add(elevateArrow);

  let circleRadiusWorld = 0;
  let verticalMode = false;

  return {
    group,
    // The drag circle is hit-tested by distance in board.js, so only the raised handles raycast.
    get pickables() {
      return verticalMode ? [rotateKnob, scaleStem, elevateArrow] : [rotateKnob, scaleStem, scaleCube];
    },
    /** World-space radius of the drag circle from the most recent setTarget. */
    get circleRadius() {
      return circleRadiusWorld;
    },
    /** Current world position of the rotate knob, for projecting its screen point. */
    rotateHandleWorldPosition(target = new THREE.Vector3()) {
      group.updateMatrixWorld(true);
      return rotateKnob.getWorldPosition(target);
    },
    /** Current world position of the active top handle, for projecting its screen point. */
    topHandleWorldPosition(target = new THREE.Vector3()) {
      group.updateMatrixWorld(true);
      return (verticalMode ? elevateArrow : scaleCube).getWorldPosition(target);
    },
    /** Swap the top handle between scaling (box) and vertical movement (arrow). */
    setVerticalMode(active) {
      verticalMode = Boolean(active);
      scaleCube.visible = !verticalMode;
      elevateArrow.visible = verticalMode;
      scaleStem.material = verticalMode ? elevateMaterial : scaleMaterial;
      scaleStem.userData.editMode = verticalMode ? "elevate" : "scale";
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
      elevateArrow.position.y = topLocal;
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
      elevateMaterial.dispose();
      group.removeFromParent();
    },
  };
}
