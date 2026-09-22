import * as THREE from "three";
import { OrbitControls } from "../vendor/three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "../vendor/three/examples/jsm/loaders/GLTFLoader.js";
import { boardImageRepeat, boardPosition, boardSignature, disposeBoardTree, fitBoardCamera, FLOOR_HEIGHT, FLOOR_WIDTH } from "./board-helpers.js";

export const CARD_BACK = "/assets/world/tutorial/cards/back.webp";
const TOP = 0.045;
const RANDOM_ANIMATION_PAUSE_MS = 1000;
const FLOOR_PLANE = new THREE.Plane(new THREE.Vector3(0, 1, 0), -TOP);

/** Convert a world-space point on the floor back into an authoritative [x%, y%, z] position. */
function boardPositionFromWorld(point) {
  return [
    Math.min(100, Math.max(0, point.x / 0.105 + 50)),
    Math.min(100, Math.max(0, point.z / 0.085 + 50)),
    0,
  ];
}

function material(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, roughness: 0.85, ...extra });
}

function box(parent, dimensions, position, materials) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...dimensions), materials);
  mesh.position.set(...position);
  mesh.castShadow = mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function makeFloor(root, board) {
  box(root, [12.45, 0.35, 10.45], [0, -0.24, 0], material("#62422d"));
  box(root, [12.5, 0.12, 10.5], [0, -0.08, 0], material("#a76e38"));
  box(root, [12.12, 0.07, 10.12], [0, -0.005, 0], material("#bca076"));
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(FLOOR_WIDTH, FLOOR_HEIGHT),
    material(board.palette?.[0] || "#d4be94"),
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = TOP;
  floor.receiveShadow = true;
  root.add(floor);
  return floor;
}

/** Apply the room's board image style by wrapping and repeating the floor texture. */
function applyFloorImageStyle(map, style) {
  const repeat = boardImageRepeat(style, map.image?.width, map.image?.height);
  if (!repeat) return;
  map.wrapS = repeat.wrapWidth ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  map.wrapT = repeat.wrapHeight ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  map.repeat.set(repeat.repeatX, repeat.repeatY);
  map.needsUpdate = true;
}

function unavailableMarker(parent) {
  const marker = new THREE.Mesh(
    new THREE.OctahedronGeometry(0.28),
    material("#e89a70", { wireframe: true }),
  );
  marker.position.y = 0.4;
  parent.add(marker);
  return marker;
}

