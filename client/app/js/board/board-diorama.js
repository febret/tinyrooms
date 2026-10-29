// Procedural TinyTown tabletop diorama.
//
// The town board is not a baked prop: an irregular height-field island is
// generated at runtime, then dressed with roads, trees, lamps, the harbour,
// and the residents' GLB house models served per viewer.

import * as THREE from "three";
import { GLTFLoader } from "../../vendor/three/examples/jsm/loaders/GLTFLoader.js";

import { withBase } from "../base-path.js";
import { disposeBoardTree } from "./board-helpers.js";
import {
  cyclePhaseAt,
  daylightForPhase,
  normalizeDayCycle,
} from "./board-diorama-daylight.js";
import {
  HALF_DEPTH,
  HALF_WIDTH,
  WATER_LEVEL,
  addShoreline,
  buildTerrain,
  hash2,
  makeRibbon,
  seededRandom,
  terrainHeightAt,
} from "./board-diorama-terrain.js";
import {
  makeCobbleTexture,
  makeDetailTexture,
  makeGlowTexture,
  makeGroundTexture,
  makePlaqueTexture,
  makeStarTexture,
  makeWoodTexture,
} from "./board-diorama-textures.js";

export const DIORAMA_BOARD_TYPE = "diorama";
const GROUP_LIFT = 0.045;
const LAMP_GLOW = "#ffd58a";

const HOUSE_FOOTPRINT_Y = 0.055;
const HOUSE_REVEAL_MS = 980;

function easeOutBack(value) {
  const c1 = 1.34;
  const c3 = c1 + 1;
  return 1 + c3 * (value - 1) ** 3 + c1 * (value - 1) ** 2;
}

