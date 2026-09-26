import * as THREE from "three";
import { OrbitControls } from "../vendor/three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "../vendor/three/examples/jsm/loaders/GLTFLoader.js";
import {
  applyFloorImageStyle, box, floorKey, GHOST_MATERIAL, makeFloor, material, rememberTexture,
  sharedCardMaterial, sharedTexture, shareModelTextures, unavailableMarker,
} from "./board-resources.js";
import {
  boardPosition,
  cardModelKey,
  detachBoardTree,
  disposeBoardTree,
  ELEVATION_PER_UNIT,
  fitBoardCamera,
  positionKey,
  propEffectKey,
  propModelKey,
} from "./board-helpers.js";
import { createGizmo } from "./editing/gizmo.js";
import { snapPositionValue } from "./editing/edit-reducer.js";
import { supportElevation } from "./editing/prop-stacking.js";
import { createPropEffects } from "./prop-effects.js";

export const CARD_BACK = "/assets/world/tutorial/cards/back.webp";
const TOP = 0.045;
const RANDOM_ANIMATION_PAUSE_MS = 1000;
const PROP_MOVE_SMOOTHING = 9;
const SCALE_DRAG_SENSITIVITY = 0.008;

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

/**
 * Footprint and top-elevation metrics used to decide how high a dragged prop rests.
 * The local model bounds are rotated into board space and enclosed by an AABB.
 */
function stackMetrics(record, worldX, worldZ) {
  const bounds = record?.bounds;
  if (!bounds) return null;
  const scale = record.group.scale.x || 1;
  const halfLocalX = (bounds.max.x - bounds.min.x) / 2;
  const halfLocalZ = (bounds.max.z - bounds.min.z) / 2;
  const centerLocalX = (bounds.max.x + bounds.min.x) / 2;
  const centerLocalZ = (bounds.max.z + bounds.min.z) / 2;
  const angle = record.group.rotation.y || 0;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    id: record.id,
    x: worldX + scale * (cos * centerLocalX + sin * centerLocalZ),
    z: worldZ + scale * (-sin * centerLocalX + cos * centerLocalZ),
    halfX: scale * (Math.abs(cos) * halfLocalX + Math.abs(sin) * halfLocalZ),
    halfZ: scale * (Math.abs(sin) * halfLocalX + Math.abs(cos) * halfLocalZ),
    topZ: (Number(record.prop?.position?.[2]) || 0)
      + ((bounds.max.y - bounds.min.y) * scale) / ELEVATION_PER_UNIT,
  };
}