/** Create the physical room board. render(state) updates it; dispose() releases its resources. */
export function createBoard({ canvas, overlay, onSelect }) {
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
  let signature = "";
  let roomId = "";
  let selection = null;
  let userAdjusted = false;
  let width = 0;
  let height = 0;
  let frame = 0;

  function isCurrent(entry) {
    return !disposed && current === entry && entry.revision === revision;
  }

  function status(entry) {
    if (!isCurrent(entry) || renderFailed) return;
    overlay.dataset.status = entry.errors.size ? "error" : entry.pending ? "loading" : "ready";
    canvas.dataset.boardReady = String(!entry.pending && !entry.errors.size);
    overlay.textContent = entry.errors.size
      ? `${[...entry.errors].join(" · ")}. Room cards and room exits remain available.`
      : entry.pending ? `${entry.label} · Loading room artwork…` : "";
  }

  function fail(entry, label) {
    entry.errors.add(label);
    status(entry);
  }

  function updateSelection() {
    selectionRing.visible = false;
    for (const object of current?.pickables || []) {
      if (object.userData.kind !== selection?.kind || object.userData.id !== selection?.id) continue;
      selectionRing.position.set(object.position.x, object.position.y + 0.06, object.position.z);
      selectionRing.visible = true;
      break;
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
    if (!position || disposed || blocked) {
      dropHint.visible = false;
      return;
    }
    const world = new THREE.Vector3(...boardPosition(position));
    world.y += TOP + 0.012;
    dropHint.position.copy(world);
    dropHint.visible = true;
  }

  function texture(entry, url, label, apply) {
    if (!url) {
      fail(entry, `${label} is missing`);
      return;
    }
    entry.pending += 1;
    textureLoader.load(url, map => {
      if (!isCurrent(entry)) {
        map.dispose();
        return;
      }
      map.colorSpace = THREE.SRGBColorSpace;
      map.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      apply(map);
      entry.pending -= 1;
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

  function stopPropAnimations(entry) {
    for (const timer of entry.animTimers || []) clearTimeout(timer);
    if (entry.animTimers) entry.animTimers.length = 0;
    for (const mixer of entry.mixers || []) mixer.stopAllAction();
    if (entry.mixers) entry.mixers.length = 0;
  }

  function startLoopedClip(entry, model, clip) {
    const mixer = new THREE.AnimationMixer(model);
    mixer.clipAction(clip).setLoop(THREE.LoopRepeat, Infinity).play();
    entry.mixers.push(mixer);
  }

  function startRandomClips(entry, model, clips) {
    const mixer = new THREE.AnimationMixer(model);
    entry.mixers.push(mixer);
    let lastIndex = -1;
    function pick() {
      if (!isCurrent(entry)) return;
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
        if (!isCurrent(entry)) return;
        entry.animTimers.push(setTimeout(pick, RANDOM_ANIMATION_PAUSE_MS));
      };
      mixer.addEventListener("finished", onFinished);
      action.play();
    }
    pick();
  }

  function playPropAnimation(entry, prop, model, clips) {
    const mode = typeof prop.animation === "string" ? prop.animation.trim() : "";
    if (!mode) return;
    if (!clips || !clips.length) {
      console.warn(`Prop ${prop.id} requests animation "${mode}" but the model has no animations.`);
      return;
    }
    if (mode === "auto") {
      startLoopedClip(entry, model, clips[0]);
      return;
    }
    if (mode === "random") {
      startRandomClips(entry, model, clips);
      return;
    }
    const clip = clips.find(candidate => candidate.name === mode);
    if (!clip) {
      console.warn(`Prop ${prop.id} requests unknown animation "${mode}".`);
      return;
    }
    startLoopedClip(entry, model, clip);
  }

  function addProp(entry, prop) {
    const group = new THREE.Group();
    register(entry, group, "prop", prop.id, prop.position);
    group.rotation.set(...(prop.rotation || [0, 0, 0]));
    group.scale.setScalar(Number.isFinite(prop.scale) ? prop.scale : 1);
    const placeholder = unavailableMarker(group);
    if (!prop.modelUrl) {
      fail(entry, `${prop.label} model is missing`);
      return;
    }
    entry.pending += 1;
    loader.load(prop.modelUrl, gltf => {
      if (!isCurrent(entry)) {
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
      const size = bounds.getSize(new THREE.Vector3());
      // Imported models have different authoring units; normalize their presentation
      // inside the authoritative instance transform, as in the reference board.
      const kind = prop.propId || "";
      const desired = /sofa|bed|dollhouse/.test(kind) ? 3
        : /rug/.test(kind) ? 2.8 : /shelf|shower|counter|door|portal/.test(kind) ? 2.5 : 1.8;
      const scale = desired / Math.max(size.x, size.y, size.z, 0.01);
      const visual = new THREE.Group();
      visual.scale.setScalar(scale);
      visual.position.y = -bounds.min.y * scale;
      visual.add(model);
      model.traverse(node => {
        if (node.isMesh) node.castShadow = node.receiveShadow = true;
      });
      group.remove(placeholder);
      disposeBoardTree(placeholder);
      group.add(visual);
      playPropAnimation(entry, prop, model, gltf.animations || []);
      entry.modelScenes.push(...(gltf.scenes || [model]));
      entry.pending -= 1;
      if (!userAdjusted) fit(true);
      updateSelection();
      status(entry);
    }, undefined, () => {
      if (!isCurrent(entry)) return;
      entry.pending -= 1;
      fail(entry, `Could not load ${prop.label} model`);
    });
  }

  function addCard(entry, card) {
    const group = new THREE.Group();
    register(entry, group, "room-card", card.stackId, card.position);
    const edge = material("#d5b887");
    const front = material("#fff7e3");
    const back = material("#193e55");
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

  function clear() {
    if (!current) return;
    stopPropAnimations(current);
    scene.remove(current.root);
    // Include non-default GLTF scenes; they can share materials with the active scene.
    disposeBoardTree([current.root, ...current.modelScenes]);
    current = null;
    selectionRing.visible = false;
    dropHint.visible = false;
  }

  function rebuild(room) {
    revision += 1;
    clear();
    const changedRoom = roomId !== room.id;
    roomId = room.id;
    if (changedRoom) userAdjusted = false;
    const entry = {
      root: new THREE.Group(), revision, pickables: [], modelScenes: [],
      mixers: [], animTimers: [],
      pending: 0, errors: new Set(), label: room.label,
    };
    current = entry;
    scene.add(entry.root);
    const board = room.board || {};
    const floor = makeFloor(entry.root, board);
    texture(entry, board.imageUrl, "floor artwork", map => {
      applyFloorImageStyle(map, board.imageStyle);
      floor.material.map = map;
      floor.material.color.set("#ffffff");
      floor.material.needsUpdate = true;
    });
    for (const prop of room.props || []) addProp(entry, prop);
    for (const card of room.roomCards || []) addCard(entry, card);
    if (!userAdjusted) fit(true);
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
    // Resizing fits the new viewport but preserves the user's orbit direction.
    fit(!userAdjusted);
  }

  function pointerDown(event) {
    if (blocked || event.button !== 0) return;
    if (!pointers.size) gestureMoved = false;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size > 1) gestureMoved = true;
  }

  function pointerMove(event) {
    const start = pointers.get(event.pointerId);
    if (start && Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) gestureMoved = true;
  }

  function pointerUp(event) {
    const start = pointers.get(event.pointerId);
    pointers.delete(event.pointerId);
    if (blocked || !start || gestureMoved || pointers.size
      || Math.hypot(event.clientX - start.x, event.clientY - start.y) > 6) return;
    const bounds = canvas.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    pointer.set((event.clientX - bounds.left) / bounds.width * 2 - 1, -(event.clientY - bounds.top) / bounds.height * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    let object = raycaster.intersectObjects(current?.pickables || [], true)[0]?.object;
    while (object && !object.userData.kind) object = object.parent;
    if (object) {
      onSelect({ kind: object.userData.kind, id: object.userData.id });
      return;
    }
    if (roomId) onSelect({ kind: "room", id: roomId });
  }

  function pointerCancel(event) {
    pointers.delete(event.pointerId);
    gestureMoved = true;
  }

  function markAdjusted() {
    if (!blocked) userAdjusted = true;
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
  function animate() {
    if (disposed || renderFailed) return;
    try {
      const delta = Math.min(clock.getDelta(), 0.1);
      for (const mixer of current?.mixers || []) mixer.update(delta);
      if (!blocked) controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(animate);
    } catch {
      contextLost({ preventDefault() {} });
    }
  }
  animate();

  return {
    /** Apply normalized server state without rebuilding for chat, peeps, or selection changes. */
    async render(state) {
      if (disposed) return;
      selection = state.selection;
      controls.enableDamping = !state.ui?.reducedMotion;
      blocked = Boolean(state.views?.main || state.views?.details || state.views?.auth
        || state.views?.commandPalette || !state.user?.initialStickerComplete);
      controls.enabled = !blocked && !renderFailed;
      if (blocked) {
        pointers.clear();
        gestureMoved = true;
      }
      if (!state.room) {
        revision += 1;
        clear();
        signature = "";
        roomId = "";
        canvas.dataset.boardReady = "false";
        if (!renderFailed) {
          overlay.textContent = "Your room will appear here.";
          overlay.dataset.status = "idle";
        }
        return;
      }
      const nextSignature = boardSignature(state.room);
      if (nextSignature !== signature) {
        signature = nextSignature;
        rebuild(state.room);
      }
      updateSelection();
    },
    /** Map a screen point to the authoritative floor position and projected screen point. */
    screenToBoardPosition,
    /** Project an authoritative [x%, y%, z] position into canvas screen coordinates. */
    projectPositionToScreen,
    /** Show or clear the floor marker used as a drag drop target. */
    setDropHint,
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
      disposeBoardTree(selectionRing);
      disposeBoardTree(dropHint);
      sunlight.shadow.dispose();
      renderer.dispose();
    },
  };
}
