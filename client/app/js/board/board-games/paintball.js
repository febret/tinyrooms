import * as THREE from "three";

import { boardPosition } from "../board-helpers.js";
import { isFreshShot, shotProgress, splatTransform } from "./paintball-state.js";

const TOP = 0.045;
const SHOT_FADE = 0.35;
const IMPACT_BURST = 0.42;
const ACCENT = "#ff4d6d";
const DEFAULT_COLORS = ["#ff4d6d", "#4ea8ff", "#5cf29a", "#ffe066", "#c77dff"];

/** Board coordinate that keeps a valid zero while defaulting malformed values. */
export function boardCoordinate(value, fallback = 50) {
  if (value === null || value === undefined || value === "") return fallback;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function makeSplatTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const painter = canvas.getContext("2d");
  if (!painter) return new THREE.CanvasTexture(canvas);
  painter.clearRect(0, 0, 128, 128);
  painter.fillStyle = "#ffffff";
  const blobs = [
    [64, 64, 34], [40, 52, 18], [88, 58, 16], [54, 92, 15],
    [92, 90, 11], [30, 84, 9], [100, 40, 8], [22, 40, 7],
  ];
  for (const [x, y, radius] of blobs) {
    painter.beginPath();
    painter.arc(x, y, radius, 0, Math.PI * 2);
    painter.fill();
  }
  for (let index = 0; index < 26; index += 1) {
    const angle = (index / 26) * Math.PI * 2;
    const distance = 46 + (index % 4) * 7;
    painter.beginPath();
    painter.arc(64 + Math.cos(angle) * distance, 64 + Math.sin(angle) * distance, 2 + (index % 3), 0, Math.PI * 2);
    painter.fill();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  return texture;
}

function disposeTree(root) {
  const geometries = new Set();
  const materials = new Set();
  root?.traverse(node => {
    if (node.geometry) geometries.add(node.geometry);
    if (node.material) {
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
        materials.add(material);
      }
    }
  });
  for (const geometry of geometries) geometry.dispose();
  for (const material of materials) material.dispose();
}