/** Create the physical room board. render(state) updates it; dispose() releases its resources. */
export function createBoard({ canvas, overlay, onSelect, onEditSelect, onEditBegin, onEditTransform, onEditRotate, onEditScale, stackProps = false, dragHandles = false }) {
  overlay.setAttribute("role", "status");
  overlay.setAttribute("aria-live", "polite");
  canvas.dataset.boardReady = "false";
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
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
  // `requestShadowUpdate` re-renders it whenever the scene actually moves.
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
  scene.add(new THREE.HemisphereLight("#fff2d5", "#496e69", 1.45));
  const sunlight = new THREE.DirectionalLight("#ffe6bb", 2);
  sunlight.position.set(-5, 12, 7);
  sunlight.castShadow = true;
  sunlight.shadow.mapSize.set(2048, 2048);
  Object.assign(sunlight.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 0.5, far: 45 });
  sunlight.shadow.normalBias = 0.025;
  sunlight.shadow.bias = -0.0001;
  scene.add(sunlight);
  const fill = new THREE.DirectionalLight("#bce2df", 0.45);
  fill.position.set(5, 5, -4);
  scene.add(fill);

  /** Pixel scale used by point-sprite effects so particle size is world-sized. */
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
  const clock = new THREE.Clock();
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  const pointers = new Map();
  let gestureMoved = false;
  let blocked = true;
  let disposed = false;
  let renderFailed = false;
  let revision = 0;
  let current = null;
  let roomId = "";
  let selection = null;
  let selectionObject = null;
  let editEnabled = false;
  let editSnapPosition = true;
  let editSelectionId = null;
  let editSelectionObject = null;
  let editGesture = null;
  let editDrag = null;
  let orbitSuppressed = false;
  let reducedMotion = false;
  let userAdjusted = false;
  let width = 0;
  let height = 0;
  let frame = 0;
  let renderedFrames = 0;
  let needsRender = true;

  /** Mark the scene as changed so the next frame redraws and refreshes shadows. */
  function invalidate() {
    needsRender = true;
    renderer.shadowMap.needsUpdate = true;
  }

  function isCurrent(entry) {
    return !disposed && current === entry && entry.revision === revision;
  }

  function status(entry) {
    if (!isCurrent(entry) || renderFailed) return;
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

  function updateSelection() {
    invalidate();
    selectionRing.visible = false;
    selectionObject = null;
    for (const object of current?.pickables || []) {
      if (object.userData.kind !== selection?.kind || object.userData.id !== selection?.id) continue;
      selectionObject = object;
      selectionRing.position.set(object.position.x, object.position.y + 0.06, object.position.z);
      selectionRing.visible = true;
      break;
    }
    editSelectionObject = editEnabled && editSelectionId
      ? (current?.pickables || []).find(object => object.userData.kind === "prop" && object.userData.id === editSelectionId)
      : null;
    if (editSelectionObject) {
      gizmo.setTarget(editSelectionObject.position.toArray(), editSelectionObject.scale.x, selectedPropHeight());
      gizmo.setVisible(true);
    } else {
      gizmo.setVisible(false);
    }
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

  function screenToBoardPosition(clientX, clientY) {
    if (disposed || renderFailed || !current || blocked) return null;
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
    const projected = hit.clone().project(camera);
    return {
      position: boardPositionFromWorld(hit),
      screen: {
        x: (projected.x + 1) / 2 * bounds.width + bounds.left,
        y: (1 - projected.y) / 2 * bounds.height + bounds.top,
      },
    };
  }

  function projectPositionToScreen(position) {
    if (disposed || !current || !Array.isArray(position)) return null;
    const bounds = canvasBounds();
    if (!bounds) return null;
    const world = new THREE.Vector3(...boardPosition(position));
    world.y += TOP;
    const projected = world.project(camera);
    if (!Number.isFinite(projected.x) || projected.z > 1) return null;
    return {
      x: (projected.x + 1) / 2 * bounds.width + bounds.left,
      y: (1 - projected.y) / 2 * bounds.height + bounds.top,
    };
  }

  function setDropHint(position) {
    invalidate();
    if (!position || disposed || blocked) {
      dropHint.visible = false;
      return;
    }
    const world = new THREE.Vector3(...boardPosition(position));
    world.y += TOP + 0.012;
    dropHint.position.copy(world);
    dropHint.visible = true;
  }

  /** World-space height of the prop currently under the gizmo, or 0 when unknown. */
  function selectedPropHeight() {
    const record = current?.props.get(editSelectionId);
    if (!record?.bounds) return 0;
    return (record.bounds.max.y - record.bounds.min.y) * (record.group.scale.x || 1);
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

  /** Raycast a pointer event onto the floor plane for gesture math. */
  function screenToFloorPoint(clientX, clientY) {
    if (!setRayFromEvent({ clientX, clientY })) return null;
    return raycaster.ray.intersectPlane(FLOOR_PLANE, new THREE.Vector3());
  }

  function gestureAngle(event, center) {
    if (!center) return 0;
    const point = screenToFloorPoint(event.clientX, event.clientY);
    return point ? Math.atan2(point.z - center.z, point.x - center.x) : 0;
  }

  /** Spin the prop by the angle swept around its centre since the last move. */
  function applyRotateGesture(event) {
    if (!editGesture?.center) return;
    const angle = gestureAngle(event, editGesture.center);
    let delta = ((angle - editGesture.lastAngle) * 180) / Math.PI;
    delta = ((delta + 180) % 360 + 360) % 360 - 180;
    if (Math.abs(delta) < 0.1) return;
    editGesture.lastAngle = angle;
    onEditRotate?.(delta, true);
  }

  /** Grow or shrink the prop by the vertical distance the scale handle is dragged. */
  function applyScaleGesture(event) {
    const factor = Math.exp((editGesture.lastY - event.clientY) * SCALE_DRAG_SENSITIVITY);
    editGesture.lastY = event.clientY;
    if (Math.abs(factor - 1) < 0.001) return;
    onEditScale?.(factor, true);
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
    textureLoader.load(url, map => {
      if (!isCurrent(entry)) {
        map.dispose();
        return;
      }
      map.colorSpace = THREE.SRGBColorSpace;
      map.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      rememberTexture(url, map);
      apply(map);
      entry.pending -= 1;
      invalidate();
      status(entry);
    }, undefined, () => {
      if (!isCurrent(entry)) return;
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
  }

  function startLoopedClip(record, model, clip) {
    const mixer = new THREE.AnimationMixer(model);
    mixer.clipAction(clip).setLoop(THREE.LoopRepeat, Infinity).play();
    record.mixers.push(mixer);
  }

  function startRandomClips(entry, record, model, clips) {
    const mixer = new THREE.AnimationMixer(model);
    record.mixers.push(mixer);
    let lastIndex = -1;
    function pick() {
      if (!isCurrent(entry) || entry.props.get(record.id) !== record) return;
      let index = Math.floor(Math.random() * clips.length);
      if (clips.length > 1) {
        while (index === lastIndex) index = Math.floor(Math.random() * clips.length);
      }
      lastIndex = index;
      const action = mixer.clipAction(clips[index]);
      action.reset();
      action.setLoop(THREE.LoopOnce, 1);
      action.clampWhenFinished = true;
      const onFinished = event => {
        if (event.action !== action) return;
        mixer.removeEventListener("finished", onFinished);
        if (!isCurrent(entry) || entry.props.get(record.id) !== record) return;
        record.animTimers.push(setTimeout(pick, RANDOM_ANIMATION_PAUSE_MS));
      };
      mixer.addEventListener("finished", onFinished);
      action.play();
    }
    pick();
  }

  function playPropAnimation(entry, record, prop, model, clips) {
    // Respect reduced-motion preferences; also keeps rendered frames deterministic.
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const mode = typeof prop.animation === "string" ? prop.animation.trim() : "";
    if (!mode) return;
    if (!clips || !clips.length) {
      console.warn(`Prop ${prop.id} requests animation "${mode}" but the model has no animations.`);
      return;
    }
    if (mode === "auto") {
      startLoopedClip(record, model, clips[0]);
      return;
    }
    if (mode === "random") {
      startRandomClips(entry, record, model, clips);
      return;
    }
    const clip = clips.find(candidate => candidate.name === mode);
    if (!clip) {
      console.warn(`Prop ${prop.id} requests unknown animation "${mode}".`);
      return;
    }
    startLoopedClip(record, model, clip);
  }

  /** Point a record at its authoritative position, tweening there unless motion is reduced. */
  function setRecordTarget(record, position) {
    const key = positionKey(position);
    if (record.positionKey === key) return;
    record.positionKey = key;
    record.target = targetPosition(position);
    if (reducedMotion) record.group.position.copy(record.target);
    invalidate();
  }

  /** Swap a loaded model's materials for the gray ghost look, or restore the originals. */
  function setGhosted(record, ghosted) {
    if (!record.model || record.ghosted === ghosted) return;
    record.ghosted = ghosted;
    if (ghosted) {
      record.materials = [];
      record.model.traverse(node => {
        if (node.isMesh && node.material) {
          record.materials.push([node, node.material]);
          node.material = GHOST_MATERIAL;
        }
      });
    } else if (record.materials) {
      for (const [node, original] of record.materials) node.material = original;
      record.materials = null;
    }
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
    });
    refreshFxStatus();
  }

  /** Publish how many effect layers are live so tests can observe them without pixels. */
  function refreshFxStatus() {
    if (!current) return;
    let count = 0;
    for (const record of current.props.values()) count += record.effectController?.activeCount || 0;
    if (canvas.dataset.fxCount !== String(count)) canvas.dataset.fxCount = String(count);
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
      model: null, clips: [], animation: prop.animation || "", mixers: [], animTimers: [], scenes: [],
      target: group.position.clone(), ghosted: false, materials: null,
      effectController: null, effectKey: "",
    };
    entry.props.set(prop.id, record);
    const placeholder = unavailableMarker(group);
    if (!prop.modelUrl) {
      fail(entry, `${prop.label} model is missing`);
      return;
    }
    entry.pending += 1;
    loader.load(prop.modelUrl, gltf => {
      if (!isCurrent(entry) || entry.props.get(prop.id) !== record) {
        entry.pending -= 1;
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        return;
      }
      const model = gltf.scene;
      const bounds = new THREE.Box3().setFromObject(model);
      if (bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray()].every(Number.isFinite)) {
        disposeBoardTree(gltf.scenes || [model]);
        entry.pending -= 1;
        fail(entry, `${prop.label} model has no usable geometry`);
        return;
      }
      // The server sends the combined definition + instance scale, applied by `group`;
      // here we only ground the model so its base rests on the floor.
      shareModelTextures(model, prop.modelUrl);
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
      playPropAnimation(entry, record, record.prop, model, record.clips);
      buildRecordEffects(record, record.prop, model, bounds, visual);
      entry.modelScenes.push(...record.scenes);
      entry.pending -= 1;
      invalidate();
      if (!userAdjusted) scheduleFit();
      updateSelection();
      status(entry);
    }, undefined, () => {
      entry.pending -= 1;
      if (!isCurrent(entry) || entry.props.get(prop.id) !== record) return;
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
      if (!userAdjusted && current) fit(true);
    });
  }

  function updateProp(entry, record, prop) {
    record.prop = prop;
    record.group.rotation.set(...(prop.rotation || [0, 0, 0]));
    record.group.scale.setScalar(Number.isFinite(prop.scale) ? prop.scale : 1);
    setGhosted(record, Boolean(prop.ghost));
    setRecordTarget(record, prop.position);
    if (propEffectKey(prop) !== record.effectKey) {
      if (record.model && record.visual && record.bounds) {
        buildRecordEffects(record, prop, record.model, record.bounds, record.visual);
      } else {
        record.effectKey = propEffectKey(prop);
        refreshFxStatus();
      }
    }
    if ((prop.animation || "") !== record.animation) {
      record.animation = prop.animation || "";
      stopRecordAnimations(record);
      if (record.model) playPropAnimation(entry, record, prop, record.model, record.clips);
    }
  }

  function removeProp(entry, id) {
    const record = entry.props.get(id);
    if (!record) return;
    invalidate();
    stopRecordAnimations(record);
    record.effectController?.dispose();
    record.effectController = null;
    entry.root.remove(record.group);
    detachBoardTree(record.group);
    const index = entry.pickables.indexOf(record.group);
    if (index >= 0) entry.pickables.splice(index, 1);
    entry.props.delete(id);
    if (selectionObject === record.group) selectionObject = null;
  }

  /** Reconcile a record map against authoritative items, recreating on model-key change. */
  function syncRecords(map, items, handlers) {
    const seen = new Set();
    for (const item of items) {
      const key = handlers.keyOf(item);
      seen.add(key);
      const record = map.get(key);
      if (!record) {
        handlers.create(item);
      } else if (record.modelKey !== handlers.modelKeyOf(item)) {
        handlers.remove(key);
        handlers.create(item);
      } else {
        handlers.update(record, item);
      }
    }
    for (const key of [...map.keys()]) {
      if (!seen.has(key)) handlers.remove(key);
    }
  }

  function syncProps(entry, room) {
    syncRecords(entry.props, room.props || [], {
      keyOf: prop => prop.id,
      modelKeyOf: propModelKey,
      create: prop => addProp(entry, prop),
      update: (record, prop) => updateProp(entry, record, prop),
      remove: id => removeProp(entry, id),
    });
    refreshFxStatus();
  }

  function addCard(entry, card) {
    invalidate();
    const group = new THREE.Group();
    register(entry, group, "room-card", card.stackId, card.position);
    entry.cards.set(card.stackId, {
      id: card.stackId, group, card, modelKey: cardModelKey(card), positionKey: positionKey(card.position),
      target: group.position.clone(),
    });
    // The edge and back materials are identical for every card, so they are
    // shared; only the front carries a card-specific texture. That takes a
    // fifty-card room from 150 materials down to 52.
    const edge = sharedCardMaterial("#d5b887");
    const back = sharedCardMaterial("#193e55");
    const front = material("#fff7e3");
    // BoxGeometry's +Y/-Y groups are the upper/lower faces, not +Z/-Z.
    const mesh = box(group, [0.62, 0.045, 0.88], [0, 0.028, 0], [edge, edge, front, back, edge, edge]);
    mesh.rotation.y = -0.08;
    texture(entry, card.definition?.imageUrl, `${card.definition?.label || "Card"} artwork`, map => {
      front.map = map;
      front.color.set("#ffffff");
      front.needsUpdate = true;
    });
    texture(entry, CARD_BACK, "card back artwork", map => {
      back.map = map;
      back.color.set("#ffffff");
      back.needsUpdate = true;
    });
  }

  function updateCard(record, card) {
    record.card = card;
    setRecordTarget(record, card.position);
  }

  function removeCard(entry, id) {
    const record = entry.cards.get(id);
    if (!record) return;
    invalidate();
    entry.root.remove(record.group);
    detachBoardTree(record.group);
    const index = entry.pickables.indexOf(record.group);
    if (index >= 0) entry.pickables.splice(index, 1);
    entry.cards.delete(id);
    if (selectionObject === record.group) selectionObject = null;
  }

  function syncCards(entry, room) {
    syncRecords(entry.cards, room.roomCards || [], {
      keyOf: card => card.stackId,
      modelKeyOf: cardModelKey,
      create: card => addCard(entry, card),
      update: (record, card) => updateCard(record, card),
      remove: id => removeCard(entry, id),
    });
  }

  /** Replace the floor only when the board artwork or palette actually changes. */
  function applyFloor(entry, room) {
    invalidate();
    const board = room.board || {};
    const key = floorKey(board);
    if (entry.floor && entry.floor.key === key) return;
    if (entry.floor) {
      entry.root.remove(entry.floor.group);
      detachBoardTree(entry.floor.group);
      // The floor's own material is not shared, so it is the one thing here
      // that still owns GPU resources.
      entry.floor.floor.material.dispose();
    }
    const { group, floor } = makeFloor(board);
    entry.root.add(group);
    entry.floor = { group, floor, key };
    texture(entry, board.imageUrl, "floor artwork", map => {
      applyFloorImageStyle(map, board.imageStyle);
      floor.material.map = map;
      floor.material.color.set("#ffffff");
      floor.material.needsUpdate = true;
    });
  }

  function clear() {
    if (!current) return;
    for (const record of current.props.values()) {
      stopRecordAnimations(record);
      record.effectController?.dispose();
      record.effectController = null;
    }
    canvas.dataset.fxCount = "0";
    scene.remove(current.root);
    // Props, cards and the floor slab all draw on page-lifetime shared caches,
    // so switching rooms unlinks the graph instead of disposing buffers that
    // other instances still reference. Those caches are bounded by the number
    // of distinct assets in the world, not by how many rooms are visited.
    detachBoardTree(current.root);
    current.floor?.floor?.material?.dispose();
    current = null;
    selectionObject = null;
    editSelectionObject = null;
    selectionRing.visible = false;
    dropHint.visible = false;
    gizmo.setVisible(false);
  }

  function rebuild(room) {
    revision += 1;
    clear();
    roomId = room.id;
    userAdjusted = false;
    const entry = {
      root: new THREE.Group(), revision, pickables: [], modelScenes: [],
      props: new Map(), cards: new Map(), floor: null,
      pending: 0, errors: new Set(), label: room.label,
    };
    current = entry;
    scene.add(entry.root);
    invalidate();
    applyFloor(entry, room);
    syncProps(entry, room);
    syncCards(entry, room);
    if (!userAdjusted) fit(true);
    status(entry);
  }

  function syncRoom(room) {
    const entry = current;
    entry.label = room.label;
    applyFloor(entry, room);
    syncProps(entry, room);
    syncCards(entry, room);
    status(entry);
  }

  function resize() {
    if (disposed) return;
    const nextWidth = Math.max(1, canvas.clientWidth || canvas.parentElement.clientWidth);
    const nextHeight = Math.max(1, canvas.clientHeight || canvas.parentElement.clientHeight);
    if (width === nextWidth && height === nextHeight) return;
    width = nextWidth;
    height = nextHeight;
    renderer.setSize(width, height, false);
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

  function pickEditMode(event) {
    if (!gizmo.group.visible || !setRayFromEvent(event)) return null;
    const hit = raycaster.intersectObjects(gizmo.pickables, true)[0];
    if (!hit) return null;
    let object = hit.object;
    while (object && !object.userData.editMode) object = object.parent;
    return object ? object.userData.editMode : null;
  }

  function pickPropId(event) {
    if (!setRayFromEvent(event)) return null;
    const hit = raycaster.intersectObjects(current?.pickables || [], true)[0];
    if (!hit) return null;
    let object = hit.object;
    while (object && !object.userData.kind) object = object.parent;
    return object && object.userData.kind === "prop" ? object.userData.id : null;
  }

  function suppressOrbit() {
    orbitSuppressed = true;
    controls.enabled = false;
  }

  function releaseOrbit() {
    orbitSuppressed = false;
    controls.enabled = !blocked && !renderFailed;
  }

  function pointerDown(event) {
    if (blocked || event.button !== 0) return;
    if (editEnabled) {
      const mode = pickEditMode(event);
      if (mode) {
        const center = editSelectionObject ? editSelectionObject.position.clone() : null;
        editGesture = {
          mode, pointerId: event.pointerId, moved: false,
          startX: event.clientX, startY: event.clientY,
          lastY: event.clientY, center,
          lastAngle: mode === "rotate" ? gestureAngle(event, center) : 0,
        };
        // Drag gestures stream deltas, so capture one undo snapshot up front.
        if (dragHandles) onEditBegin?.();
        suppressOrbit();
        return;
      }
      const propId = pickPropId(event);
      editDrag = { id: propId, pointerId: event.pointerId, moved: false, startX: event.clientX, startY: event.clientY };
      if (propId) {
        suppressOrbit();
        onEditSelect?.(propId);
        onEditBegin?.();
      }
      return;
    }
    if (!pointers.size) gestureMoved = false;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size > 1) gestureMoved = true;
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
        }
        return;
      }
      if (editDrag && editDrag.pointerId === event.pointerId) {
        if (Math.hypot(event.clientX - editDrag.startX, event.clientY - editDrag.startY) > 4) editDrag.moved = true;
        if (editDrag.moved && editDrag.id) {
          const point = screenToBoardPosition(event.clientX, event.clientY);
          if (point) onEditTransform?.({ id: editDrag.id, position: resolveEditPosition(editDrag.id, point.position) });
        }
        return;
      }
    }
    const start = pointers.get(event.pointerId);
    if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) gestureMoved = true;
  }

  function pointerUp(event) {
    if (editEnabled) {
      if (editGesture && editGesture.pointerId === event.pointerId) {
        const gesture = editGesture;
        editGesture = null;
        releaseOrbit();
        if (!gesture.moved && gesture.mode === "rotate") onEditRotate?.(15, dragHandles);
        else if (!gesture.moved && gesture.mode === "scale") onEditScale?.(1.15, dragHandles);
        return;
      }
      if (editDrag && editDrag.pointerId === event.pointerId) {
        const drag = editDrag;
        editDrag = null;
        releaseOrbit();
        if (!drag.moved && !drag.id) onEditSelect?.(null);
        return;
      }
      return;
    }
    const start = pointers.get(event.pointerId);
    pointers.delete(event.pointerId);
    if (blocked || !start || gestureMoved || pointers.size
      || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return;
    if (!setRayFromEvent(event)) return;
    let object = raycaster.intersectObjects(current?.pickables || [], true)[0]?.object;
    while (object && !object.userData.kind) object = object.parent;
    if (object) {
      onSelect({ kind: object.userData.kind, id: object.userData.id });
      return;
    }
    if (roomId) onSelect({ kind: "room", id: roomId });
  }

  function pointerCancel(event) {
    editGesture = null;
    editDrag = null;
    releaseOrbit();
    pointers.delete(event.pointerId);
    gestureMoved = true;
  }

  function markAdjusted() {
    if (!blocked) userAdjusted = true;
    invalidate();
  }

  function contextLost(event) {
    event.preventDefault();
    renderFailed = true;
    controls.enabled = false;
    canvas.dataset.boardReady = "false";
    overlay.dataset.status = "error";
    overlay.textContent = "3D rendering was interrupted. Reload to restore the board; Room view remains available.";
  }

  controls.addEventListener("start", markAdjusted);
  canvas.addEventListener("pointerdown", pointerDown);
  canvas.addEventListener("pointermove", pointerMove);
  canvas.addEventListener("pointerup", pointerUp);
  canvas.addEventListener("pointercancel", pointerCancel);
  canvas.addEventListener("webglcontextlost", contextLost);
  const observer = new ResizeObserver(resize);
  observer.observe(canvas.parentElement);
  resize();
  /** Ease each record toward its authoritative position; snaps instantly when motion is reduced. */
  function advanceRecords(records, delta) {
    const alpha = 1 - Math.exp(-delta * PROP_MOVE_SMOOTHING);
    for (const record of records) {
      const target = record.target;
      if (!target || record.group.position.equals(target)) continue;
      if (reducedMotion) {
        record.group.position.copy(target);
      } else {
        record.group.position.lerp(target, alpha);
        if (record.group.position.distanceToSquared(target) < 1e-6) record.group.position.copy(target);
      }
    }
  }

  /**
   * Whether the next frame has to be drawn.
   *
   * The loop used to call `renderer.render` unconditionally, sixty times a
   * second, for the whole life of the page -- including behind a modal, and for
   * a scene where nothing was animating. A room with ninety props submits
   * hundreds of draw calls per frame, so an always-on loop kept the CPU and GPU
   * busy for a picture nobody was looking at.
   *
   * A frame is needed while something is animating, the camera is moving, or
   * anything was invalidated since the last draw.
   */
  function sceneIsAnimating() {
    if (!current) return false;
    for (const record of current.props.values()) {
      if (record.mixers.length) return true;
      if (record.effectController?.activeCount) return true;
      if (record.target && !record.group.position.equals(record.target)) return true;
    }
    for (const record of current.cards.values()) {
      if (record.target && !record.group.position.equals(record.target)) return true;
    }
    return false;
  }

  /**
   * A background tab gets no animation frames from the browser anyway, and the
   * shadow pass would otherwise be marked stale and re-rendered on return.
   * Pausing explicitly keeps the loop from doing work the compositor discards.
   */
  function pageIsHidden() {
    return typeof document !== "undefined" && document.hidden;
  }

  function animate() {
    if (disposed || renderFailed) return;
    try {
      if (pageIsHidden()) {
        // Draw once on the way back so the canvas is not blank when restored.
        frame = requestAnimationFrame(animate);
        return;
      }
      const delta = Math.min(clock.getDelta(), 0.1);
      if (current) {
        for (const record of current.props.values()) {
          for (const mixer of record.mixers) mixer.update(delta);
          record.effectController?.update(delta);
        }
        advanceRecords(current.props.values(), delta);
        advanceRecords(current.cards.values(), delta);
      }
      if (selectionRing.visible && selectionObject) {
        selectionRing.position.set(
          selectionObject.position.x,
          selectionObject.position.y + 0.06,
          selectionObject.position.z,
        );
      }
      if (editSelectionObject) {
        gizmo.setTarget(editSelectionObject.position.toArray(), editSelectionObject.scale.x, selectedPropHeight());
      }
      if (!blocked) {
        // OrbitControls only moves the camera when it is damping or being
        // dragged, so its own change flag is the cheapest reliable signal.
        if (controls.update()) invalidate();
      }
      if (needsRender || sceneIsAnimating()) {
        needsRender = false;
        renderedFrames += 1;
        renderer.render(scene, camera);
      }
      frame = requestAnimationFrame(animate);
    } catch {
      contextLost({ preventDefault() {} });
    }
  }
  animate();

  return {
    /**
     * Counters describing what the board is actually submitting to the GPU.
     *
     * The performance suite asserts on these rather than on frame timings, so
     * the budgets stay deterministic on any machine. `frames` only advances
     * while the loop is producing frames, which is what makes it possible to
     * assert that the loop goes quiet when nothing is moving.
     */
    diagnostics() {
      let nodes = 0;
      current?.root?.traverse(() => {
        nodes += 1;
      });
      return {
        frames: renderedFrames,
        drawCalls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        geometries: renderer.info.memory.geometries,
        textures: renderer.info.memory.textures,
        programs: renderer.info.programs ? renderer.info.programs.length : 0,
        nodes,
        props: current ? current.props.size : 0,
        cards: current ? current.cards.size : 0,
        pickables: current ? current.pickables.length : 0,
        editEnabled,
        blocked,
        shadowAutoUpdate: renderer.shadowMap.autoUpdate,
        shadowMapSize: sunlight.shadow.mapSize.width,
        pixelRatio: renderer.getPixelRatio(),
        renderFailed,
      };
    },
    /** Diff normalized server state into the scene: only changed floor/props/cards are touched. */
    async render(state) {
      if (disposed) return;
      selection = state.selection;
      reducedMotion = Boolean(state.ui?.reducedMotion);
      controls.enableDamping = !state.ui?.reducedMotion;
      editEnabled = Boolean(state.editing);
      editSnapPosition = state.editor?.snapPosition ?? true;
      editSelectionId = editEnabled ? (state.editSelection || null) : null;
      const modalView = state.views?.main;
      const blockingView = Boolean(modalView && modalView !== "edit-room");
      blocked = Boolean(blockingView || state.views?.details || state.views?.auth
        || state.views?.commandPalette || !state.user?.initialStickerComplete);
      controls.enabled = !blocked && !renderFailed && !orbitSuppressed;
      if (blocked) {
        pointers.clear();
        gestureMoved = true;
      }
      if (!state.room) {
        revision += 1;
        clear();
        roomId = "";
        canvas.dataset.boardReady = "false";
        if (!renderFailed) {
          overlay.textContent = "Your room will appear here.";
          overlay.dataset.status = "idle";
        }
        return;
      }
      if (!current || roomId !== state.room.id) {
        rebuild(state.room);
      } else {
        syncRoom(state.room);
      }
      updateSelection();
      const elevation = editEnabled && editSelectionId
        ? String(current?.props.get(editSelectionId)?.prop?.position?.[2] ?? 0)
        : "0";
      if (canvas.dataset.editElevation !== elevation) canvas.dataset.editElevation = elevation;
    },
    /** Map a screen point to the authoritative floor position and projected screen point. */
    screenToBoardPosition,
    /** Project an authoritative [x%, y%, z] position into canvas screen coordinates. */
    projectPositionToScreen,
    /** Show or clear the floor marker used as a drag drop target. */
    setDropHint,
    /** Cancel an in-progress edit gesture; returns true when one was active. */
    cancelEditGesture() {
      const active = Boolean(editGesture || editDrag);
      editGesture = null;
      editDrag = null;
      releaseOrbit();
      return active;
    },
    /** Release geometry, materials, textures, controls, listeners, and late-loading assets. */
    dispose() {
      if (disposed) return;
      disposed = true;
      canvas.dataset.boardReady = "false";
      revision += 1;
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.removeEventListener("start", markAdjusted);
      controls.dispose();
      canvas.removeEventListener("pointerdown", pointerDown);
      canvas.removeEventListener("pointermove", pointerMove);
      canvas.removeEventListener("pointerup", pointerUp);
      canvas.removeEventListener("pointercancel", pointerCancel);
      canvas.removeEventListener("webglcontextlost", contextLost);
      clear();
      gizmo.dispose();
      GHOST_MATERIAL.dispose();
      disposeBoardTree(selectionRing);
      disposeBoardTree(dropHint);
      sunlight.shadow.dispose();
      renderer.dispose();
    },
  };
}