function createHouseLayer(parent, materials, houseData) {
  const loader = new GLTFLoader();
  const records = [];
  const pickables = [];
  let disposed = false;
  let lastRevealShadowAt = 0;

  function houseColor(info, index) {
    const palette = Array.isArray(info.palette) ? info.palette : [];
    const raw = palette[index % Math.max(1, palette.length)] || info.district_accent || "#87977c";
    const color = new THREE.Color(raw);
    if (color.r + color.g + color.b < 0.9) color.offsetHSL(0, 0.02, 0.17);
    return color;
  }

  function setTextured(record, textured) {
    if (record.mode === (textured ? "full" : "footprint")) return;
    record.mode = textured ? "full" : "footprint";
    for (const entry of record.meshes) {
      if (textured) {
        entry.mesh.material = Array.isArray(entry.materials)
          ? [...entry.materials]
          : entry.materials;
      } else {
        entry.mesh.material = Array.isArray(entry.materials)
          ? entry.materials.map(() => record.footprint)
          : record.footprint;
      }
    }
  }

  function scheduleReveal(record) {
    record.revealDone = false;
    record.revealAt = performance.now() + 140 + record.order * 48;
  }

  function makeFallback(record) {
    const group = record.visual;
    box(group, [0.72, 0.34, 0.54], [0, 0.17, 0], record.footprint);
    const roof = new THREE.Mesh(gableGeometry(0.84, 0.65, 0.3), record.footprint);
    roof.position.y = 0.34;
    roof.castShadow = true;
    roof.receiveShadow = true;
    group.add(roof);
    box(group, [0.08, 0.15, 0.03], [0, 0.09, 0.28], record.footprint);
    record.top = 0.7;
    record.star.position.y = record.top + 0.22;
    record.mode = "";
    setTextured(record, false);
    scheduleReveal(record);
  }

  function loadHouse(record, info, index) {
    loader.loadAsync(withBase(info.model_url)).then(gltf => {
      if (disposed) {
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        return;
      }
      const model = gltf.scene || (gltf.scenes || [])[0];
      if (!model) {
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        makeFallback(record);
        return;
      }
      const initial = new THREE.Box3().setFromObject(model);
      const size = initial.getSize(new THREE.Vector3());
      const widest = Math.max(size.x, size.z);
      if (!Number.isFinite(widest) || widest <= 0) {
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        makeFallback(record);
        return;
      }
      const target = Math.max(0.55, Number(info.lot?.scale) || 1) * 1.05;
      model.scale.multiplyScalar(target / widest);
      model.updateMatrixWorld(true);
      const fitted = new THREE.Box3().setFromObject(model);
      const center = fitted.getCenter(new THREE.Vector3());
      model.position.x -= center.x;
      model.position.z -= center.z;
      model.position.y -= fitted.min.y;
      model.traverse(node => {
        if (!node.isMesh) return;
        node.castShadow = true;
        node.receiveShadow = true;
        const materialsForMesh = Array.isArray(node.material) ? [...node.material] : node.material;
        record.meshes.push({ mesh: node, materials: materialsForMesh });
      });
      record.visual.add(model);
      record.model = model;
      // Measure from `fitted`, not from `record.visual`: the house group is
      // scaled to HOUSE_FOOTPRINT_Y until the reveal animation finishes, so a
      // world-space box over `record.visual` would report a squashed height.
      const houseHeight = Math.max(0, fitted.max.y - fitted.min.y);
      record.top = Math.max(0.55, houseHeight);
      record.star.position.y = record.top + 0.24;
      const proxyWidth = target * 0.98;
      record.pick.geometry.dispose();
      record.pick.geometry = new THREE.BoxGeometry(proxyWidth, record.top + 0.12, proxyWidth);
      record.pick.position.y = (record.top + 0.12) / 2;
      record.mode = "";
      setTextured(record, false);
      record.group.scale.y = HOUSE_FOOTPRINT_Y;
      scheduleReveal(record);
    }).catch(error => {
      console.warn(`TinyTown house model failed: ${info.id}`, error);
      if (!disposed) makeFallback(record);
    });
  }

  function lotGroundHeight(x, z, scale) {
    let height = terrainHeightAt(x, z);
    const radius = 0.5 * scale;
    for (let step = 0; step < 8; step += 1) {
      const angle = step / 8 * Math.PI * 2;
      height = Math.max(height, terrainHeightAt(
        x + Math.cos(angle) * radius,
        z + Math.sin(angle) * radius,
      ));
    }
    return height;
  }

  (Array.isArray(houseData) ? houseData : []).forEach((info, index) => {
    const lot = info.lot || {};
    const x = Number(lot.x) || 0;
    const z = Number(lot.z) || 0;
    const scale = Math.max(0.55, Number(lot.scale) || 1);
    const group = new THREE.Group();
    group.name = `tinytown-house-${info.id}`;
    group.position.set(x, lotGroundHeight(x, z, scale) + 0.01, z);
    group.rotation.y = Number(lot.rotation) || 0;
    group.userData.kind = "house";
    group.userData.id = info.id;
    group.scale.y = HOUSE_FOOTPRINT_Y;
    parent.add(group);

    const padMaterial = materials.standard("#b9a983", { roughness: 0.98 });
    cylinder(group, 0.5 * scale, 0.54 * scale, 0.035, 20, [0, 0.012, 0], padMaterial);

    const pickMaterial = new THREE.MeshBasicMaterial({
      transparent: true, opacity: 0, depthWrite: false, colorWrite: false,
    });
    const pick = new THREE.Mesh(new THREE.BoxGeometry(0.9 * scale, 1.0, 0.9 * scale), pickMaterial);
    pick.position.y = 0.5;
    pick.castShadow = false;
    pick.receiveShadow = false;
    group.add(pick);

    const visual = new THREE.Group();
    group.add(visual);

    const footprint = new THREE.MeshStandardMaterial({
      color: houseColor(info, index),
      roughness: 1,
      metalness: 0,
      flatShading: true,
    });
    const star = new THREE.Sprite(new THREE.SpriteMaterial({
      map: materials.starTexture,
      color: "#fff1b8",
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    }));
    star.scale.set(0.34, 0.34, 1);
    star.visible = false;
    star.position.y = 1;
    group.add(star);

    const ringMaterial = new THREE.MeshBasicMaterial({
      color: info.district_accent || "#ffe2a0",
      transparent: true,
      opacity: 0,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.21, 0.27, 28), ringMaterial);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.045;
    group.add(ring);

    const record = {
      info,
      group,
      visual,
      pick,
      star,
      ring,
      ringMaterial,
      footprint,
      meshes: [],
      model: null,
      mode: "",
      owned: Boolean(info.owned),
      available: Boolean(info.available || info.owned),
      top: 0.8,
      order: index,
      revealAt: Number.POSITIVE_INFINITY,
      revealDone: false,
    };
    records.push(record);
    pickables.push(group);
    if (record.available) loadHouse(record, info, index);
  });

  function update(elapsed, { reducedMotion = false, requestShadow = () => {} } = {}) {
    const now = performance.now();
    let animating = false;
    for (const record of records) {
      if (record.available) {
        const raw = reducedMotion ? 1 : Math.min(1, Math.max(0, (now - record.revealAt) / HOUSE_REVEAL_MS));
        const eased = raw >= 1 ? 1 : Math.max(0, easeOutBack(raw));
        const lift = HOUSE_FOOTPRINT_Y + (1 - HOUSE_FOOTPRINT_Y) * eased;
        record.group.scale.y = lift;
        if (!record.revealDone && raw > 0.08) setTextured(record, true);
        if (raw >= 1) record.revealDone = true;
        else animating = true;
        const pulse = Math.min(1, raw / 0.72);
        record.ringMaterial.opacity = raw < 1 ? Math.sin(pulse * Math.PI) * 0.72 : 0;
        record.ring.scale.setScalar(0.6 + pulse * 1.6);
        if (record.owned) {
          const alpha = Math.min(1, Math.max(0, (raw - 0.55) / 0.45));
          record.star.visible = alpha > 0.01;
          record.star.material.opacity = alpha;
          if (record.star.visible) {
            const seed = Number.isFinite(record.revealAt) ? record.revealAt * 0.001 : 0;
            const pulse = 1 + Math.sin(elapsed * 2.6 + seed) * 0.06;
            const size = 0.34 * pulse * (0.75 + alpha * 0.25);
            record.star.scale.set(size, size, 1);
            record.star.position.y = record.top + 0.24 + Math.sin(elapsed * 1.7 + seed) * 0.035;
            record.star.material.rotation = Math.sin(elapsed * 0.7 + seed) * 0.12;
          }
        } else {
          record.star.visible = false;
        }
      } else {
        record.group.scale.y = HOUSE_FOOTPRINT_Y;
        setTextured(record, false);
        record.star.visible = false;
        record.ringMaterial.opacity = 0;
      }
    }
    if (animating && now - lastRevealShadowAt > 90) {
      lastRevealShadowAt = now;
      requestShadow();
    }
  }

  function dispose() {
    disposed = true;
    for (const record of records) {
      if (record.model) setTextured(record, true);
      record.footprint.dispose();
    }
  }

  return { pickables, update, dispose };
}

function makeWaterMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true,
    depthWrite: false,
    uniforms: {
      uTime: { value: 0 },
      uLight: { value: 1 },
      uNight: { value: 0 },
      uDeep: { value: new THREE.Color("#0f4a5e") },
      uShallow: { value: new THREE.Color("#55a7a2") },
    },
    vertexShader: `
      uniform float uTime;
      varying vec3 vWorld;
      varying float vWave;
      void main() {
        vec3 transformed = position;
        float wave =
          sin(position.x * 3.4 + uTime * 1.15) * 0.5 +
          sin(position.z * 5.2 - uTime * 1.45) * 0.3 +
          sin((position.x + position.z) * 7.3 + uTime * 2.0) * 0.18;
        transformed.y += wave * 0.018;
        vWave = wave;
        vec4 world = modelMatrix * vec4(transformed, 1.0);
        vWorld = world.xyz;
        gl_Position = projectionMatrix * viewMatrix * world;
      }
    `,
    fragmentShader: `
      uniform float uTime;
      uniform float uLight;
      uniform float uNight;
      uniform vec3 uDeep;
      uniform vec3 uShallow;
      varying vec3 vWorld;
      varying float vWave;

      void main() {
        vec3 viewDirection = normalize(cameraPosition - vWorld);
        vec2 slope = vec2(
          cos(vWorld.x * 3.4 + uTime * 1.15) * 3.4 * 0.009
            + cos((vWorld.x + vWorld.z) * 7.3 + uTime * 2.0) * 7.3 * 0.0032,
          cos(vWorld.z * 5.2 - uTime * 1.45) * 5.2 * 0.0054
            + cos((vWorld.x + vWorld.z) * 7.3 + uTime * 2.0) * 7.3 * 0.0032
        );
        vec3 normal = normalize(vec3(-slope.x, 1.0, -slope.y));
        vec3 lightDirection = normalize(vec3(-0.45, 0.82, 0.3));
        float fresnel = pow(1.0 - max(dot(normal, viewDirection), 0.0), 2.4);
        float specular = pow(max(dot(reflect(-lightDirection, normal), viewDirection), 0.0), 84.0);
        float crest = smoothstep(0.76, 1.0,
          sin(vWorld.x * 8.5 + uTime * 1.8) * sin(vWorld.z * 11.0 - uTime * 1.5) * 0.5 + 0.5
        ) * 0.045;
        vec3 color = mix(uDeep, uShallow, 0.3 + fresnel * 0.52 + vWave * 0.1);
        color += vec3(0.12, 0.26, 0.3) * fresnel * 0.5;
        color += vec3(1.0, 0.9, 0.68) * specular * (0.2 + uLight * 0.8);
        color += vec3(0.62, 0.82, 0.82) * crest * (0.2 + uLight * 0.8);
        color *= mix(0.58, 1.0, uLight);
        color = mix(color, color * vec3(0.6, 0.7, 0.93) + vec3(0.01, 0.024, 0.06), uNight * 0.4);
        color += vec3(0.12, 0.2, 0.3) * uNight * fresnel * 0.3;
        color += vec3(0.014, 0.035, 0.055) * uNight;
        gl_FragColor = vec4(color, 0.95);
      }
    `,
  });
}

function createPalette() {
  const cache = new Map();
  const standard = (color, extra = {}) => {
    const key = `${color}|${JSON.stringify(extra)}`;
    let material = cache.get(key);
    if (!material) {
      material = new THREE.MeshStandardMaterial({ color, roughness: 0.86, ...extra });
      cache.set(key, material);
    }
    return material;
  };
  return { cache, standard };
}

function box(parent, size, position, material, rotation = [0, 0, 0]) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.position.set(...position);
  mesh.rotation.set(...rotation);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function cylinder(parent, radiusTop, radiusBottom, height, segments, position, material) {
  const mesh = new THREE.Mesh(
    new THREE.CylinderGeometry(radiusTop, radiusBottom, height, segments),
    material,
  );
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

function gableGeometry(width, depth, height) {
  const halfWidth = width / 2;
  const halfDepth = depth / 2;
  const positions = new Float32Array([
    -halfWidth, 0, halfDepth, halfWidth, 0, halfDepth, 0, height, halfDepth,
    halfWidth, 0, -halfDepth, -halfWidth, 0, -halfDepth, 0, height, -halfDepth,
    -halfWidth, 0, -halfDepth, -halfWidth, 0, halfDepth, 0, height, halfDepth,
    0, height, -halfDepth,
    halfWidth, 0, halfDepth, halfWidth, 0, -halfDepth, 0, height, -halfDepth,
    0, height, halfDepth,
  ]);
  const indices = [
    0, 1, 2, 3, 4, 5,
    6, 7, 8, 6, 8, 9,
    10, 11, 12, 10, 12, 13,
  ];
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function addBoat(parent, x, z, sailColor, phase, materials) {
  const group = new THREE.Group();
  const baseY = WATER_LEVEL + 0.045;
  group.position.set(x, baseY, z);
  group.rotation.y = phase * 1.7;
  parent.add(group);

  const hull = materials.standard("#7b4e34", { roughness: 0.8 });
  const trim = materials.standard("#e8d6ad");
  const sail = materials.standard(sailColor, { side: THREE.DoubleSide, roughness: 0.9 });
  box(group, [0.38, 0.08, 0.15], [0, 0, 0], hull);
  box(group, [0.28, 0.025, 0.16], [0, 0.045, 0], trim);
  cylinder(group, 0.012, 0.012, 0.5, 6, [0.02, 0.28, 0], hull);
  const sailShape = new THREE.BufferGeometry();
  sailShape.setAttribute("position", new THREE.Float32BufferAttribute([
    0.035, 0.15, 0, 0.035, 0.49, 0, 0.27, 0.18, 0,
  ], 3));
  sailShape.computeVertexNormals();
  const sailMesh = new THREE.Mesh(sailShape, sail);
  sailMesh.castShadow = true;
  group.add(sailMesh);

  return { group, baseY, phase };
}

function addPier(parent, materials) {
  const group = new THREE.Group();
  parent.add(group);
  const start = [3.12, 0.72];
  const end = [4.18, 0.28];
  const dx = end[0] - start[0];
  const dz = end[1] - start[1];
  const length = Math.hypot(dx, dz);
  const angle = Math.atan2(dz, dx);
  const wood = materials.wood;
  const trim = materials.standard("#a8865f", { roughness: 0.86 });
  const count = 16;
  for (let index = 0; index < count; index += 1) {
    const t = index / (count - 1);
    const x = start[0] + dx * t;
    const z = start[1] + dz * t;
    const plank = box(group, [length / count * 0.88, 0.034, 0.2], [x, WATER_LEVEL + 0.055, z], wood);
    plank.rotation.y = angle + Math.PI / 2;
  }
  for (const t of [0.08, 0.33, 0.63, 0.93]) {
    const x = start[0] + dx * t;
    const z = start[1] + dz * t;
    for (const side of [-0.09, 0.09]) {
      box(group, [0.035, 0.44, 0.035], [
        x + Math.cos(angle) * side, WATER_LEVEL - 0.14, z + Math.sin(angle) * side,
      ], wood);
    }
  }
  box(group, [0.18, 0.14, 0.13], [end[0] + 0.04, WATER_LEVEL + 0.14, end[1] + 0.1], trim);
  box(group, [0.16, 0.12, 0.12], [end[0] - 0.08, WATER_LEVEL + 0.13, end[1] - 0.06], trim);
  const post = materials.standard("#3b3a35", { metalness: 0.35, roughness: 0.6 });
  cylinder(group, 0.012, 0.016, 0.34, 8, [end[0], WATER_LEVEL + 0.23, end[1]], post);
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.038, 10, 8), materials.lampBulb);
  bulb.position.set(end[0], WATER_LEVEL + 0.4, end[1]);
  group.add(bulb);
  const glow = new THREE.Sprite(materials.glowMaterial);
  glow.position.copy(bulb.position);
  glow.scale.set(0.48, 0.48, 1);
  group.add(glow);
  return group;
}