/** Render the server-authored paintball arena: splats and shots. */
export function createPaintballRenderer(context) {
  const group = new THREE.Group();
  const accentGroup = new THREE.Group();
  const splatGroup = new THREE.Group();
  const shotGroup = new THREE.Group();
  group.add(accentGroup, splatGroup, shotGroup);
  context.root.add(group);

  const splatTexture = makeSplatTexture();
  const splatGeometry = new THREE.PlaneGeometry(1, 1);
  const splatMaterials = new Map();
  const ballGeometry = new THREE.SphereGeometry(0.075, 12, 8);
  const ballMaterials = new Map();
  const splats = new Map();
  const pendingSplats = new Map();
  const activeShots = [];
  const seenShots = new Set();
  let accentsKey = "";
  let game = null;
  let state = null;
  let roomDark = false;
  let reducedMotion = false;

  function splatMaterial(color) {
    if (!splatMaterials.has(color)) {
      splatMaterials.set(color, new THREE.MeshBasicMaterial({
        map: splatTexture,
        color,
        transparent: true,
        opacity: 0.9,
        depthWrite: false,
        side: THREE.DoubleSide,
      }));
    }
    return splatMaterials.get(color);
  }

  function ballMaterial(color) {
    if (!ballMaterials.has(color)) {
      ballMaterials.set(color, new THREE.MeshBasicMaterial({ color, toneMapped: false }));
    }
    return ballMaterials.get(color);
  }

  function buildAccents() {
    const colors = Array.isArray(game?.config?.palette) ? game.config.palette : DEFAULT_COLORS;
    const corners = [[7, 7], [93, 7], [7, 93], [93, 93]];
    corners.forEach((corner, index) => {
      const post = new THREE.Mesh(
        new THREE.CylinderGeometry(0.06, 0.08, 0.5, 8),
        new THREE.MeshBasicMaterial({ color: colors[index % colors.length], toneMapped: false }),
      );
      const world = new THREE.Vector3(...boardPosition([corner[0], corner[1], 0]));
      post.position.set(world.x, TOP + 0.25, world.z);
      accentGroup.add(post);
      const glow = new THREE.Mesh(
        new THREE.SphereGeometry(0.11, 10, 8),
        new THREE.MeshBasicMaterial({ color: colors[index % colors.length], transparent: true, opacity: 0.65, toneMapped: false }),
      );
      glow.position.set(world.x, TOP + 0.52, world.z);
      accentGroup.add(glow);
    });
  }

  function addSplatMesh(id, splat) {
    const transform = splatTransform(id, splats.size);
    const mesh = new THREE.Mesh(splatGeometry, splatMaterial(String(splat.color || "#ff4d6d")));
    const world = new THREE.Vector3(...boardPosition([boardCoordinate(splat.x), boardCoordinate(splat.y), 0]));
    mesh.position.set(world.x, TOP + 0.004 + splats.size * 0.0004, world.z);
    mesh.rotation.x = -Math.PI / 2;
    mesh.rotation.z = Number(splat.rotation ?? transform.rotation);
    const size = (Number(splat.size) || transform.scale) * 0.95;
    mesh.scale.set(size, size, 1);
    splatGroup.add(mesh);
    splats.set(id, mesh);
  }

  function syncSplats() {
    const wanted = new Map();
    for (const splat of Array.isArray(state?.splats) ? state.splats : []) {
      const id = String(splat?.id || "");
      if (id) wanted.set(id, splat);
    }
    for (const id of [...splats.keys()]) {
      if (!wanted.has(id)) {
        const mesh = splats.get(id);
        mesh.removeFromParent();
        splats.delete(id);
      }
    }
    for (const id of [...pendingSplats.keys()]) {
      if (!wanted.has(id)) pendingSplats.delete(id);
    }
    for (const [id, splat] of wanted) {
      if (splats.has(id) || pendingSplats.has(id)) continue;
      const owner = id.split(":")[0];
      if (activeShots.some(record => String(record.id) === owner)) {
        pendingSplats.set(id, splat);
        continue;
      }
      addSplatMesh(id, splat);
    }
  }

  function flushSplatsForShot(shotId) {
    for (const [id, splat] of [...pendingSplats]) {
      if (id.split(":")[0] !== String(shotId)) continue;
      pendingSplats.delete(id);
      addSplatMesh(id, splat);
    }
  }

  function spawnShot(shot) {
    const color = String(shot.color || "#ff4d6d");
    const start = new THREE.Vector3(...boardPosition([boardCoordinate(shot.from?.[0]), boardCoordinate(shot.from?.[1]), 0]));
    const end = new THREE.Vector3(...boardPosition([boardCoordinate(shot.impact?.[0]), boardCoordinate(shot.impact?.[1]), 0]));
    start.y += TOP + 0.42;
    end.y += TOP + 0.42;

    const tracerGeometry = new THREE.BufferGeometry().setFromPoints([start, end]);
    const tracer = new THREE.Line(
      tracerGeometry,
      new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.7, toneMapped: false }),
    );
    shotGroup.add(tracer);

    const ball = new THREE.Mesh(ballGeometry, ballMaterial(color));
    ball.position.copy(start);
    shotGroup.add(ball);

    const muzzle = new THREE.Mesh(
      new THREE.SphereGeometry(0.16, 10, 8),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85, toneMapped: false }),
    );
    muzzle.position.copy(start);
    shotGroup.add(muzzle);

    const burst = new THREE.Mesh(
      new THREE.RingGeometry(0.12, 0.2, 22),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, side: THREE.DoubleSide, toneMapped: false }),
    );
    burst.position.copy(end);
    burst.rotation.x = -Math.PI / 2;
    shotGroup.add(burst);

    const record = {
      id: shot.id,
      color,
      victimId: shot.hit ? String(shot.victim_id || "") : "",
      duration: Math.max(120, Number(shot.flight_ms) || 320) / 1000,
      elapsed: reducedMotion ? 1 : 0,
      start,
      end,
      tracer,
      ball,
      muzzle,
      burst,
      reacted: false,
      done: false,
    };
    if (reducedMotion) {
      ball.position.copy(end);
      tracer.visible = false;
      muzzle.visible = false;
    }
    activeShots.push(record);
  }

  function syncShots() {
    const now = Date.now();
    for (const shot of Array.isArray(state?.shots) ? state.shots : []) {
      const id = String(shot?.id ?? "");
      if (!id || seenShots.has(id)) continue;
      seenShots.add(id);
      if (!isFreshShot(shot, now)) continue;
      spawnShot(shot);
    }
    if (seenShots.size > 200) seenShots.clear();
  }

  function removeShot(record) {
    for (const node of [record.tracer, record.muzzle, record.burst]) {
      node.removeFromParent();
      disposeTree(node);
    }
    // The ball reuses shared geometry and per-color materials.
    record.ball.removeFromParent();
  }

  function advanceShots(delta) {
    for (let index = activeShots.length - 1; index >= 0; index -= 1) {
      const record = activeShots[index];
      if (!record.reacted) {
        record.elapsed += delta;
        const flight = Math.min(1, record.elapsed / record.duration);
        const eased = reducedMotion ? 1 : shotProgress(record.elapsed * 1000, record.duration * 1000);
        record.ball.position.lerpVectors(record.start, record.end, flight);
        record.ball.position.y += reducedMotion ? 0 : Math.sin(Math.PI * eased) * 0.5;
        record.muzzle.material.opacity = Math.max(0, 0.85 * (1 - record.elapsed / 0.18));
        record.muzzle.scale.setScalar(1 + record.elapsed * 3);
        if (record.elapsed >= record.duration) {
          record.reacted = true;
          record.tracer.visible = false;
          record.muzzle.visible = false;
          record.ball.visible = false;
          record.burst.material.opacity = reducedMotion ? 0 : 0.95;
          flushSplatsForShot(record.id);
          if (record.victimId) {
            context.reactSprite?.(record.victimId, { color: record.color, duration: 0.6 });
          }
        }
      } else {
        record.burst.material.opacity = Math.max(0, record.burst.material.opacity - delta / IMPACT_BURST);
        record.burst.scale.setScalar(1 + (1 - record.burst.material.opacity) * 3);
        if (record.burst.material.opacity <= 0.01) {
          record.done = true;
        }
      }
      if (record.done) {
        removeShot(record);
        activeShots.splice(index, 1);
      }
    }
  }

  function clear() {
    for (const record of activeShots) removeShot(record);
    activeShots.length = 0;
    seenShots.clear();
    for (const mesh of splats.values()) mesh.removeFromParent();
    splats.clear();
    pendingSplats.clear();
    for (const node of [...accentGroup.children]) {
      accentGroup.remove(node);
      disposeTree(node);
    }
    accentsKey = "";
    game = null;
    state = null;
    roomDark = false;
    group.visible = false;
  }

  function sync(next) {
    game = next.game || null;
    state = next.state || null;
    roomDark = Boolean(next.dark);
    reducedMotion = Boolean(next.reducedMotion);
    const active = Boolean(game && !roomDark);
    group.visible = active;
    if (!active) {
      clear();
      return;
    }
    const nextAccentsKey = JSON.stringify(game.config?.palette || DEFAULT_COLORS);
    if (nextAccentsKey !== accentsKey) {
      accentsKey = nextAccentsKey;
      for (const node of [...accentGroup.children]) {
        accentGroup.remove(node);
        disposeTree(node);
      }
      buildAccents();
    }
    syncShots();
    syncSplats();
    context.invalidate();
  }

  function advance(delta) {
    if (!group.visible) return;
    advanceShots(delta);
  }

  function isAnimating() {
    return group.visible && activeShots.length > 0;
  }

  function itemCount() {
    return splats.size + activeShots.length;
  }

  function dispose() {
    clear();
    splatGeometry.dispose();
    ballGeometry.dispose();
    splatTexture.dispose();
    for (const material of splatMaterials.values()) material.dispose();
    for (const material of ballMaterials.values()) material.dispose();
    group.removeFromParent();
  }

  return {
    sync,
    advance,
    isAnimating,
    itemCount,
    pointerUp: () => false,
    clear,
    dispose,
  };
}
