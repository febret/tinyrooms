import * as THREE from "three";
import { OrbitControls } from "../vendor/three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "../vendor/three/examples/jsm/loaders/GLTFLoader.js";
import {
  applyFloorImageStyle, floorKey, loadSharedTexture, makeFloor,
  setDarkened, setGhosted, setPropLightGlow, sharedTexture, shareModelTextures, unavailableMarker,
} from "./board-resources.js";
import {
  advanceRecords,
  boardPosition,
  detachBoardTree,
  disposeBoardTree,
  fitBoardCamera,
  loadPropModel,
  positionKey,
  propEffectKey,
  propModelKey,
  syncRecords,
} from "./board-helpers.js";
import { isTextProp } from "./text-props.js";
import { isSurfaceProp } from "./surface-props.js";
import { isExitProp } from "./exit-props.js";
import { createGizmo, elevationDeltaForDrag, footprintRadius, rotationDeltaForDrag } from "./editing/gizmo.js";
import { createEditModifier } from "./editing/edit-modifier.js";
import { snapPositionValue } from "./editing/edit-reducer.js";
import { cardDropElevation, stackMetrics, supportElevation } from "./editing/prop-stacking.js";
import { createPropEffects } from "./prop-effects.js";
import { createBoardLights, resetBoardLights, scaredShake, selfIsScared, settleShake } from "./board-effects.js";
import {
  DARK_SPRITE_LIGHTING,
  MAX_PROP_LIGHTS,
  PROP_LIGHT_DISTANCE,
  applyBoardBackdrop,
  applyEnvironmentLighting,
  backdropForPreset,
  clearBoardBackdrop,
  propLightWorldPosition,
  resolveRoomLighting,
  selectAmbientSources,
  selectPropLights,
  spriteLightingForPreset,
} from "./board-lighting.js";
import { createBoardOutlines } from "./board-outlines.js";
import { createBoardSprites } from "./board-sprites.js";
import { createBoardCards } from "./board-cards.js";
import { createBoardScheduler } from "./board-scheduler.js";
import { createBoardRecovery } from "./board-recovery.js";
import { createBoardGames } from "./board-games.js";
import { playPropAnimation } from "./board-animations.js";
import { DIORAMA_BOARD_TYPE, createDioramaBoard } from "./board-diorama.js";
const TOP = 0.045;
const SCALE_DRAG_SENSITIVITY = 0.008;
/** Card footprint used for stacking, matching the ground shadow ellipse. */
const CARD_HALF_X = 0.425;
const CARD_HALF_Z = 0.275;
/** Vertical drag sensitivity: screen pixels to board world units. */
const BOARD_LIFT_PX = 0.015;
const BOARD_LIFT_MIN = -4;
const BOARD_LIFT_MAX = 6;

/** Convert an authoritative position into its board-space target, resting on the floor. */
function targetPosition(position) {
  const target = new THREE.Vector3(...boardPosition(position));
  target.y += TOP;
  return target;
}
const FLOOR_PLANE = new THREE.Plane(new THREE.Vector3(0, 1, 0), -TOP);

/** Convert a world-space point on the floor back into an authoritative [x%, y%, z] position. */
function boardPositionFromWorld(point) {
  return [
    Math.min(100, Math.max(0, point.x / 0.105 + 50)),
    Math.min(100, Math.max(0, point.z / 0.085 + 50)),
    0,
  ];
}