function addLamp(parent, x, z, materials, lights) {
  const ground = terrainHeightAt(x, z);
  const group = new THREE.Group();
  group.position.set(x, ground, z);
  parent.add(group);
  const post = materials.standard("#3b3a35", { metalness: 0.35, roughness: 0.6 });
  cylinder(group, 0.012, 0.018, 0.48, 8, [0, 0.24, 0], post);
  box(group, [0.11, 0.02, 0.02], [0.045, 0.46, 0], post);
  const bulb = new THREE.Mesh(new THREE.SphereGeometry(0.04, 10, 8), materials.lampBulb);
  bulb.position.set(0.095, 0.43, 0);
  group.add(bulb);
  const glow = new THREE.Sprite(materials.glowMaterial);
  glow.position.copy(bulb.position);
  glow.scale.set(0.8, 0.8, 1);
  group.add(glow);
  const light = new THREE.PointLight(LAMP_GLOW, 0, 2.3, 2);
  light.position.copy(bulb.position);
  group.add(light);
  lights.push(light);
  return group;
}

function addTrees(parent, spots, type, materials) {
  if (!spots.length) return;
  const dummy = new THREE.Object3D();
  const trunkMaterial = materials.standard("#5a402c", { roughness: 1 });
  const trunkGeometry = new THREE.CylinderGeometry(0.032, 0.055, 1, 6);
  const trunks = new THREE.InstancedMesh(trunkGeometry, trunkMaterial, spots.length);
  trunks.castShadow = true;
  trunks.receiveShadow = true;

  const canopyGeometry = type === "conifer"
    ? new THREE.ConeGeometry(1, 2.2, 7)
    : new THREE.IcosahedronGeometry(1, 1);
  if (type !== "conifer") {
    const position = canopyGeometry.getAttribute("position");
    for (let index = 0; index < position.count; index += 1) {
      const x = position.getX(index);
      const y = position.getY(index);
      const z = position.getZ(index);
      const bump = 0.86 + hash2(x * 4.1 + index, z * 5.7 - index) * 0.3;
      position.setXYZ(index, x * bump, y * bump, z * bump);
    }
    canopyGeometry.computeVertexNormals();
  }
  const canopyMaterial = new THREE.MeshStandardMaterial({
    color: "#ffffff",
    roughness: 0.94,
    flatShading: true,
  });
  const canopies = new THREE.InstancedMesh(canopyGeometry, canopyMaterial, spots.length);
  canopies.castShadow = true;
  canopies.receiveShadow = true;
  const highlightMaterial = new THREE.MeshStandardMaterial({
    color: "#ffffff",
    roughness: 0.9,
    flatShading: true,
  });
  const highlights = type === "conifer"
    ? null
    : new THREE.InstancedMesh(canopyGeometry, highlightMaterial, spots.length);
  if (highlights) {
    highlights.castShadow = true;
    highlights.receiveShadow = true;
  }

  const foliage = type === "conifer"
    ? ["#315848", "#3e6651", "#48735a"]
    : ["#5c8550", "#6e9758", "#7ca55f", "#4d794c"];
  const highlightFoliage = ["#86ad68", "#93b975", "#a3c783"];
  spots.forEach((spot, index) => {
    const height = terrainHeightAt(spot.x, spot.z);
    const trunkHeight = spot.size * 0.52;
    dummy.position.set(spot.x, height + trunkHeight / 2, spot.z);
    dummy.rotation.set(0, spot.rotation, 0);
    dummy.scale.set(spot.size * 0.72, trunkHeight, spot.size * 0.72);
    dummy.updateMatrix();
    trunks.setMatrixAt(index, dummy.matrix);

    const canopyHeight = type === "conifer" ? spot.size * 0.72 : spot.size * 0.6;
    dummy.position.set(spot.x, height + trunkHeight + canopyHeight * 0.36, spot.z);
    dummy.rotation.set(0, spot.rotation, 0);
    dummy.scale.set(
      spot.size * (type === "conifer" ? 0.40 : 0.44),
      spot.size * (type === "conifer" ? 0.55 : 0.39),
      spot.size * (type === "conifer" ? 0.40 : 0.44),
    );
    dummy.updateMatrix();
    canopies.setMatrixAt(index, dummy.matrix);
    canopies.setColorAt(index, new THREE.Color(foliage[Math.floor(hash2(spot.x, spot.z) * foliage.length)]));

    if (highlights) {
      dummy.position.set(
        spot.x + Math.cos(spot.rotation) * spot.size * 0.08,
        height + trunkHeight + canopyHeight * 0.48,
        spot.z + Math.sin(spot.rotation) * spot.size * 0.08,
      );
      dummy.scale.setScalar(spot.size * 0.28);
      dummy.updateMatrix();
      highlights.setMatrixAt(index, dummy.matrix);
      highlights.setColorAt(index, new THREE.Color(
        highlightFoliage[Math.floor(hash2(spot.z, spot.x) * highlightFoliage.length)],
      ));
    }
  });
  trunks.instanceMatrix.needsUpdate = true;
  canopies.instanceMatrix.needsUpdate = true;
  if (canopies.instanceColor) canopies.instanceColor.needsUpdate = true;
  if (highlights) {
    highlights.instanceMatrix.needsUpdate = true;
    if (highlights.instanceColor) highlights.instanceColor.needsUpdate = true;
  }
  parent.add(trunks, canopies);
  if (highlights) parent.add(highlights);
}

