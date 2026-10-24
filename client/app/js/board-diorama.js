// Procedural TinyTown tabletop diorama.
//
// The town board is not a baked prop: an irregular height-field island is
// generated at runtime, then dressed with reusable meshes for roads, houses,
// trees, lamps, a harbour, and a clock tower.

import * as THREE from "three";

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

export const DIORAMA_BOARD_TYPE = "diorama";
const GROUP_LIFT = 0.045;
const WARM_WINDOW = "#ffb45e";
const COOL_WINDOW = "#b6dcff";
const LAMP_GLOW = "#ffd58a";

function makeCanvasTexture(width, height, draw, { repeatX = 1, repeatY = 1 } = {}) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  draw(context, width, height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(repeatX, repeatY);
  texture.anisotropy = 4;
  return texture;
}

function makeDetailTexture() {
  return makeCanvasTexture(256, 256, (context, width, height) => {
    const image = context.createImageData(width, height);
    for (let index = 0; index < image.data.length; index += 4) {
      const value = 112 + Math.floor(Math.random() * 46);
      image.data[index] = value;
      image.data[index + 1] = value;
      image.data[index + 2] = value;
      image.data[index + 3] = 255;
    }
    context.putImageData(image, 0, 0);
  }, { repeatX: 18, repeatY: 15 });
}

function makeCobbleTexture() {
  return makeCanvasTexture(256, 256, (context, width, height) => {
    context.fillStyle = "#b6aa93";
    context.fillRect(0, 0, width, height);
    for (let row = 0; row < 9; row += 1) {
      for (let column = 0; column < 9; column += 1) {
        const x = column * 30 + (row % 2 ? 14 : 0) + Math.random() * 4;
        const y = row * 30 + Math.random() * 4;
        context.fillStyle = `hsl(${32 + Math.random() * 12} 14% ${62 + Math.random() * 12}%)`;
        context.beginPath();
        context.ellipse(x, y, 13 + Math.random() * 2, 9 + Math.random() * 2, 0.1, 0, Math.PI * 2);
        context.fill();
      }
    }
  }, { repeatX: 3, repeatY: 2 });
}

function makeWoodTexture() {
  return makeCanvasTexture(256, 128, (context, width, height) => {
    context.fillStyle = "#6a482e";
    context.fillRect(0, 0, width, height);
    for (let line = 0; line < 34; line += 1) {
      const y = Math.random() * height;
      context.strokeStyle = `rgba(${38 + Math.random() * 26},${24 + Math.random() * 16},${14 + Math.random() * 10},0.35)`;
      context.lineWidth = 0.5 + Math.random() * 1.5;
      context.beginPath();
      context.moveTo(0, y);
      for (let x = 0; x <= width; x += 16) {
        context.lineTo(x, y + Math.sin(x * 0.06 + line) * 2.4);
      }
      context.stroke();
    }
  }, { repeatX: 2, repeatY: 1 });
}

function makePlaqueTexture() {
  return makeCanvasTexture(512, 128, (context, width, height) => {
    const gradient = context.createLinearGradient(0, 0, 0, height);
    gradient.addColorStop(0, "#d8b86a");
    gradient.addColorStop(0.48, "#a97b33");
    gradient.addColorStop(1, "#745022");
    context.fillStyle = gradient;
    context.fillRect(0, 0, width, height);
    context.strokeStyle = "rgba(65,39,12,0.9)";
    context.lineWidth = 8;
    context.strokeRect(6, 6, width - 12, height - 12);
    context.fillStyle = "#2f2114";
    context.textAlign = "center";
    context.font = "700 49px Georgia, serif";
    context.fillText("TINYTOWN", width / 2, 68);
    context.font = "600 17px Georgia, serif";
    context.letterSpacing = "4px";
    context.fillText("EST. 2026 · POPULATION: MANY PEEPS", width / 2, 101);
  });
}