/** Create the physical room board. render(state) updates it; dispose() releases its resources. */
export function createBoard({ canvas, overlay, onSelect, onMoveSprite, onDropPoint, onPeepAnchors, onGameAction, needsPeepAnchors, onEditSelect, onEditBegin, onEditTransform, onEditRotate, onEditScale, onEditElevate, stackProps = false, dragHandles = false }) {
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
  canvas.dataset.boardReady = "false";
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, stencil: true });
  } catch {
    overlay.textContent = "3D rendering is unavailable. Room cards and room exits remain available.";
    overlay.dataset.status = "error";
    return { async render() {}, dispose() {} };
  }
  renderer.setClearColor("#417f7c", 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  // The room is static between edits, so re-rendering the 2048x2048 depth
  // buffer every frame doubled the submitted geometry for no visual change.
  // `invalidateScene` marks it stale when geometry or a caster actually moves.
  renderer.shadowMap.autoUpdate = false;
  renderer.shadowMap.needsUpdate = true;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 1000);
  camera.position.set(0, 16, 12);
  const controls = new OrbitControls(camera, canvas);
  controls.enabled = false;
  controls.enablePan = false;
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minPolarAngle = Math.PI / 8;
  controls.maxPolarAngle = Math.PI / 2.25;
  controls.minDistance = 7;
  controls.maxDistance = 100;
  // Left-drag orbits and the wheel/pinch zooms in every mode; prop dragging
  // suppresses the controls for the duration of the gesture instead.
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: null };
  controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_ROTATE };
  const lights = createBoardLights(scene);
  const propLights = [];
  for (let index = 0; index < MAX_PROP_LIGHTS; index += 1) {
    const point = new THREE.PointLight("#ffd9a1", 0, PROP_LIGHT_DISTANCE, 2);
    point.visible = false;
    scene.add(point);
    propLights.push(point);
  }

  function syncPropLights(entries) {
    if (!current || current.diorama) {
      for (const point of propLights) {
        point.intensity = 0;
        point.visible = false;
      }
      return;
    }
    propLights.forEach((point, index) => {
      const entry = entries[index];
      if (!entry) {
        point.intensity = 0;
        point.visible = false;
        return;
      }
      point.visible = true;
      point.color.set(entry.color);
      point.intensity = entry.intensity;
      point.position.set(...propLightWorldPosition(entry.position));
    });
  }

  function effectPixelScale() {
    return renderer.domElement.height / (2 * Math.tan((camera.fov * Math.PI / 180) / 2));
  }

  const selectionRing = new THREE.Mesh(
    new THREE.TorusGeometry(0.65, 0.035, 8, 64),
    new THREE.MeshBasicMaterial({ color: "#ffde92", depthWrite: false }),
  );
  selectionRing.rotation.x = -Math.PI / 2;
  selectionRing.visible = false;
  scene.add(selectionRing);
  const dropHint = new THREE.Mesh(
    new THREE.TorusGeometry(0.5, 0.035, 8, 48),
    new THREE.MeshBasicMaterial({ color: "#a6e87a", depthWrite: false, transparent: true, opacity: 0.85 }),
  );
  dropHint.rotation.x = -Math.PI / 2;
  dropHint.visible = false;
  scene.add(dropHint);
  const gizmo = createGizmo();
  scene.add(gizmo.group);
  const loader = new GLTFLoader();
  const textureLoader = new THREE.TextureLoader();
  const spriteLayer = createBoardSprites({ textureLoader, invalidate });
  const cardLayer = createBoardCards({
    register,
    texture,
    setRecordTarget,
    invalidateScene,
    onRemoveGroup(group) {
      if (selectionObject === group) selectionObject = null;
    },
  });
  const gameLayer = createBoardGames({
    loader,
    textureLoader,
    screenToBoardPosition: (clientX, clientY) => screenToBoardPosition(clientX, clientY),
    pixelScale: effectPixelScale,
    invalidate,
    invalidateShadows: invalidateScene,
    reactSprite: (id, options) => (current ? spriteLayer.react(current, id, options) : false),
  });
  gameLayer.setActionHandler(action => onGameAction?.(action));

  function applySpriteLighting(entry, lighting) {
    const spritesChanged = spriteLayer.applyLighting(entry, lighting);
    const cardsChanged = cardLayer.applyLighting(entry, lighting);
    return spritesChanged || cardsChanged;
  }

  const clock = new THREE.Clock();
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const pointers = new Map();
  const pointerCurrent = new Map();
  let gestureMoved = false;
  let blocked = true;
  let disposed = false;
  let revision = 0;
  let current = null;
  let roomId = "";
  let spritesEnabled = false;
  let selection = null;
  let selectionObject = null;
  let editEnabled = false;
  let editSnapPosition = true;
  let editSelectionId = null;
  let editSelectionObject = null;
  let editGesture = null;
  let editDrag = null;
  let orbitSuppressed = false;
  let boardLift = 0;
  let shiftDrag = null;
  let twoFingerLift = null;
  let reducedMotion = false;
  let showActiveProps = false;
  let roomDark = false;
  let roomScared = false;
  let spriteLighting = { color: "#ffffff", opacity: 1 };
  let gameInputEnabled = true;
  let dropArmed = false;
  let userAdjusted = false;
  let width = 0;
  let height = 0;
  let renderedFrames = 0;
  let needsRender = true;
  let shadowPasses = 0;
  let shadowInvalidations = 0;
  let anchorsDirty = true;
  let lastAnchorUpdate = 0;
  const ANCHOR_INTERVAL_MS = 66;
  const recovery = createBoardRecovery({
    canvas,
    overlay,
    onLost() {
      controls.enabled = false;
      canvas.dataset.boardReady = "false";
      overlay.dataset.status = "error";
      overlay.textContent = "3D rendering was interrupted. Restoring the board…";
    },
    onRestored: contextRestored,
    onFrameError() {
      needsRender = true;
      scheduler.schedule();
    },
  });
  const scheduler = createBoardScheduler({
    onFrame: animate,
    onError: recovery.frameError,
  });

  /** Request a color frame. Use invalidateScene when geometry actually moved. */
  function invalidate() {
    needsRender = true;
    scheduler.schedule();
  }

  /** Request a color frame and refresh the static shadow map. */
  function invalidateScene() {
    shadowInvalidations += 1;
    renderer.shadowMap.needsUpdate = true;
    needsRender = true;
    scheduler.schedule();
  }

  const outlines = createBoardOutlines(renderer, camera);

  const editModifier = createEditModifier(active => {
    gizmo.setVerticalMode(active);
    invalidate();
  });

  function isCurrent(entry) {
    return !disposed && current === entry && entry.revision === revision;
  }

  function status(entry) {
    if (!isCurrent(entry) || recovery.renderFailed) return;
    // The overlay is a live region, and these run on every load event. Writing
    // an unchanged value still counts as a DOM mutation, so compare first.
    const state = entry.errors.size ? "error" : entry.pending ? "loading" : "ready";
    if (overlay.dataset.status !== state) overlay.dataset.status = state;
    const ready = String(!entry.pending && !entry.errors.size);
    if (canvas.dataset.boardReady !== ready) canvas.dataset.boardReady = ready;
    const text = entry.errors.size
      ? `${[...entry.errors].join(" · ")}. Room cards and room exits remain available.`
      : entry.pending ? `${entry.label} · Loading room artwork…` : "";
    if (overlay.textContent !== text) overlay.textContent = text;
  }

  function fail(entry, label) {
    entry.errors.add(label);
    status(entry);
  }

  /** Coalesce per-model selection refreshes into one update per frame. */
  function scheduleSelectionUpdate() {
    scheduler.once("selection", () => {
      if (current) updateSelection();
    });
  }

  /** Coalesce the O(props) FX count scan during room loading. */
  function scheduleFxStatus() {
    scheduler.once("fx-status", refreshFxStatus);
  }

  function updateSelection() {
    let changed = false;
    const previousSelectionObject = selectionObject;
    selectionRing.visible = false;
    selectionObject = null;
    for (const object of current?.pickables || []) {
      if (roomDark || object.userData.kind !== selection?.kind || object.userData.id !== selection?.id) continue;
      selectionObject = object;
      if (object.userData.kind !== "prop") {
        selectionRing.position.set(object.position.x, object.position.y + 0.06, object.position.z);
        selectionRing.visible = true;
      }
      break;
    }
    if (selectionObject !== previousSelectionObject) changed = true;
    const showProps = !editEnabled && !roomDark;
    for (const record of current?.props.values() || []) {
      if (outlines.update(record, showProps && selection?.kind === "prop" && selection.id === record.id, showProps && showActiveProps)) changed = true;
    }
    const previousEditSelection = editSelectionObject;
    editSelectionObject = editEnabled && editSelectionId
      ? (current?.pickables || []).find(object => object.userData.kind === "prop" && object.userData.id === editSelectionId)
      : null;
    if (editSelectionObject !== previousEditSelection) changed = true;
    const showGizmo = Boolean(editSelectionObject && !editSelectionLocked());
    gizmo.setResizable(editSelectionResizable());
    if (showGizmo) {
      gizmo.setTarget(editSelectionObject.position.toArray(), editSelectionObject.scale.x, selectedPropHeight(), selectedPropFootprint());
    }
    if (gizmo.group.visible !== showGizmo) {
      gizmo.setVisible(showGizmo);
      changed = true;
    }
    if (changed) invalidate();
  }

  function fit(resetDirection = false) {
    if (!current || !width || !height) return;
    const trayHeight = parseFloat(getComputedStyle(canvas).getPropertyValue("--tray-height")) || 0;
    fitBoardCamera(camera, controls, current.root, {
      resetDirection, width, height, bottomInset: width < height ? trayHeight : 0,
    });
  }

  function canvasBounds() {
    const bounds = canvas.getBoundingClientRect();
    return bounds.width && bounds.height ? bounds : null;
  }

  /** Convert a projected NDC point into canvas client coordinates. */
  function ndcToScreen(projected, bounds) {
    return {
      x: (projected.x + 1) / 2 * bounds.width + bounds.left,
      y: (1 - projected.y) / 2 * bounds.height + bounds.top,
    };
  }

  function screenToBoardPosition(clientX, clientY) {
    if (disposed || recovery.renderFailed || !current || blocked) return null;
    const bounds = canvasBounds();
    if (!bounds) return null;
    if (clientX < bounds.left || clientX > bounds.right || clientY < bounds.top || clientY > bounds.bottom) return null;
    pointer.set(
      (clientX - bounds.left) / bounds.width * 2 - 1,
      -(clientY - bounds.top) / bounds.height * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.ray.intersectPlane(FLOOR_PLANE, new THREE.Vector3());
    if (!hit) return null;
    return { position: boardPositionFromWorld(hit), screen: ndcToScreen(hit.clone().project(camera), bounds) };
  }

  function projectPositionToScreen(position) {
    if (disposed || !current || !Array.isArray(position)) return null;
    const bounds = canvasBounds();
    if (!bounds) return null;
    const world = new THREE.Vector3(...boardPosition(position));
    world.y += TOP + boardLift;
    const projected = world.project(camera);
    if (!Number.isFinite(projected.x) || projected.z > 1) return null;
    return ndcToScreen(projected, bounds);
  }

  function setDropHint(position) {
    invalidate();
    if (!position || disposed || blocked || current?.diorama) {
      dropHint.visible = false;
      return;
    }
    const world = new THREE.Vector3(...boardPosition(position));
    world.y += TOP + boardLift + 0.012;
    dropHint.position.copy(world);
    dropHint.visible = true;
  }

  /** World-space height of the prop currently under the gizmo, or 0 when unknown. */
  function selectedPropHeight() {
    const record = current?.props.get(editSelectionId);
    if (!record?.bounds) return 0;
    return (record.bounds.max.y - record.bounds.min.y) * (record.group.scale.x || 1);
  }

  /** World-space footprint radius of the selected prop, used to size the drag circle. */
  function selectedPropFootprint() {
    const record = current?.props.get(editSelectionId);
    return footprintRadius(record?.bounds, record?.group.scale.x);
  }

  /** Whether the prop currently under the gizmo is locked against transforms. */
  function editSelectionLocked() {
    return Boolean(current?.props.get(editSelectionId)?.prop?.locked);
  }

  /** Whether the prop currently under the gizmo may be resized. Unknown payloads default to resizable. */
  function editSelectionResizable() {
    return current?.props.get(editSelectionId)?.prop?.resizable !== false;
  }

  /**
   * Resolve a dragged prop's final position, raising it onto the highest prop it
   * intersects. Only the room editor opts in via `stackProps`.
   */
  function resolveEditPosition(id, candidate) {
    if (!stackProps) return candidate;
    const position = snapPositionValue(candidate, editSnapPosition);
    const record = current?.props.get(id);
    const world = boardPosition(position);
    const entry = stackMetrics(record, world[0], world[2]);
    if (!entry) return position;
    const others = [];
    for (const other of current.props.values()) {
      if (other.id === id) continue;
      const metrics = stackMetrics(other, other.group.position.x, other.group.position.z);
      if (metrics) others.push(metrics);
    }
    return [position[0], position[1], Math.min(50, Math.max(0, supportElevation(entry, others)))];
  }

  /** Shift the whole room board up or down, keeping the offset clamped. */
  function applyBoardLift(delta) {
    if (!current || disposed || !Number.isFinite(delta) || delta === 0) return;
    boardLift = Math.min(BOARD_LIFT_MAX, Math.max(BOARD_LIFT_MIN, boardLift + delta));
    syncBoardLift();
    markAdjusted();
  }

  function syncBoardLift() {
    if (!current) return;
    current.root.position.y = boardLift;
    FLOOR_PLANE.constant = -(TOP + boardLift);
  }

  /**
   * Resolve a dropped card's height with the same prop-stacking rule used by
   * the editor, so cards land on the floor or on top of intersecting props.
   */
  function resolveCardPosition(position) {
    if (!current || current.diorama || !Array.isArray(position)) return position;
    const world = boardPosition(position);
    return [position[0], position[1], cardDropElevation(current.props.values(), world[0], world[2], CARD_HALF_X, CARD_HALF_Z)];
  }

  /** True when a screen point falls inside the selected prop's drag circle. */
  function pickDragCircle(event) {
    if (editSelectionLocked() || !editSelectionObject || !editSelectionId || !(gizmo.circleRadius > 0) || !setRayFromEvent(event)) return null;
    const point = raycaster.ray.intersectPlane(FLOOR_PLANE, new THREE.Vector3());
    if (!point) return null;
    const dx = point.x - editSelectionObject.position.x;
    const dz = point.z - editSelectionObject.position.z;
    return Math.hypot(dx, dz) <= gizmo.circleRadius ? editSelectionId : null;
  }

  /** Push the single undo snapshot for a streamed gesture the first time it actually changes. */
  function ensureEditBegin(gesture) {
    if (!gesture || gesture.began) return;
    gesture.began = true;
    if (dragHandles) onEditBegin?.();
  }

  /** Rotate the prop by the horizontal distance the rotate handle is dragged. */
  function applyRotateGesture(event) {
    const delta = rotationDeltaForDrag(event.clientX - editGesture.lastX);
    editGesture.lastX = event.clientX;
    if (Math.abs(delta) < 0.01) return;
    ensureEditBegin(editGesture);
    onEditRotate?.(delta, true);
  }

  /** Grow or shrink the prop by the vertical distance the scale handle is dragged. */
  function applyScaleGesture(event) {
    const factor = Math.exp((editGesture.lastY - event.clientY) * SCALE_DRAG_SENSITIVITY);
    editGesture.lastY = event.clientY;
    if (Math.abs(factor - 1) < 0.001) return;
    ensureEditBegin(editGesture);
    onEditScale?.(factor, true);
  }

  /** Raise or lower the prop by the vertical distance the shift-held top handle is dragged. */
  function applyElevateGesture(event) {
    const delta = elevationDeltaForDrag(event.clientY - editGesture.lastY);
    editGesture.lastY = event.clientY;
    if (Math.abs(delta) < 0.001) return;
    ensureEditBegin(editGesture);
    onEditElevate?.(delta, true);
  }

  function texture(entry, url, label, apply) {
    if (!url) {
      fail(entry, `${label} is missing`);
      return;
    }
    entry.pending += 1;
    // One texture per URL for the lifetime of the page. Every room card loads
    // the same card back, so without this a 40-card room held 40 identical
    // resident textures; the HTTP cache saved the bytes, not the GPU memory.
    const cached = sharedTexture(url);
    if (cached) {
      entry.pending -= 1;
      apply(cached);
      status(entry);
      return;
    }
    loadSharedTexture(url, textureLoader).then(map => {
      if (!isCurrent(entry)) {
        entry.pending -= 1;
        status(entry);
        return;
      }
      map.colorSpace = THREE.SRGBColorSpace;
      map.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      apply(map);
      entry.pending -= 1;
      invalidate();
      status(entry);
    }, () => {
      if (!isCurrent(entry)) {
        entry.pending -= 1;
        status(entry);
        return;
      }
      entry.pending -= 1;
      fail(entry, `Could not load ${label}`);
    });
  }

  function register(entry, object, kind, id, position) {
    object.position.set(...boardPosition(position));
    object.position.y += TOP;
    object.userData = { kind, id };
    entry.root.add(object);
    entry.pickables.push(object);
  }

  function stopRecordAnimations(record) {
    for (const timer of record.animTimers) clearTimeout(timer);
    record.animTimers.length = 0;
    for (const mixer of record.mixers) mixer.stopAllAction();
    record.mixers.length = 0;
    record.animationActive = false;
  }

  /** Point a record at its authoritative position, tweening there unless motion is reduced. */
  function setRecordTarget(record, position) {
    const key = positionKey(position);
    if (record.positionKey === key) return;
    record.positionKey = key;
    record.target = targetPosition(position);
    if (reducedMotion) record.group.position.copy(record.target);
    invalidateScene();
  }

  /** Release a prop model's per-instance geometry and materials, keeping shared textures. */
  function disposePropRecord(record) {
    stopRecordAnimations(record);
    record.effectController?.dispose();
    record.effectController = null;
    outlines.remove(record);
    setGhosted(record, false);
    setDarkened(record, false);
    disposeBoardTree([record.group, ...(record.scenes || [])], { textures: record.ownsTextures === true });
  }

  /** Build (or rebuild) a prop record's effect controller from its effect sets. */
  function buildRecordEffects(record, prop, model, bounds, visual) {
    record.effectController?.dispose();
    record.effectController = null;
    record.effectKey = propEffectKey(prop);
    const effectSets = prop.effectSets && typeof prop.effectSets === "object" ? prop.effectSets : null;
    if (!effectSets || !model) return;
    record.effectController = createPropEffects({
      group: record.group,
      visual,
      model,
      bounds,
      effectSets,
      activeEffect: prop.activeEffect || null,
      reducedMotion,
      textureLoader,
      pixelScale: effectPixelScale,
      wake: invalidate,
    });
    scheduleFxStatus();
  }

  /** Publish how many effect layers are live so tests can observe them without pixels. */
  function refreshFxStatus() {
    if (!current) return;
    let count = 0;
    for (const record of current.props.values()) count += record.effectController?.activeCount || 0;
    const next = String(count);
    if (canvas.dataset.fxCount === next) return;
    canvas.dataset.fxCount = next;
    invalidate();
  }

  function addProp(entry, prop) {
    invalidate();
    const group = new THREE.Group();
    register(entry, group, "prop", prop.id, prop.position);
    group.rotation.set(...(prop.rotation || [0, 0, 0]));
    group.scale.setScalar(Number.isFinite(prop.scale) ? prop.scale : 1);
    const record = {
      id: prop.id, group, prop, modelKey: propModelKey(prop), positionKey: positionKey(prop.position),
      model: null, clips: [], animation: prop.animation || "", animationActive: false, mixers: [], animTimers: [], scenes: [],
      target: group.position.clone(), ghosted: false, darkened: false, override: null, materials: null,
      ownsTextures: isTextProp(prop) || isSurfaceProp(prop), effectController: null, effectKey: "",
    };
    entry.props.set(prop.id, record);
    const placeholder = unavailableMarker(group);
    if (!isTextProp(prop) && !isSurfaceProp(prop) && !isExitProp(prop) && !prop.modelUrl) {
      fail(entry, `${prop.label} model is missing`);
      return;
    }
    entry.pending += 1;
    loadPropModel(prop, loader).then(gltf => {
      if (!isCurrent(entry) || entry.props.get(prop.id) !== record) {
        entry.pending -= 1;
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        status(entry);
        return;
      }
      const model = gltf.scene;
      // Models load without shadow flags, so without this props cast no shadow.
      model.traverse(node => {
        if (node.isMesh) node.castShadow = node.receiveShadow = true;
      });
      const bounds = new THREE.Box3().setFromObject(model);
      if (bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray()].every(Number.isFinite)) {
        disposeBoardTree(gltf.scenes || [model]);
        entry.pending -= 1;
        fail(entry, `${prop.label} model has no usable geometry`);
        return;
      }
      // The server sends the combined definition + instance scale, applied by `group`;
      // here we only ground the model so its base rests on the floor.
      if (!isTextProp(prop) && !isSurfaceProp(prop) && !isExitProp(prop)) shareModelTextures(model, prop.modelUrl);
      const visual = new THREE.Group();
      visual.position.y = -bounds.min.y;
      visual.add(model);
      group.remove(placeholder);
      // The placeholder is a per-prop temporary that owns its geometry and
      // material outright, so unlike shared resources it really is disposed.
      disposeBoardTree(placeholder);
      group.add(visual);
      record.model = model;
      record.visual = visual;
      record.bounds = bounds;
      record.clips = gltf.animations || [];
      record.scenes = gltf.scenes || [model];
      setGhosted(record, Boolean(record.prop.ghost));
      setDarkened(record, roomDark);
      setPropLightGlow(record, record.prop.light);
      playPropAnimation(entry, record, record.prop, model, record.clips, isCurrent, invalidate);
      buildRecordEffects(record, record.prop, model, bounds, visual);
      entry.pending -= 1;
      invalidateScene();
      if (!userAdjusted) scheduleFit();
      scheduleSelectionUpdate();
      status(entry);
    }, () => {
      entry.pending -= 1;
      if (!isCurrent(entry) || entry.props.get(prop.id) !== record) {
        status(entry);
        return;
      }
      fail(entry, `Could not load ${prop.label} model`);
    });
  }

  /**
   * Coalesce camera fitting into one call per frame.
   *
   * Every model that finished loading used to trigger a full `fit()`, and each
   * fit walks every visible mesh, allocates eight corner vectors per mesh and
   * then binary-searches 28 times over all of them. Populating a room of ninety
   * props therefore allocated millions of vectors, all discarded. Fitting is
   * idempotent, so deferring it to the next frame gives the same result once
   * per burst of arrivals rather than once per arrival.
   */
  let fitFrame = 0;
  function scheduleFit() {
    if (userAdjusted || fitFrame || disposed) return;
    fitFrame = requestAnimationFrame(() => {
      fitFrame = 0;
      if (!userAdjusted && current) {
        fit(true);
        invalidate();
      }
    });
  }

  function updateProp(entry, record, prop) {
    let moved = false;
    record.prop = prop;
    const rotation = prop.rotation || [0, 0, 0];
    if (record.group.rotation.x !== rotation[0] || record.group.rotation.y !== rotation[1] || record.group.rotation.z !== rotation[2]) {
      record.group.rotation.set(...rotation);
      moved = true;
    }
    const scale = Number.isFinite(prop.scale) ? prop.scale : 1;
    if (record.group.scale.x !== scale) {
      record.group.scale.setScalar(scale);
      moved = true;
    }
    if (moved) invalidateScene();
    setGhosted(record, Boolean(prop.ghost));
    setDarkened(record, roomDark);
    setPropLightGlow(record, prop.light);
    setRecordTarget(record, prop.position);
    if (propEffectKey(prop) !== record.effectKey) {
      if (record.model && record.visual && record.bounds) {
        buildRecordEffects(record, prop, record.model, record.bounds, record.visual);
      } else {
        record.effectKey = propEffectKey(prop);
        scheduleFxStatus();
      }
    }
    if ((prop.animation || "") !== record.animation) {
      record.animation = prop.animation || "";
      stopRecordAnimations(record);
      if (record.model) playPropAnimation(entry, record, prop, record.model, record.clips, isCurrent, invalidate);
    }
  }

  function removeProp(entry, id) {
    const record = entry.props.get(id);
    if (!record) return;
    invalidateScene();
    disposePropRecord(record);
    entry.root.remove(record.group);
    const index = entry.pickables.indexOf(record.group);
    if (index >= 0) entry.pickables.splice(index, 1);
    entry.props.delete(id);
    if (selectionObject === record.group) selectionObject = null;
  }

  function syncProps(entry, room) {
    syncRecords(entry.props, (room.props || []).filter(prop => prop.visible !== false), {
      keyOf: prop => prop.id,
      modelKeyOf: propModelKey,
      create: prop => addProp(entry, prop),
      update: (record, prop) => updateProp(entry, record, prop),
      remove: id => removeProp(entry, id),
    });
    scheduleFxStatus();
  }

  function syncCards(entry, room) {
    syncRecords(entry.cards, room.roomCards || [], {
      keyOf: card => card.stackId,
      modelKeyOf: card => card.definition?.imageUrl || "",
      create: card => cardLayer.add(entry, card),
      update: (record, card) => cardLayer.update(entry, record, card),
      remove: id => cardLayer.remove(entry, id),
    });
  }

  function syncSprites(entry, room) {
    const enabled = Boolean(room.board?.spritesEnabled);
    const actors = enabled ? [...(room.occupants || []), ...(room.npcs || [])] : [];
    const spriteScale = Number(room.board?.spriteScale) > 0 ? Number(room.board?.spriteScale) : 1;
    spriteLayer.sync(entry, actors, roomDark, spriteScale);
  }

  /** Replace the floor only when the board artwork or palette actually changes. */
  function applyFloor(entry, room) {
    const board = room.board || {};
    const key = floorKey(board);
    if (entry.floor && entry.floor.key === key) return;
    invalidateScene();
    if (entry.floor) {
      entry.root.remove(entry.floor.group);
      if (!entry.floor.diorama) detachBoardTree(entry.floor.group);
      entry.floor.dispose();
    }
    canvas.dataset.boardType = board.type || "";
    canvas.dataset.diorama = board.type === DIORAMA_BOARD_TYPE ? "true" : "false";
    if (board.type === DIORAMA_BOARD_TYPE) {
      const diorama = createDioramaBoard({
        board,
        environment: room.environment,
        requestShadow() {
          shadowInvalidations += 1;
          renderer.shadowMap.needsUpdate = true;
        },
        setExposure(value) {
          renderer.toneMappingExposure = value;
        },
      });
      entry.root.add(diorama.group);
      entry.diorama = diorama;
      entry.floor = { group: diorama.group, diorama, dispose: () => diorama.dispose(), key };
      return;
    }
    entry.diorama = null;
    const { group, floor, dispose } = makeFloor(board);
    entry.root.add(group);
    entry.floor = { group, floor, dispose, key };
    if (board.dark) return;
    texture(entry, board.imageUrl, "floor artwork", map => {
      applyFloorImageStyle(map, board.imageStyle);
      floor.material.map = map;
      floor.material.color.set("#ffffff");
      floor.material.needsUpdate = true;
    });
  }

  function clear() {
    if (!current) return;
    for (const record of current.props.values()) disposePropRecord(record);
    for (const record of current.cards.values()) record.spriteMaterial?.dispose();
    spriteLayer.clear(current);
    gameLayer.clear();
    canvas.dataset.fxCount = "0";
    scene.remove(current.root);
    // Shared shadow/face geometry and textures are page-lifetime caches, so
    // each entry releases only what it created before the graph is unlinked.
    current.floor?.dispose?.();
    detachBoardTree(current.root);
    current = null;
    selectionObject = null;
    editSelectionObject = null;
    selectionRing.visible = false;
    dropHint.visible = false;
    gizmo.setVisible(false);
    for (const point of propLights) {
      point.intensity = 0;
      point.visible = false;
    }
  }

  function rebuild(room) {
    revision += 1;
    clear();
    roomId = room.id;
    spritesEnabled = Boolean(room.board?.spritesEnabled);
    userAdjusted = false;
    const entry = {
      root: new THREE.Group(), revision, pickables: [],
      props: new Map(), cards: new Map(), sprites: new Map(), floor: null, diorama: null,
      pending: 0, errors: new Set(), label: room.label,
    };
    current = entry;
    boardLift = 0;
    scene.add(entry.root);
    syncBoardLift();
    invalidateScene();
    applyFloor(entry, room);
    syncProps(entry, room);
    syncCards(entry, room);
    syncSprites(entry, room);
    syncGame(entry, room);
    if (!userAdjusted) fit(true);
    status(entry);
  }

  function syncRoom(room) {
    const entry = current;
    entry.label = room.label;
    spritesEnabled = Boolean(room.board?.spritesEnabled);
    applyFloor(entry, room);
    syncProps(entry, room);
    syncCards(entry, room);
    syncSprites(entry, room);
    syncGame(entry, room);
    status(entry);
  }

  function syncGame(entry, room) {
    gameLayer.sync(entry.root, room, { dark: roomDark, reducedMotion });
  }

  function resize() {
    if (disposed) return;
    const nextWidth = Math.max(1, canvas.clientWidth || canvas.parentElement.clientWidth);
    const nextHeight = Math.max(1, canvas.clientHeight || canvas.parentElement.clientHeight);
    if (width === nextWidth && height === nextHeight) return;
    width = nextWidth;
    height = nextHeight;
    renderer.setSize(width, height, false);
    outlines.resize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    invalidate();
    // Resizing fits the new viewport but preserves the user's orbit direction.
    fit(!userAdjusted);
  }

  function setRayFromEvent(event) {
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return false;
    // World matrices are normally refreshed as a side effect of rendering. The
    // render loop skips frames when the scene is at rest, so a raycast can
    // otherwise run against a camera or a prop transform that is one frame
    // behind, which makes picking miss. This is only on pointer input, so the
    // cost does not matter.
    camera.updateMatrixWorld();
    current?.root?.updateMatrixWorld(true);
    // The editor gizmo is a scene child rather than part of the room graph, so
    // it has to be refreshed explicitly. When it is stale, its rotate and scale
    // handles raycast at their previous positions and swallow clicks aimed at
    // the prop underneath.
    gizmo.group.updateMatrixWorld(true);
    pointer.set(
      (event.clientX - bounds.left) / bounds.width * 2 - 1,
      -(event.clientY - bounds.top) / bounds.height * 2 + 1,
    );
    raycaster.setFromCamera(pointer, camera);
    return true;
  }

  /** Walk up from the nearest raycast hit to the first object carrying `field`. */
  function pickOwner(objects, field) {
    const hit = raycaster.intersectObjects(objects, true)[0];
    if (!hit) return null;
    let object = hit.object;
    while (object && !object.userData[field]) object = object.parent;
    return object;
  }

  function pickGameplayOwner() {
    return roomDark ? null : pickOwner(current?.pickables || [], "kind");
  }

  function pickEditMode(event) {
    if (!gizmo.group.visible || !setRayFromEvent(event)) return null;
    return pickOwner(gizmo.pickables, "editMode")?.userData.editMode ?? null;
  }

  function pickPropId(event) {
    if (!setRayFromEvent(event)) return null;
    const owner = pickOwner(current?.pickables || [], "kind");
    return owner?.userData.kind === "prop" ? owner.userData.id : null;
  }

  function suppressOrbit() {
    orbitSuppressed = true;
    controls.enabled = false;
  }

  function releaseOrbit() {
    orbitSuppressed = false;
    controls.enabled = !blocked && !recovery.renderFailed;
  }

  function pointerDown(event) {
    if (blocked || event.button !== 0) return;
    if (editEnabled) {
      const mode = pickEditMode(event);
      if (mode) {
        editGesture = {
          mode, pointerId: event.pointerId, moved: false, began: false,
          startX: event.clientX, startY: event.clientY,
          lastX: event.clientX, lastY: event.clientY,
        };
        suppressOrbit();
        return;
      }
      const propId = pickPropId(event);
      const locked = propId && Boolean(current?.props.get(propId)?.prop?.locked);
      const id = locked ? null : (propId || pickDragCircle(event));
      editDrag = {
        id, propId, pointerId: event.pointerId, moved: false,
        startX: event.clientX, startY: event.clientY,
      };
      if (id) suppressOrbit();
      if (propId) onEditSelect?.(propId);
      return;
    }
    if (!editEnabled && event.shiftKey) {
      shiftDrag = { pointerId: event.pointerId, lastY: event.clientY };
      gestureMoved = true;
      suppressOrbit();
      return;
    }
    if (!pointers.size) gestureMoved = false;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    pointerCurrent.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size > 1) {
      gestureMoved = true;
      const ys = [...pointerCurrent.values()].map(point => point.y);
      twoFingerLift = { lastY: ys.reduce((sum, y) => sum + y, 0) / ys.length };
    }
  }

  function pointerMove(event) {
    if (editEnabled) {
      if (editGesture && editGesture.pointerId === event.pointerId) {
        if (!editGesture.moved && Math.hypot(event.clientX - editGesture.startX, event.clientY - editGesture.startY) > 4) {
          editGesture.moved = true;
        }
        if (dragHandles && editGesture.moved) {
          if (editGesture.mode === "rotate") applyRotateGesture(event);
          else if (editGesture.mode === "scale") applyScaleGesture(event);
          else if (editGesture.mode === "elevate") applyElevateGesture(event);
        }
        return;
      }
      if (editDrag && editDrag.pointerId === event.pointerId) {
        if (Math.hypot(event.clientX - editDrag.startX, event.clientY - editDrag.startY) > 4) editDrag.moved = true;
        if (editDrag.moved && editDrag.id) {
          ensureEditBegin(editDrag);
          const point = screenToBoardPosition(event.clientX, event.clientY);
          if (point) onEditTransform?.({ id: editDrag.id, position: resolveEditPosition(editDrag.id, point.position) });
        }
        return;
      }
    }
    if (!editEnabled && shiftDrag && shiftDrag.pointerId === event.pointerId) {
      applyBoardLift((shiftDrag.lastY - event.clientY) * BOARD_LIFT_PX);
      shiftDrag.lastY = event.clientY;
      gestureMoved = true;
      return;
    }
    if (!editEnabled && pointers.size >= 2) {
      const currentPointer = pointerCurrent.get(event.pointerId);
      if (currentPointer) {
        currentPointer.x = event.clientX;
        currentPointer.y = event.clientY;
        if (!twoFingerLift) {
          const ys = [...pointerCurrent.values()].map(point => point.y);
          twoFingerLift = { lastY: ys.reduce((sum, y) => sum + y, 0) / ys.length };
        }
        const ys = [...pointerCurrent.values()].map(point => point.y);
        const average = ys.reduce((sum, y) => sum + y, 0) / ys.length;
        applyBoardLift(-(average - twoFingerLift.lastY) * BOARD_LIFT_PX);
        twoFingerLift.lastY = average;
      }
      gestureMoved = true;
      if (dropArmed) setDropHint(null);
      return;
    }
    const currentPointer = pointerCurrent.get(event.pointerId);
    if (currentPointer) {
      currentPointer.x = event.clientX;
      currentPointer.y = event.clientY;
    }
    if (dropArmed) {
      const point = screenToBoardPosition(event.clientX, event.clientY);
      setDropHint(point?.position ? resolveCardPosition(point.position) : null);
    }
    const start = pointers.get(event.pointerId);
    if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) gestureMoved = true;
  }

  function pointerUp(event) {
    if (!editEnabled && shiftDrag && shiftDrag.pointerId === event.pointerId) {
      shiftDrag = null;
      releaseOrbit();
      gestureMoved = true;
      pointers.delete(event.pointerId);
      pointerCurrent.delete(event.pointerId);
      return;
    }
    if (editEnabled) {
      if (editGesture && editGesture.pointerId === event.pointerId) {
        const gesture = editGesture;
        editGesture = null;
        releaseOrbit();
        if (!gesture.moved && gesture.mode === "scale") {
          ensureEditBegin(gesture);
          onEditScale?.(1.15, dragHandles);
        }
        return;
      }
      if (editDrag && editDrag.pointerId === event.pointerId) {
        const drag = editDrag;
        editDrag = null;
        releaseOrbit();
        if (!drag.moved && !drag.id && !drag.propId) onEditSelect?.(null);
        return;
      }
      return;
    }
    const start = pointers.get(event.pointerId);
    pointers.delete(event.pointerId);
    pointerCurrent.delete(event.pointerId);
    if (pointers.size < 2) twoFingerLift = null;
    if (blocked || !start || gestureMoved || pointers.size
      || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return;
    if (!setRayFromEvent(event)) return;
    if (dropArmed) {
      setDropHint(null);
      const owner = pickGameplayOwner();
      if (owner && owner.userData.kind === "prop") {
        onSelect({ kind: "prop", id: owner.userData.id }, { x: event.clientX, y: event.clientY });
        return;
      }
      const point = screenToBoardPosition(event.clientX, event.clientY);
      if (point) onDropPoint?.(resolveCardPosition(point.position), point.screen);
      return;
    }
    if (gameInputEnabled && gameLayer.pointerUp(event.clientX, event.clientY)) return;
    const owner = pickGameplayOwner();
    if (owner) {
      onSelect({ kind: owner.userData.kind, id: owner.userData.id }, { x: event.clientX, y: event.clientY });
      return;
    }
    const floor = spritesEnabled ? screenToBoardPosition(event.clientX, event.clientY) : null;
    if (roomId) onSelect({ kind: "room", id: roomId });
    if (floor) onMoveSprite?.(floor.position);
  }

  function pointerCancel(event) {
    editGesture = null;
    editDrag = null;
    if (shiftDrag?.pointerId === event.pointerId) shiftDrag = null;
    releaseOrbit();
    pointers.delete(event.pointerId);
    pointerCurrent.delete(event.pointerId);
    if (pointers.size < 2) twoFingerLift = null;
    gestureMoved = true;
  }

  function markAdjusted() {
    if (!blocked) userAdjusted = true;
    invalidate();
  }

  function contextRestored() {
    if (disposed) return;
    clock.getDelta();
    resize();
    controls.enabled = !blocked && !orbitSuppressed;
    if (current) status(current);
    else {
      canvas.dataset.boardReady = "false";
      overlay.dataset.status = "idle";
      overlay.textContent = "Your room will appear here.";
    }
    invalidateScene();
  }

  controls.addEventListener("start", markAdjusted);
  controls.addEventListener("change", invalidate);
  canvas.addEventListener("pointerdown", pointerDown);
  canvas.addEventListener("pointermove", pointerMove);
  canvas.addEventListener("pointerup", pointerUp);
  canvas.addEventListener("pointercancel", pointerCancel);
  const observer = new ResizeObserver(resize);
  observer.observe(canvas.parentElement);
  resize();
  /**
   * A frame is needed while something animates, the camera moves, or anything
   * was invalidated since the last draw. Static rooms stay idle instead of
   * re-submitting hundreds of draw calls behind a modal.
   */
  function sceneIsAnimating() {
    if (!current) return false;
    if (current.diorama) return !blocked;
    if (roomScared && !reducedMotion) return true;
    for (const record of current.props.values()) {
      if (record.animationActive) return true;
      if (record.effectController?.isAnimating?.()) return true;
      if (record.target && !record.group.position.equals(record.target)) return true;
    }
    for (const record of current.cards.values()) {
      if (record.target && !record.group.position.equals(record.target)) return true;
    }
    if (gameLayer.isAnimating()) return true;
    return spriteLayer.isAnimating(current);
  }

  /** One scheduler frame: advance state, draw if needed, and report whether to continue. */
  function animate() {
    if (disposed || recovery.renderFailed) return false;
    recovery.resetFrameErrors();
    const delta = Math.min(clock.getDelta(), 0.1);
    if (current) {
      const dioramaFrame = current.diorama?.update(delta, { reducedMotion });
      if (current.diorama) {
        current.diorama.setSceneLights(lights);
        const day = dioramaFrame?.daylight;
        if (day) {
          applyBoardBackdrop(canvas, day.sky, day.ground);
          spriteLighting = roomDark ? DARK_SPRITE_LIGHTING : spriteLightingForPreset(day);
          applySpriteLighting(current, spriteLighting);
        }
      }
      if (roomScared && !reducedMotion && !editEnabled) scaredShake(current.root, clock.elapsedTime);
      for (const record of current.props.values()) {
        for (const mixer of record.mixers) mixer.update(delta);
        record.effectController?.update(delta);
      }
      advanceRecords(current.props.values(), delta, reducedMotion);
      advanceRecords(current.cards.values(), delta, reducedMotion);
      spriteLayer.advance(current, delta, reducedMotion);
      gameLayer.advance(delta);
    }
    if (selectionRing.visible && selectionObject) {
      selectionRing.position.set(
        selectionObject.position.x,
        selectionObject.position.y + boardLift + 0.06,
        selectionObject.position.z,
      );
    }
    if (editSelectionObject && !editSelectionLocked()) {
      gizmo.setTarget(editSelectionObject.position.toArray(), editSelectionObject.scale.x, selectedPropHeight(), selectedPropFootprint());
    }
    if (!blocked) {
      // OrbitControls only moves the camera when it is damping or being
      // dragged, so its own change flag is the cheapest reliable signal.
      if (controls.update()) invalidate();
    }
    const animating = sceneIsAnimating();
    if (needsRender || animating) {
      needsRender = false;
      renderedFrames += 1;
      const shadowWillRender = renderer.shadowMap.needsUpdate;
      renderer.render(scene, camera);
      if (shadowWillRender) shadowPasses += 1;
      outlines.render();
      if (current?.sprites?.size && (!needsPeepAnchors || needsPeepAnchors())) {
        const now = performance.now();
        if (anchorsDirty || now - lastAnchorUpdate >= ANCHOR_INTERVAL_MS) {
          anchorsDirty = false;
          lastAnchorUpdate = now;
          onPeepAnchors?.(spriteLayer.anchors(current, camera, canvas));
        }
      }
    }
    return needsRender || animating;
  }
  scheduler.schedule();

  return {
    /** GPU counters used by the deterministic performance suite. */
    diagnostics() {
      let nodes = 0;
      current?.root?.traverse(() => {
        nodes += 1;
      });
      return {
        frames: renderedFrames,
        ticks: scheduler.ticks,
        shadowPasses,
        shadowInvalidations,
        outline: outlines.diagnostics(),
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        geometries: renderer.info.memory.geometries,
        textures: renderer.info.memory.textures,
        programs: renderer.info.programs ? renderer.info.programs.length : 0,
        nodes,
        boardType: current?.floor?.key ? canvas.dataset.boardType || "" : "",
        diorama: Boolean(current?.diorama),
        dayPhase: current?.diorama?.phase ?? null,
        props: current ? current.props.size : 0,
        cards: current ? current.cards.size : 0,
        sprites: current ? current.sprites.size : 0,
        gamePieces: gameLayer.pieceCount(),
        pickables: current ? current.pickables.length : 0,
        editEnabled,
        blocked,
        shadowAutoUpdate: renderer.shadowMap.autoUpdate,
        shadowMapSize: lights.sunlight.shadow.mapSize.width,
        pixelRatio: renderer.getPixelRatio(),
        renderFailed: recovery.renderFailed,
      };
    },
    /** Diff normalized server state into the scene: only changed floor/props/cards are touched. */
    async render(state) {
      if (disposed) return;
      selection = state.selection;
      reducedMotion = Boolean(state.ui?.reducedMotion);
      showActiveProps = Boolean(state.ui?.outlineActiveProps);
      controls.enableDamping = !state.ui?.reducedMotion;
      editEnabled = Boolean(state.editing);
      editSnapPosition = state.editor?.snapPosition ?? true;
      editSelectionId = editEnabled ? (state.editSelection || null) : null;
      const modalView = state.views?.main;
      const blockingView = Boolean(modalView && modalView !== "edit-room");
      const wasBlocked = blocked;
      blocked = Boolean(blockingView || state.views?.auth
        || state.views?.commandPalette || !state.user?.initialStickerComplete);
      if (blocked !== wasBlocked) invalidate();
      const wasDropArmed = dropArmed;
      dropArmed = Boolean(state.ui?.dropTargeting) && !current?.diorama;
      gameInputEnabled = !blocked && !state.ui?.targeting && !state.ui?.dropTargeting && !state.room?.dialog;
      if (wasDropArmed && !dropArmed) setDropHint(null);
      controls.enabled = !blocked && !recovery.renderFailed && !orbitSuppressed;
      if (blocked) {
        pointers.clear();
        gestureMoved = true;
      }
      if (!state.room) {
        revision += 1;
        clear();
        roomId = "";
        spritesEnabled = false;
        canvas.dataset.boardType = "";
        canvas.dataset.diorama = "false";
        canvas.dataset.boardReady = "false";
        clearBoardBackdrop(canvas);
        spriteLighting = { color: "#ffffff", opacity: 1 };
        if (!recovery.renderFailed) {
          overlay.textContent = "Your room will appear here.";
          overlay.dataset.status = "idle";
        }
        return;
      }
      const wasDark = roomDark;
      const wasScared = roomScared;
      roomDark = Boolean(state.room.board.dark);
      roomScared = selfIsScared(state);
      if (wasScared !== roomScared) invalidate();
      if (roomDark !== wasDark) invalidate();
      if (!roomScared && current) settleShake(current.root);
      if (!current || roomId !== state.room.id) {
        rebuild(state.room);
      } else {
        syncRoom(state.room);
      }
      // Editing shows neutral day lighting so authors see true colors.
      const preset = editEnabled ? resolveRoomLighting(null) : resolveRoomLighting(state.room);
      const lightSelection = editEnabled
        ? { lights: [], lamps: 0, windows: 0 }
        : selectPropLights(state.room.props, preset.name, MAX_PROP_LIGHTS);
      const ambientSources = editEnabled
        ? { lamps: 0, windows: 0 }
        : selectAmbientSources(state.room.props, preset.name);
      if (current?.diorama) {
        current.diorama.setRoomDark(roomDark);
        current.diorama.setSceneLights(lights);
        syncPropLights(lightSelection.lights);
        const day = current.diorama.daylight;
        applyBoardBackdrop(canvas, day.sky, day.ground);
        spriteLighting = roomDark ? DARK_SPRITE_LIGHTING : spriteLightingForPreset(day);
      } else {
        resetBoardLights(lights);
        if (applyEnvironmentLighting(lights, preset, renderer, ambientSources.lamps, ambientSources.windows)) invalidate();
        syncPropLights(lightSelection.lights);
        const backdrop = backdropForPreset(preset);
        applyBoardBackdrop(canvas, backdrop.top, backdrop.bottom);
        spriteLighting = spriteLightingForPreset(preset);
      }
      if (applySpriteLighting(current, spriteLighting)) invalidate();
      for (const record of current?.props?.values() || []) setDarkened(record, roomDark);
      updateSelection();
      if (current?.sprites?.size && (!needsPeepAnchors || needsPeepAnchors())) {
        anchorsDirty = true;
        invalidate();
      }
    },
    /** Map a screen point to the authoritative floor position and projected screen point. */
    screenToBoardPosition,
    /** Project an authoritative [x%, y%, z] position into canvas screen coordinates. */
    projectPositionToScreen,
    /** Show or clear the floor marker used while arming a card drop. */
    setDropHint,
    /** Resolve a drop position onto the floor or the top of intersecting props. */
    resolveCardDrop: resolveCardPosition,
    /** Cancel an in-progress edit gesture. Returns null when none was active, else whether an undo is owed. */
    cancelEditGesture() {
      const gesture = editGesture || editDrag;
      editGesture = null;
      editDrag = null;
      releaseOrbit();
      // A handle press pushes its snapshot lazily, so a click with no drag owes no undo.
      return gesture ? { undo: gesture.began !== false } : null;
    },
    /** Release geometry, materials, textures, controls, listeners, and late-loading assets. */
    dispose() {
      if (disposed) return;
      disposed = true;
      canvas.dataset.boardReady = "false";
      revision += 1;
      scheduler.stop();
      observer.disconnect();
      controls.removeEventListener("start", markAdjusted);
      controls.removeEventListener("change", invalidate);
      controls.dispose();
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("pointercancel", pointerCancel);
      recovery.dispose();
      editModifier.dispose();
      gameLayer.dispose();
      clear();
      gizmo.dispose();
      outlines.dispose();
      // GHOST_MATERIAL is a page-lifetime shared resource, so it is not disposed with one board.
      disposeBoardTree(selectionRing);
      disposeBoardTree(dropHint);
      lights.sunlight.shadow.dispose();
      renderer.dispose();
    },
  };
}