function addFlowerBeds(parent, materials, blockers = []) {
  const dummy = new THREE.Object3D();
  const flowerGeometry = new THREE.IcosahedronGeometry(0.028, 0);
  const flowerMaterial = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.8 });
  const flowers = [];
  const colors = ["#e88b79", "#f3c55b", "#d97ab0", "#f7e8ce", "#8fb5dc"];
  const beds = [
    [-2.4, 0.55, 0.45, 0.24],
    [-2.9, 1.45, 0.38, 0.22],
    [0.85, 1.35, 0.34, 0.2],
    [2.05, 1.65, 0.3, 0.2],
    [-1.55, 2.05, 0.32, 0.2],
  ];
  for (const [x, z, radius, height] of beds) {
    for (let index = 0; index < 14; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const distance = Math.sqrt(Math.random()) * radius;
      const fx = x + Math.cos(angle) * distance;
      const fz = z + Math.sin(angle) * distance;
      if (blockers.some(blocker => Math.hypot(fx - blocker.x, fz - blocker.z) < blocker.r)) continue;
      flowers.push({ x: fx, z: fz, y: terrainHeightAt(fx, fz) + height * 0.5 + 0.05, color: colors[index % colors.length] });
    }
  }
  const mesh = new THREE.InstancedMesh(flowerGeometry, flowerMaterial, flowers.length);
  flowers.forEach((flower, index) => {
    dummy.position.set(flower.x, flower.y, flower.z);
    dummy.scale.setScalar(0.7 + Math.random() * 0.9);
    dummy.updateMatrix();
    mesh.setMatrixAt(index, dummy.matrix);
    mesh.setColorAt(index, new THREE.Color(flower.color));
  });
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  parent.add(mesh);
  return mesh;
}

function addRocks(parent, materials, blockers = []) {
  const random = seededRandom(7341);
  const geometry = new THREE.DodecahedronGeometry(1, 0);
  const material = materials.standard("#76736b", { roughness: 1, flatShading: true });
  const spots = [];
  for (let attempt = 0; attempt < 160 && spots.length < 23; attempt += 1) {
    const angle = random() * Math.PI * 2;
    const radius = 0.9 + random() * 0.09;
    const x = Math.cos(angle) * 5.7 * radius;
    const z = Math.sin(angle) * 4.75 * radius;
    const height = terrainHeightAt(x, z);
    if (height < WATER_LEVEL - 0.08 || height > WATER_LEVEL + 0.18) continue;
    if (blockers.some(blocker => Math.hypot(x - blocker.x, z - blocker.z) < blocker.r)) continue;
    spots.push({ x, z, height, size: 0.07 + random() * 0.13, rotation: random() * Math.PI });
  }
  const mesh = new THREE.InstancedMesh(geometry, material, spots.length);
  const dummy = new THREE.Object3D();
  spots.forEach((spot, index) => {
    dummy.position.set(spot.x, spot.height + spot.size * 0.34, spot.z);
    dummy.rotation.set(spot.rotation, spot.rotation * 2, spot.rotation * 0.6);
    dummy.scale.set(spot.size, spot.size * 0.65, spot.size);
    dummy.updateMatrix();
    mesh.setMatrixAt(index, dummy.matrix);
  });
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.instanceMatrix.needsUpdate = true;
  parent.add(mesh);
  return mesh;
}