function makeClockTexture() {
  return makeCanvasTexture(256, 256, (context, width, height) => {
    context.clearRect(0, 0, width, height);
    context.fillStyle = "#f5e6c4";
    context.beginPath();
    context.arc(width / 2, height / 2, 116, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = "#7f5a2c";
    context.lineWidth = 12;
    context.stroke();
    context.fillStyle = "#3b2a1c";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.font = "700 28px Georgia, serif";
    for (let mark = 0; mark < 12; mark += 1) {
      const angle = mark / 12 * Math.PI * 2;
      context.save();
      context.translate(width / 2 + Math.sin(angle) * 82, height / 2 - Math.cos(angle) * 82);
      context.rotate(angle);
      context.fillText(String(mark === 0 ? 12 : mark), 0, 0);
      context.restore();
    }
    context.fillStyle = "#c98b3f";
    context.beginPath();
    context.arc(width / 2, height / 2, 8, 0, Math.PI * 2);
    context.fill();
  });
}

function makeGlowTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  const gradient = context.createRadialGradient(64, 64, 0, 64, 64, 62);
  gradient.addColorStop(0, "rgba(255,255,255,1)");
  gradient.addColorStop(0.22, "rgba(255,239,190,0.78)");
  gradient.addColorStop(1, "rgba(255,190,94,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 128, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
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

function addWindow(parent, {
  x = 0, y = 0, z = 0, rotation = 0, width = 0.13, height = 0.16, material,
  frameMaterial,
}) {
  const holder = new THREE.Group();
  holder.position.set(x, y, z);
  holder.rotation.y = rotation;
  parent.add(holder);
  box(holder, [width + 0.026, height + 0.026, 0.022], [0, 0, 0], frameMaterial);
  box(holder, [width, height, 0.012], [0, 0, 0.014], material);
  box(holder, [0.012, height, 0.016], [0, 0, 0.022], frameMaterial);
  box(holder, [width, 0.012, 0.016], [0, 0, 0.022], frameMaterial);
  return holder;
}

function addCottage(parent, options, materials, windows) {
  const {
    x, z, rotation = 0, width = 0.55, depth = 0.46, height = 0.52,
    wall = "#e7cf9c", roof = "#a95f4a", scale = 1,
  } = options;
  const group = new THREE.Group();
  const ground = terrainHeightAt(x, z);
  group.position.set(x, ground, z);
  group.rotation.y = rotation;
  group.scale.setScalar(scale);
  parent.add(group);

  const foundation = materials.standard("#887567", { roughness: 0.95 });
  const wallMaterial = materials.standard(wall);
  const roofMaterial = materials.standard(roof, { roughness: 0.74 });
  const trim = materials.standard("#f4e5c8");
  const doorMaterial = materials.standard("#5e3d2d", { roughness: 0.8 });
  const frame = materials.standard("#4a3427", { roughness: 0.9 });

  box(group, [width + 0.05, 0.6, depth + 0.05], [0, -0.28, 0], foundation);
  box(group, [width, height, depth], [0, height / 2, 0], wallMaterial);
  const roofHeight = 0.24 + height * 0.22;
  const roofMesh = new THREE.Mesh(gableGeometry(width + 0.11, depth + 0.11, roofHeight), roofMaterial);
  roofMesh.position.y = height;
  roofMesh.castShadow = true;
  roofMesh.receiveShadow = true;
  group.add(roofMesh);

  box(group, [0.11, 0.16, 0.025], [0, 0.085, depth / 2 + 0.015], doorMaterial);
  box(group, [0.16, 0.022, 0.06], [0, 0.18, depth / 2 + 0.045], trim);

  const lit = hash2(x * 9, z * 7) > 0.35;
  const windowMaterial = lit ? windows.warm : windows.cool;
  addWindow(group, {
    x: -width * 0.27, y: height * 0.62, z: depth / 2 + 0.012,
    width: width * 0.22, height: height * 0.26, material: windowMaterial, frameMaterial: frame,
  });
  addWindow(group, {
    x: width * 0.27, y: height * 0.62, z: depth / 2 + 0.012,
    width: width * 0.22, height: height * 0.26, material: windowMaterial, frameMaterial: frame,
  });
  addWindow(group, {
    x: width / 2 + 0.012, y: height * 0.62, z: 0, rotation: Math.PI / 2,
    width: depth * 0.24, height: height * 0.24, material: windowMaterial, frameMaterial: frame,
  });
  if (lit) {
    const halo = new THREE.Sprite(materials.glowMaterial);
    halo.position.set(0, height * 0.62, depth / 2 + 0.08);
    halo.scale.set(0.38, 0.38, 1);
    group.add(halo);
  }

  box(group, [0.075, 0.22, 0.075], [width * 0.27, height + roofHeight * 0.5, -depth * 0.22], foundation);
  box(group, [0.07, 0.018, 0.06], [width * 0.27, height + roofHeight * 0.5 + 0.12, -depth * 0.22], roofMaterial);
  box(group, [0.2, 0.018, 0.26], [0, 0.022, depth / 2 + 0.11], trim);

  return group;
}

function addTownhouse(parent, options, materials, windows) {
  const {
    x, z, rotation = 0, width = 0.62, depth = 0.52, height = 1.1,
    wall = "#c56f55", roof = "#7f4a3b",
  } = options;
  const group = new THREE.Group();
  const ground = terrainHeightAt(x, z);
  group.position.set(x, ground, z);
  group.rotation.y = rotation;
  parent.add(group);

  const foundation = materials.standard("#7f6a5b", { roughness: 0.95 });
  const wallMaterial = materials.standard(wall);
  const roofMaterial = materials.standard(roof);
  const trim = materials.standard("#efe0c1");
  const awningMaterial = materials.standard("#4c8379");
  const frame = materials.standard("#3d2d24", { roughness: 0.9 });
  const doorMaterial = materials.standard("#4e332b");

  box(group, [width + 0.06, 0.72, depth + 0.06], [0, -0.33, 0], foundation);
  box(group, [width, height, depth], [0, height / 2, 0], wallMaterial);
  box(group, [width + 0.08, 0.08, depth + 0.08], [0, height + 0.02, 0], trim);
  box(group, [width + 0.02, 0.1, depth + 0.02], [0, height + 0.09, 0], roofMaterial);
  box(group, [width * 0.62, 0.08, 0.12], [0, 0.1, depth / 2 + 0.04], awningMaterial, [-0.16, 0, 0]);
  box(group, [0.14, 0.2, 0.026], [0, 0.1, depth / 2 + 0.016], doorMaterial);

  const lit = hash2(x * 5, z * 11) > 0.3;
  const windowMaterial = lit ? windows.warm : windows.cool;
  const rows = height > 1.2 ? 3 : 2;
  for (let row = 0; row < rows; row += 1) {
    const y = 0.34 + row * (height * 0.25);
    for (const side of [-1, 1]) {
      addWindow(group, {
        x: side * width * 0.24, y, z: depth / 2 + 0.014,
        width: width * 0.18, height: height * 0.12, material: windowMaterial, frameMaterial: frame,
      });
      addWindow(group, {
        x: side * (width / 2 + 0.014), y, z: 0, rotation: Math.PI / 2,
        width: depth * 0.19, height: height * 0.12, material: windowMaterial, frameMaterial: frame,
      });
    }
  }
  if (lit) {
    const halo = new THREE.Sprite(materials.glowMaterial);
    halo.position.set(0, height * 0.55, depth / 2 + 0.08);
    halo.scale.set(0.5, 0.5, 1);
    group.add(halo);
  }
  box(group, [width * 0.42, 0.035, 0.05], [0, height + 0.16, 0], trim);
  box(group, [0.1, 0.3, 0.1], [-width * 0.3, height + 0.25, -depth * 0.2], foundation);
  return group;
}

function addHarborHouse(parent, options, materials, windows) {
  const group = addCottage(parent, {
    ...options,
    width: options.width || 0.48,
    depth: options.depth || 0.42,
    height: options.height || 0.44,
    roof: options.roof || "#4d7d86",
    wall: options.wall || "#e4bd7c",
  }, materials, windows);
  const posts = materials.standard("#5c4635");
  for (const sx of [-1, 1]) {
    for (const sz of [-1, 1]) {
      box(group, [0.045, 0.26, 0.045], [sx * 0.17, -0.2, sz * 0.15], posts);
    }
  }
  return group;
}

function addClockTower(parent, materials, windows) {
  const x = -0.1;
  const z = -0.2;
  const ground = terrainHeightAt(x, z);
  const group = new THREE.Group();
  group.position.set(x, ground, z);
  parent.add(group);

  const stone = materials.standard("#b8a68f", { roughness: 0.92 });
  const trim = materials.standard("#e5d6b9");
  const roof = materials.standard("#55776f");
  const faceMaterial = materials.clock;
  const handsMaterial = materials.standard("#31251c", { roughness: 0.7 });

  box(group, [0.52, 0.12, 0.52], [0, 0.04, 0], stone);
  box(group, [0.34, 1.2, 0.34], [0, 0.66, 0], stone);
  box(group, [0.43, 0.09, 0.43], [0, 1.28, 0], trim);
  box(group, [0.4, 0.06, 0.4], [0, 0.37, 0], trim);
  box(group, [0.4, 0.06, 0.4], [0, 0.96, 0], trim);

  const faceGeometry = new THREE.PlaneGeometry(0.23, 0.23);
  const faces = [
    [0, 1.05, 0.176, 0],
    [0, 1.05, -0.176, Math.PI],
    [0.176, 1.05, 0, Math.PI / 2],
    [-0.176, 1.05, 0, -Math.PI / 2],
  ];
  const hands = [];
  for (const [fx, fy, fz, rotation] of faces) {
    const face = new THREE.Mesh(faceGeometry, faceMaterial);
    face.position.set(fx, fy, fz);
    face.rotation.y = rotation;
    group.add(face);
    const handGroup = new THREE.Group();
    handGroup.position.set(fx, fy, fz);
    handGroup.rotation.y = rotation;
    group.add(handGroup);
    box(handGroup, [0.012, 0.07, 0.01], [0, 0.025, 0.012], handsMaterial);
    box(handGroup, [0.009, 0.095, 0.01], [-0.012, 0.04, 0.02], handsMaterial, [0, 0, -0.6]);
    hands.push(handGroup);
  }

  const roofMesh = new THREE.Mesh(new THREE.ConeGeometry(0.3, 0.28, 4), roof);
  roofMesh.position.y = 1.45;
  roofMesh.rotation.y = Math.PI / 4;
  roofMesh.castShadow = true;
  group.add(roofMesh);
  box(group, [0.025, 0.2, 0.025], [0, 1.65, 0], handsMaterial);
  cylinder(group, 0.022, 0.022, 0.13, 8, [0, 1.76, 0], materials.lampBulb);

  return { group, hands, faceMaterial };
}

function addLighthouse(parent, materials) {
  const x = 3.9;
  const z = -1.65;
  const ground = Math.max(WATER_LEVEL + 0.02, terrainHeightAt(x, z));
  const group = new THREE.Group();
  group.position.set(x, ground, z);
  parent.add(group);

  const rock = materials.standard("#6e6960", { roughness: 1 });
  const white = materials.standard("#f0ead8");
  const red = materials.standard("#b64e42");
  for (const [dx, dz, scale] of [[0, 0, 0.34], [0.3, 0.08, 0.2], [-0.24, 0.15, 0.17], [0.12, -0.22, 0.16]]) {
    const mesh = new THREE.Mesh(new THREE.DodecahedronGeometry(scale, 0), rock);
    mesh.position.set(dx, -0.06 + scale * 0.5, dz);
    mesh.rotation.set(dx, dz, 0.4);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    group.add(mesh);
  }

  const base = 0.13;
  for (let index = 0; index < 5; index += 1) {
    const radiusTop = 0.13 - index * 0.012;
    const radiusBottom = 0.145 - index * 0.012;
    cylinder(group, radiusTop, radiusBottom, 0.2, 18, [0, base + index * 0.2, 0], index % 2 ? red : white);
  }
  cylinder(group, 0.17, 0.15, 0.07, 18, [0, base + 1.02, 0], red);
  cylinder(group, 0.145, 0.145, 0.15, 12, [0, base + 1.1, 0], materials.lanternGlass);
  cylinder(group, 0.17, 0.16, 0.06, 12, [0, base + 1.2, 0], red);
  const cap = new THREE.Mesh(new THREE.ConeGeometry(0.18, 0.16, 16), red);
  cap.position.y = base + 1.31;
  cap.castShadow = true;
  group.add(cap);

  const lantern = new THREE.PointLight("#ffd38a", 0, 2.8, 2);
  lantern.position.set(0, base + 1.1, 0);
  group.add(lantern);
  const glow = new THREE.Sprite(materials.glowMaterial);
  glow.position.set(0, base + 1.1, 0);
  glow.scale.set(0.72, 0.72, 1);
  group.add(glow);

  const beamMaterial = new THREE.MeshBasicMaterial({
    color: "#ffe3a6",
    transparent: true,
    opacity: 0,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
  });
  const beamGeometry = new THREE.ConeGeometry(0.34, 2.2, 20, 1, true);
  beamGeometry.translate(0, 1.1, 0);
  beamGeometry.rotateZ(Math.PI / 2);
  beamGeometry.translate(2.2, 0, 0);
  const beamGroup = new THREE.Group();
  beamGroup.position.y = base + 1.1;
  group.add(beamGroup);
  const beam = new THREE.Mesh(beamGeometry, beamMaterial);
  beamGroup.add(beam);
  const backBeam = new THREE.Mesh(beamGeometry, beamMaterial);
  backBeam.rotation.y = Math.PI;
  beamGroup.add(backBeam);

  return { group, lantern, glow, beamGroup, beamMaterial };
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

function addFlowerBeds(parent, materials) {
  const dummy = new THREE.Object3D();
  const flowerGeometry = new THREE.IcosahedronGeometry(0.028, 0);
  const flowerMaterial = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.8 });
  const flowers = [];
  const colors = ["#e88b79", "#f3c55b", "#d97ab0", "#f7e8ce", "#8fb5dc"];
  const beds = [
    [-2.4, 0.55, 0.45, 0.24],
    [1.8, 2.7, 0.42, 0.22],
    [-0.5, 2.63, 0.34, 0.2],
    [3.1, 1.2, 0.32, 0.2],
  ];
  for (const [x, z, radius, height] of beds) {
    for (let index = 0; index < 14; index += 1) {
      const angle = Math.random() * Math.PI * 2;
      const distance = Math.sqrt(Math.random()) * radius;
      const fx = x + Math.cos(angle) * distance;
      const fz = z + Math.sin(angle) * distance;
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

function addRocks(parent, materials) {
  const random = seededRandom(7341);
  const geometry = new THREE.DodecahedronGeometry(1, 0);
  const material = materials.standard("#76736b", { roughness: 1, flatShading: true });
  const spots = [];
  for (let attempt = 0; attempt < 120 && spots.length < 23; attempt += 1) {
    const angle = random() * Math.PI * 2;
    const radius = 0.9 + random() * 0.09;
    const x = Math.cos(angle) * 5.7 * radius;
    const z = Math.sin(angle) * 4.75 * radius;
    const height = terrainHeightAt(x, z);
    if (height < WATER_LEVEL - 0.08 || height > WATER_LEVEL + 0.18) continue;
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

function addBushes(parent, materials) {
  const random = seededRandom(1987);
  const geometry = new THREE.IcosahedronGeometry(1, 0);
  const material = materials.standard("#5e8253", { roughness: 1, flatShading: true });
  const spots = [];
  for (let attempt = 0; attempt < 150 && spots.length < 34; attempt += 1) {
    const x = (random() * 2 - 1) * 4.9;
    const z = (random() * 2 - 1) * 4.1;
    const height = terrainHeightAt(x, z);
    if (height < WATER_LEVEL + 0.17 || Math.hypot(x, z) < 1.35) continue;
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
  materials.detailTexture = makeDetailTexture();
  materials.cobbleTexture = makeCobbleTexture();
  materials.woodTexture = makeWoodTexture();
  materials.plaqueTexture = makePlaqueTexture();
  materials.clockTexture = makeClockTexture();
  materials.glowTexture = makeGlowTexture();
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
  const windows = {
    warm: new THREE.MeshStandardMaterial({
      color: "#dfb574", emissive: WARM_WINDOW, emissiveIntensity: 0.04, roughness: 0.42,
    }),
    cool: new THREE.MeshStandardMaterial({
      color: "#6d8a96", emissive: COOL_WINDOW, emissiveIntensity: 0.02, roughness: 0.34,
    }),
  };
  materials.windows = windows;
  const clockFace = new THREE.MeshStandardMaterial({
    map: materials.clockTexture,
    emissiveMap: materials.clockTexture,
    emissive: "#ffd78a",
    emissiveIntensity: 0.03,
    roughness: 0.62,
  });
  materials.clock = clockFace;

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

  const plazaGround = terrainHeightAt(-0.1, 0.55);
  cylinder(group, 0.82, 0.88, 0.055, 36, [-0.1, plazaGround + 0.02, 0.55], materials.cobble);
  const plazaRing = new THREE.Mesh(
    new THREE.TorusGeometry(0.84, 0.016, 8, 48),
    materials.standard("#a38b63", { metalness: 0.55, roughness: 0.46 }),
  );
  plazaRing.rotation.x = Math.PI / 2;
  plazaRing.position.set(-0.1, plazaGround + 0.058, 0.55);
  group.add(plazaRing);

  const buildings = [
    { x: -1.52, z: -0.82, rotation: 0.1, kind: "townhouse", width: 0.66, depth: 0.52, height: 1.34, wall: "#c57257", roof: "#744238" },
    { x: -0.42, z: -1.18, rotation: -0.08, kind: "townhouse", width: 0.58, depth: 0.5, height: 1.52, wall: "#d3a558", roof: "#814b3f" },
    { x: 0.8, z: -1.32, rotation: 0.16, kind: "townhouse", width: 0.68, depth: 0.5, height: 1.08, wall: "#cf8062", roof: "#654b47" },
    { x: 1.62, z: -0.14, rotation: -0.26, kind: "townhouse", width: 0.56, depth: 0.48, height: 0.9, wall: "#b96d58", roof: "#7c4c3b" },
    { x: 0.62, z: 0.92, rotation: 0.2, kind: "townhouse", width: 0.62, depth: 0.48, height: 1.12, wall: "#d29b61", roof: "#6b4a3f" },
    { x: -1.68, z: 1.18, rotation: -0.24, kind: "townhouse", width: 0.58, depth: 0.5, height: 0.98, wall: "#c98063", roof: "#6e4a40" },

    { x: 2.9, z: 1.35, rotation: 0.48, kind: "harbor", wall: "#e1b578", roof: "#4f7d86" },
    { x: 3.38, z: 2.08, rotation: 0.22, kind: "harbor", wall: "#d89879", roof: "#3f6b75" },
    { x: 2.08, z: 2.35, rotation: -0.4, kind: "harbor", wall: "#e2c28b", roof: "#567f80" },

    { x: -3.35, z: -1.75, rotation: 0.32, kind: "cottage", width: 0.52, depth: 0.44, height: 0.48, wall: "#e0c68f", roof: "#95604b" },
    { x: -2.38, z: -2.45, rotation: -0.36, kind: "cottage", width: 0.47, depth: 0.42, height: 0.44, wall: "#d9b978", roof: "#7f5a4c" },
    { x: -4.12, z: -0.82, rotation: 0.84, kind: "cottage", width: 0.46, depth: 0.4, height: 0.46, wall: "#e3c699", roof: "#8b5b49" },
    { x: -3.55, z: 0.48, rotation: -0.18, kind: "cottage", width: 0.54, depth: 0.46, height: 0.5, wall: "#d7b07a", roof: "#805246" },

    { x: 0.72, z: 2.7, rotation: -0.22, kind: "cottage", width: 0.55, depth: 0.45, height: 0.45, wall: "#e0c183", roof: "#a45c4e" },
    { x: -0.34, z: 2.92, rotation: 0.24, kind: "cottage", width: 0.5, depth: 0.43, height: 0.43, wall: "#d6b68e", roof: "#8e5948" },
    { x: 1.55, z: 2.95, rotation: 0.44, kind: "cottage", width: 0.52, depth: 0.44, height: 0.42, wall: "#e7cf9d", roof: "#9c6751" },
  ];
  for (const building of buildings) {
    const options = { ...building };
    if (building.kind === "townhouse") addTownhouse(group, options, materials, windows);
    else if (building.kind === "harbor") addHarborHouse(group, options, materials, windows);
    else addCottage(group, options, materials, windows);
  }

  const tower = addClockTower(group, materials, windows);
  const lighthouse = addLighthouse(group, materials);
  addFountain(group, materials);

  const lampLights = [];
  for (const [x, z] of [
    [-2.9, 0.78], [-1.62, 0.42], [-0.34, 0.34], [0.98, 0.55],
    [2.2, 0.76], [3.15, 1.18], [-0.8, -0.58], [0.38, 1.82], [1.15, 2.62],
  ]) {
    addLamp(group, x, z, materials, lampLights);
  }
  for (const [x, z] of [[-1.5, -0.82], [0.8, -1.32], [2.9, 1.35], [-3.35, -1.75]]) {
    const light = new THREE.PointLight("#ffc980", 0, 1.65, 2);
    light.position.set(x, terrainHeightAt(x, z) + 0.43, z);
    group.add(light);
    lampLights.push(light);
  }
  addPier(group, materials);

  const blockers = [
    ...buildings.map(building => ({ x: building.x, z: building.z, r: 0.58 })),
    { x: -0.1, z: -0.2, r: 0.62 },
    { x: 3.9, z: -1.65, r: 0.55 },
    { x: -0.1, z: 0.55, r: 0.9 },
    { x: -1.42, z: 1.04, r: 0.46 },
  ];
  const treeRandom = seededRandom(44121);
  const decidTrees = [];
  const coniferTrees = [];
  const zones = [
    { count: 34, x: -3.45, z: -1.55, rx: 1.6, rz: 1.55 },
    { count: 22, x: 0.9, z: 3.1, rx: 1.95, rz: 0.85 },
    { count: 14, x: 2.5, z: 2.8, rx: 1.1, rz: 0.9 },
    { count: 12, x: -2.2, z: 2.65, rx: 1.6, rz: 0.72 },
    { count: 8, x: 4.0, z: 0.1, rx: 0.55, rz: 1.0 },
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
  addFlowerBeds(group, materials);
  addRocks(group, materials);
  addBushes(group, materials);

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
    windows.warm.emissiveIntensity = 0.035 + day.night * 2.15;
    windows.cool.emissiveIntensity = 0.018 + day.night * 1.15;
    materials.lampBulb.emissiveIntensity = 0.15 + day.night * 3.1;
    materials.lanternGlass.emissiveIntensity = 0.25 + day.night * 2.3;
    materials.glowMaterial.opacity = day.night * 0.8;
    materials.clock.emissiveIntensity = 0.03 + day.night * 0.9;
    lighthouse.beamMaterial.opacity = day.night * 0.045;
    lightReflectionMaterial.opacity = day.night * 0.48;
    const flicker = 0.94 + Math.sin(performance.now() * 0.004) * 0.06 * day.night;
    for (const light of lampLights) {
      light.color.set(LAMP_GLOW);
      light.intensity = day.night * 4.65 * flicker;
    }
    lighthouse.lantern.intensity = day.night * 3.1;
    fireflyMaterial.opacity = day.night * 0.74;
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
    lighthouse.beamGroup.rotation.y = elapsed * 0.46;
    for (const floater of floaters) {
      const bob = Math.sin(elapsed * 1.25 + floater.phase) * (reducedMotion ? 0.006 : 0.018);
      floater.group.position.y = floater.baseY + bob;
      floater.group.rotation.z = Math.sin(elapsed * 1.1 + floater.phase) * (reducedMotion ? 0.006 : 0.024);
    }
    for (const hand of tower.hands) {
      hand.children[0].rotation.z = -phase * 2 * Math.PI * 2;
      hand.children[1].rotation.z = -phase * 24 * Math.PI * 2 - 0.6;
    }
    fireflies.rotation.y = elapsed * 0.018;
    if (elapsed - lastShadowAt > 1.6) {
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
    lights.hemisphere.color.copy(day.sky);
    lights.hemisphere.groundColor.copy(day.ground);
    lights.hemisphere.intensity = roomDark ? Math.min(day.ambient, 0.24) : day.ambient;
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
    update,
    setSceneLights,
    setRoomDark(value) {
      roomDark = Boolean(value);
    },
    get phase() {
      return lastPhase;
    },
    dispose() {
      disposed = true;
      disposeBoardTree(group);
    },
  };
}