function addBushes(parent, materials, blockers = []) {
  const random = seededRandom(1987);
  const geometry = new THREE.IcosahedronGeometry(1, 0);
  const material = materials.standard("#5e8253", { roughness: 1, flatShading: true });
  const spots = [];
  for (let attempt = 0; attempt < 220 && spots.length < 28; attempt += 1) {
    const x = (random() * 2 - 1) * 4.9;
    const z = (random() * 2 - 1) * 4.1;
    const height = terrainHeightAt(x, z);
    if (height < WATER_LEVEL + 0.17 || Math.hypot(x, z) < 1.35) continue;
    if (blockers.some(blocker => Math.hypot(x - blocker.x, z - blocker.z) < blocker.r)) continue;
    spots.push({ x, z, height, size: 0.06 + random() * 0.1, rotation: random() * Math.PI });
  }
  const mesh = new THREE.InstancedMesh(geometry, material, spots.length);
  const dummy = new THREE.Object3D();
  spots.forEach((spot, index) => {
    dummy.position.set(spot.x, spot.height + spot.size * 0.5, spot.z);
    dummy.rotation.set(spot.rotation, spot.rotation * 2, 0);
    dummy.scale.set(spot.size, spot.size * 0.6, spot.size);
    dummy.updateMatrix();
    mesh.setMatrixAt(index, dummy.matrix);
  });
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  mesh.instanceMatrix.needsUpdate = true;
  parent.add(mesh);
  return mesh;
}

function makePlinth(materials) {
  const group = new THREE.Group();
  const wood = materials.wood;
  const brass = materials.standard("#b38b49", { metalness: 0.62, roughness: 0.42 });
  box(group, [12.18, 0.48, 10.18], [0, -0.35, 0], wood);
  box(group, [12.32, 0.08, 10.32], [0, -0.09, 0], wood);
  box(group, [12.2, 0.035, 10.2], [0, -0.65, 0], brass);
  const frameSides = [
    [[12.18, 0.16, 0.18], [0, 0, 5.05]], [[12.18, 0.16, 0.18], [0, 0, -5.05]],
    [[0.18, 0.16, 10.1], [6.05, 0, 0]], [[0.18, 0.16, 10.1], [-6.05, 0, 0]],
  ];
  for (const [size, position] of frameSides) box(group, size, position, wood);
  for (const x of [-5.85, 5.85]) {
    for (const z of [-4.85, 4.85]) {
      cylinder(group, 0.08, 0.1, 0.12, 12, [x, -0.7, z], brass);
    }
  }
  box(group, [2.58, 0.6, 0.03], [0, -0.37, 5.13], brass);
  const plaque = new THREE.Mesh(new THREE.PlaneGeometry(2.44, 0.48), materials.plaque);
  plaque.position.set(0, -0.37, 5.152);
  group.add(plaque);
  return group;
}

function addFountain(parent, materials) {
  const x = -1.42;
  const z = 1.04;
  const ground = terrainHeightAt(x, z);
  const group = new THREE.Group();
  group.position.set(x, ground, z);
  parent.add(group);
  const stone = materials.standard("#b9ad99", { roughness: 0.92 });
  cylinder(group, 0.27, 0.3, 0.1, 24, [0, 0.05, 0], stone);
  cylinder(group, 0.22, 0.22, 0.03, 24, [0, 0.11, 0], materials.waterStatic);
  cylinder(group, 0.055, 0.07, 0.3, 10, [0, 0.22, 0], stone);
  cylinder(group, 0.12, 0.09, 0.04, 16, [0, 0.36, 0], stone);
  return group;
}

export function createDioramaBoard({
  environment = {},
  requestShadow = () => {},
  setExposure = () => {},
} = {}) {
  const group = new THREE.Group();
  group.name = "tinytown-diorama";
  group.position.y = GROUP_LIFT;

  const materials = createPalette();
  materials.groundTexture = makeGroundTexture();
  materials.detailTexture = makeDetailTexture();
  materials.cobbleTexture = makeCobbleTexture();
  materials.woodTexture = makeWoodTexture();
  materials.plaqueTexture = makePlaqueTexture();
  materials.glowTexture = makeGlowTexture();
  materials.starTexture = makeStarTexture();
  materials.waterMaterial = makeWaterMaterial();

  materials.wood = materials.standard("#805b3d", { map: materials.woodTexture, roughness: 0.84 });
  materials.cobble = materials.standard("#c3b79f", { map: materials.cobbleTexture, roughness: 0.94 });
  materials.waterStatic = materials.standard("#4b9297", { roughness: 0.2, metalness: 0.1 });
  materials.lampBulb = new THREE.MeshStandardMaterial({
    color: "#ffe4a8", emissive: "#ffbd60", emissiveIntensity: 0.1, roughness: 0.4,
  });
  materials.lanternGlass = new THREE.MeshStandardMaterial({
    color: "#ffe0a2", emissive: "#ffc05e", emissiveIntensity: 0.25,
    transparent: true, opacity: 0.82, roughness: 0.3,
  });
  materials.glowMaterial = new THREE.SpriteMaterial({
    map: materials.glowTexture, color: "#ffe5ae", transparent: true, opacity: 0,
    depthWrite: false, blending: THREE.AdditiveBlending,
  });
  materials.plaque = new THREE.MeshStandardMaterial({
    map: materials.plaqueTexture,
    emissive: "#6b4c20",
    emissiveIntensity: 0.28,
    roughness: 0.42,
    metalness: 0.35,
  });
  group.add(makePlinth(materials));
  const terrain = buildTerrain(materials);
  group.add(terrain);

  const water = new THREE.Mesh(
    (() => {
      const geometry = new THREE.PlaneGeometry(HALF_WIDTH * 2.02, HALF_DEPTH * 2.02, 96, 80);
      geometry.rotateX(-Math.PI / 2);
      return geometry;
    })(),
    materials.waterMaterial,
  );
  water.position.y = WATER_LEVEL;
  water.renderOrder = 2;
  group.add(water);
  const lightReflectionMaterial = new THREE.MeshBasicMaterial({
    map: materials.glowTexture,
    color: "#ffd88f",
    transparent: true,
    opacity: 0,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
  const lightReflection = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 2.8), lightReflectionMaterial);
  lightReflection.rotation.x = -Math.PI / 2;
  lightReflection.position.set(3.9, WATER_LEVEL + 0.012, -0.3);
  lightReflection.renderOrder = 3;
  group.add(lightReflection);
  addShoreline(group);

  const road = new THREE.Group();
  group.add(road);
  const mainRoad = [
    [-4.65, 1.2], [-3.55, 0.92], [-2.45, 0.48], [-1.35, 0.2],
    [-0.24, 0.3], [0.88, 0.5], [1.95, 0.58], [2.95, 0.9], [3.52, 1.38],
  ];
  const northRoad = [[-0.7, 0.31], [-0.72, -0.48], [-1.18, -1.3], [-2.0, -2.08], [-2.98, -2.32]];
  const southRoad = [[-0.04, 0.31], [0.3, 1.18], [0.82, 2.16], [1.42, 2.86]];
  road.add(makeRibbon(mainRoad, 0.39, materials.standard("#9f927c", { roughness: 1 }), 0.012));
  road.add(makeRibbon(mainRoad, 0.31, materials.cobble, 0.02));
  road.add(makeRibbon(northRoad, 0.29, materials.standard("#9f927c", { roughness: 1 }), 0.012));
  road.add(makeRibbon(northRoad, 0.23, materials.cobble, 0.02));
  road.add(makeRibbon(southRoad, 0.29, materials.standard("#9f927c", { roughness: 1 }), 0.012));
  road.add(makeRibbon(southRoad, 0.23, materials.cobble, 0.02));

  const plazaX = -1.42;
  const plazaZ = 1.04;
  const plazaGround = terrainHeightAt(plazaX, plazaZ);
  cylinder(group, 0.82, 0.88, 0.055, 36, [plazaX, plazaGround + 0.02, plazaZ], materials.cobble);
  const plazaRing = new THREE.Mesh(
    new THREE.TorusGeometry(0.84, 0.016, 8, 48),
    materials.standard("#a38b63", { metalness: 0.55, roughness: 0.46 }),
  );
  plazaRing.rotation.x = Math.PI / 2;
  plazaRing.position.set(plazaX, plazaGround + 0.058, plazaZ);
  group.add(plazaRing);

  const houses = Array.isArray(environment?.diorama?.houses) ? environment.diorama.houses : [];
  const houseLayer = createHouseLayer(group, materials, houses);
  addFountain(group, materials);

  const houseBlockers = houses.map(house => {
    const lot = house.lot || {};
    return {
      x: Number(lot.x) || 0,
      z: Number(lot.z) || 0,
      r: Math.max(0.58, (Number(lot.scale) || 1) * 0.82),
    };
  });
  const lampSpots = [
    [-2.95, 0.78], [-1.95, 0.45], [-0.72, 1.05], [0.45, 1.35],
    [1.85, 0.85], [2.72, 1.62], [-0.95, -0.55], [0.5, 1.95], [1.55, 2.0],
    [-2.1, 2.25],
  ];
  const lampLights = [];
  for (const [x, z] of lampSpots) {
    if (houses.some(house => {
      const lot = house.lot || {};
      const radius = Math.max(0.6, (Number(lot.scale) || 1) * 0.72);
      return Math.hypot(x - (Number(lot.x) || 0), z - (Number(lot.z) || 0)) < radius;
    })) continue;
    addLamp(group, x, z, materials, lampLights);
  }
  addPier(group, materials);

  const blockers = [
    ...houseBlockers,
    { x: plazaX, z: plazaZ, r: 0.92 },
    { x: 3.9, z: -1.65, r: 0.55 },
    { x: 3.2, z: 0.7, r: 0.4 },
  ];
  const treeRandom = seededRandom(44121);
  const decidTrees = [];
  const coniferTrees = [];
  const zones = [
    { count: 22, x: -3.25, z: -1.9, rx: 1.7, rz: 1.2 },
    { count: 14, x: -0.2, z: 2.95, rx: 1.75, rz: 0.55 },
    { count: 8, x: 2.85, z: 2.35, rx: 0.7, rz: 0.45 },
    { count: 12, x: -2.85, z: 1.85, rx: 1.25, rz: 0.9 },
    { count: 6, x: 3.65, z: 0.05, rx: 0.45, rz: 0.9 },
    { count: 8, x: 0.2, z: -2.4, rx: 1.5, rz: 0.6 },
  ];
  for (const zone of zones) {
    let added = 0;
    for (let attempt = 0; attempt < 180 && added < zone.count; attempt += 1) {
      const x = zone.x + (treeRandom() * 2 - 1) * zone.rx;
      const z = zone.z + (treeRandom() * 2 - 1) * zone.rz;
      if (terrainHeightAt(x, z) < WATER_LEVEL + 0.15) continue;
      if (blockers.some(blocker => Math.hypot(x - blocker.x, z - blocker.z) < blocker.r)) continue;
      if (decidTrees.some(tree => Math.hypot(x - tree.x, z - tree.z) < 0.22)) continue;
      decidTrees.push({
        x, z, size: 0.6 + treeRandom() * 0.55, rotation: treeRandom() * Math.PI * 2,
      });
      added += 1;
    }
  }
  for (let attempt = 0; attempt < 200 && coniferTrees.length < 28; attempt += 1) {
    const x = -3.65 + (treeRandom() * 2 - 1) * 1.3;
    const z = -1.55 + (treeRandom() * 2 - 1) * 1.2;
    if (terrainHeightAt(x, z) < WATER_LEVEL + 0.2) continue;
    if (blockers.some(blocker => Math.hypot(x - blocker.x, z - blocker.z) < blocker.r)) continue;
    coniferTrees.push({ x, z, size: 0.65 + treeRandom() * 0.5, rotation: treeRandom() * Math.PI * 2 });
  }
  addTrees(group, decidTrees, "deciduous", materials);
  addTrees(group, coniferTrees, "conifer", materials);
  addFlowerBeds(group, materials, blockers);
  addRocks(group, materials, blockers);
  addBushes(group, materials, blockers);

  const floaters = [
    addBoat(group, 3.55, -0.15, "#f3e0b0", 0.1, materials),
    addBoat(group, 4.2, 0.1, "#d98b72", 1.7, materials),
    addBoat(group, 3.5, 2.5, "#8ebac0", 3.2, materials),
  ];

  const fireflyCount = 38;
  const fireflyPositions = new Float32Array(fireflyCount * 3);
  for (let index = 0; index < fireflyCount; index += 1) {
    const x = (treeRandom() * 2 - 1) * 3.8;
    const z = (treeRandom() * 2 - 1) * 3.2;
    fireflyPositions[index * 3] = x;
    fireflyPositions[index * 3 + 1] = terrainHeightAt(x, z) + 0.2 + treeRandom() * 0.75;
    fireflyPositions[index * 3 + 2] = z;
  }
  const fireflyGeometry = new THREE.BufferGeometry();
  fireflyGeometry.setAttribute("position", new THREE.BufferAttribute(fireflyPositions, 3));
  const fireflyMaterial = new THREE.PointsMaterial({
    color: "#ffe6a3", size: 0.035, transparent: true, opacity: 0,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true,
  });
  const fireflies = new THREE.Points(fireflyGeometry, fireflyMaterial);
  group.add(fireflies);

  const cycle = normalizeDayCycle(environment);
  const startedAt = performance.now();
  let roomDark = false;
  let disposed = false;
  let lastShadowAt = -10;
  let lastPhase = -1;

  function applyLighting(day) {
    setExposure(day.exposure);
    materials.waterMaterial.uniforms.uLight.value = day.water;
    materials.waterMaterial.uniforms.uNight.value = day.night;
    materials.lampBulb.emissiveIntensity = 0.15 + day.night * 4.03;
    materials.lanternGlass.emissiveIntensity = 0.25 + day.night * 3.0;
    materials.glowMaterial.opacity = day.night * 0.9;
    lightReflectionMaterial.opacity = day.night * 0.62;
    const flicker = 0.94 + Math.sin(performance.now() * 0.004) * 0.06 * day.night;
    for (const light of lampLights) {
      light.color.set(LAMP_GLOW);
      light.intensity = day.night * 6.05 * flicker;
    }
    fireflyMaterial.opacity = day.night * 0.9;
  }

  function currentDaylight() {
    return daylightForPhase(cyclePhaseAt(cycle, (performance.now() - startedAt) / 1000));
  }

  function update(delta, { reducedMotion = false } = {}) {
    if (disposed) return;
    const elapsed = (performance.now() - startedAt) / 1000;
    const phase = cyclePhaseAt(cycle, elapsed);
    const day = daylightForPhase(phase);
    if (roomDark) {
      day.night = 1;
      day.ambient = Math.min(day.ambient, 0.25);
      day.sun = 0;
      day.water = Math.min(day.water, 0.16);
    }
    applyLighting(day);
    materials.waterMaterial.uniforms.uTime.value = reducedMotion ? elapsed * 0.28 : elapsed;
    for (const floater of floaters) {
      const bob = Math.sin(elapsed * 1.25 + floater.phase) * (reducedMotion ? 0.006 : 0.018);
      floater.group.position.y = floater.baseY + bob;
      floater.group.rotation.z = Math.sin(elapsed * 1.1 + floater.phase) * (reducedMotion ? 0.006 : 0.024);
    }
    houseLayer.update(elapsed, { reducedMotion, requestShadow });
    fireflies.rotation.y = elapsed * 0.018;
    if (elapsed - lastShadowAt > 1.2) {
      lastShadowAt = elapsed;
      requestShadow();
    }
    lastPhase = phase;
    return { phase, daylight: day };
  }

  function setSceneLights(lights) {
    // The diorama owns the shared scene lights while it is visible.
    const phase = cyclePhaseAt(cycle, (performance.now() - startedAt) / 1000);
    const day = daylightForPhase(phase);
    const solar = (phase - 0.25) * Math.PI * 2;
    const lampAmbient = Math.min(lampLights.length * 0.012, 0.16) * day.night;
    lights.hemisphere.color.copy(day.sky);
    lights.hemisphere.groundColor.copy(day.ground);
    lights.hemisphere.intensity = roomDark
      ? Math.min(day.ambient, 0.24)
      : Math.min(day.ambient + lampAmbient, 2.0);
    lights.sunlight.color.copy(day.sunColor);
    lights.sunlight.intensity = roomDark ? 0 : Math.max(day.sun, day.night * 0.48);
    lights.sunlight.position.set(
      Math.cos(solar) * 8.5,
      2.2 + Math.max(0, Math.sin(solar)) * 8.4,
      Math.sin(solar * 0.82) * 3.4,
    );
    lights.fill.color.copy(day.fillColor);
    lights.fill.intensity = roomDark ? Math.min(day.fill, 0.05) : day.fill;
  }

  return {
    group,
    pickables: houseLayer.pickables,
    update,
    setSceneLights,
    setRoomDark(value) {
      roomDark = Boolean(value);
    },
    get daylight() {
      return currentDaylight();
    },
    get phase() {
      return lastPhase;
    },
    dispose() {
      disposed = true;
      houseLayer.dispose();
      disposeBoardTree(group);
    },
  };
}
