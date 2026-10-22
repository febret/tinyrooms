// Terrain sampling and meshes for the procedural TinyTown diorama.

import * as THREE from "three";

export const WATER_LEVEL = 0.035;
export const HALF_WIDTH = 6.0;
export const HALF_DEPTH = 5.0;

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

function smoothstep(edge0, edge1, value) {
  const t = clamp((value - edge0) / (edge1 - edge0), 0, 1);
  return t * t * (3 - 2 * t);
}

export function hash2(x, z) {
  const value = Math.sin(x * 127.1 + z * 311.7) * 43758.5453123;
  return value - Math.floor(value);
}

function noise2(x, z) {
  const ix = Math.floor(x);
  const iz = Math.floor(z);
  const fx = x - ix;
  const fz = z - iz;
  const sx = fx * fx * (3 - 2 * fx);
  const sz = fz * fz * (3 - 2 * fz);
  const a = hash2(ix, iz);
  const b = hash2(ix + 1, iz);
  const c = hash2(ix, iz + 1);
  const d = hash2(ix + 1, iz + 1);
  return (a + (b - a) * sx) * (1 - sz) + (c + (d - c) * sx) * sz;
}

function fbm(x, z) {
  let value = 0;
  let amplitude = 0.55;
  let frequency = 1;
  for (let octave = 0; octave < 4; octave += 1) {
    value += noise2(x * frequency, z * frequency) * amplitude;
    frequency *= 2.02;
    amplitude *= 0.48;
  }
  return value;
}

function gauss(x, z, sx, sz) {
  return Math.exp(-0.5 * ((x / sx) ** 2 + (z / sz) ** 2));
}

export function seededRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

/** Height of the generated island, in board-local world units. */
export function terrainHeightAt(x, z) {
  const radius = Math.hypot(x / 5.7, z / 4.75);
  const angle = Math.atan2(z / 4.75, x / 5.7);
  const coast = 0.8
    + 0.075 * Math.sin(angle * 3 + 0.9)
    + 0.04 * Math.sin(angle * 6 - 0.4)
    + 0.02 * Math.sin(angle * 11 + 2.2);
  const coastline = 1 - smoothstep(coast - 0.075, coast + 0.075, radius);
  const bay = Math.exp(-((((x - 3.35) / 1.35) ** 2) + (((z + 0.05) / 1.15) ** 2)));
  const land = Math.max(0, coastline * (1 - bay * 0.66));

  const hills = gauss(x + 3.3, z + 1.8, 1.35, 1.05) * 1.12
    + gauss(x + 4.25, z - 0.4, 0.92, 0.82) * 0.48;
  const rise = gauss(x - 0.1, z - 0.2, 2.1, 1.9) * 0.16;
  const detail = (fbm(x * 1.35 + 9, z * 1.35 - 4) - 0.5) * 0.13
    + (fbm(x * 3.8, z * 3.8) - 0.5) * 0.025;
  const natural = WATER_LEVEL + 0.075 + hills + rise + detail;

  const flat = gauss(x - 0.15, z - 0.2, 1.55, 1.35);
  const plateau = WATER_LEVEL + 0.3 + (fbm(x * 2.4, z * 2.4) - 0.5) * 0.03;
  const landHeight = natural + (plateau - natural) * flat * 0.72;
  const seabed = WATER_LEVEL - 0.43 - fbm(x * 0.9 + 3, z * 0.9 + 7) * 0.18;
  return seabed + land * (landHeight - seabed);
}

/** Build the vertex-coloured island height field. */
export function buildTerrain(materials) {
  const segmentsX = 150;
  const segmentsZ = 126;
  const positions = [];
  const colors = [];
  const uvs = [];
  const indices = [];
  const sand = new THREE.Color("#d5bd87");
  const wetSand = new THREE.Color("#ad9668");
  const grassA = new THREE.Color("#77995f");
  const grassB = new THREE.Color("#9aae73");
  const grassC = new THREE.Color("#587b52");
  const rock = new THREE.Color("#7c7568");
  const color = new THREE.Color();

  for (let iz = 0; iz <= segmentsZ; iz += 1) {
    const z = -HALF_DEPTH + iz / segmentsZ * HALF_DEPTH * 2;
    for (let ix = 0; ix <= segmentsX; ix += 1) {
      const x = -HALF_WIDTH + ix / segmentsX * HALF_WIDTH * 2;
      const height = terrainHeightAt(x, z);
      const slope = Math.abs(terrainHeightAt(x + 0.08, z) - terrainHeightAt(x - 0.08, z))
        + Math.abs(terrainHeightAt(x, z + 0.08) - terrainHeightAt(x, z - 0.08));
      const shade = fbm(x * 2.6 + 4, z * 2.6 - 2);
      positions.push(x, height, z);
      uvs.push((x + HALF_WIDTH) / (HALF_WIDTH * 2), (z + HALF_DEPTH) / (HALF_DEPTH * 2));

      if (height < WATER_LEVEL + 0.015) {
        color.copy(wetSand).multiplyScalar(0.8 + shade * 0.16);
      } else if (height < WATER_LEVEL + 0.095 + shade * 0.025) {
        color.copy(sand).lerp(wetSand, clamp((WATER_LEVEL + 0.12 - height) * 5, 0, 1));
      } else {
        color.copy(grassA).lerp(grassB, shade * 0.8);
        if (height > 0.9 || slope > 0.34) color.lerp(rock, smoothstep(0.3, 0.8, slope));
        if (shade > 0.66) color.lerp(grassC, (shade - 0.66) * 1.8);
      }
      const light = 0.84 + fbm(x * 8, z * 8) * 0.24;
      color.multiplyScalar(light);
      colors.push(color.r, color.g, color.b);
    }
  }
  for (let iz = 0; iz < segmentsZ; iz += 1) {
    for (let ix = 0; ix < segmentsX; ix += 1) {
      const a = iz * (segmentsX + 1) + ix;
      const b = a + 1;
      const c = a + segmentsX + 1;
      const d = c + 1;
      indices.push(a, c, b, b, c, d);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const material = new THREE.MeshStandardMaterial({
    vertexColors: true,
    roughness: 0.96,
    metalness: 0,
    bumpMap: materials.detailTexture,
    bumpScale: 0.012,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

/** Build a flat ribbon that follows the island surface. */
export function makeRibbon(points, width, material, lift = 0.018) {
  const curve = new THREE.CatmullRomCurve3(
    points.map(([x, z]) => new THREE.Vector3(x, 0, z)),
    false,
    "catmullrom",
    0.3,
  );
  const samples = 110;
  const positions = [];
  const uvs = [];
  const indices = [];
  for (let index = 0; index <= samples; index += 1) {
    const t = index / samples;
    const point = curve.getPoint(t);
    const tangent = curve.getTangent(t);
    const side = new THREE.Vector3(-tangent.z, 0, tangent.x).normalize();
    const height = terrainHeightAt(point.x, point.z) + lift;
    positions.push(
      point.x - side.x * width / 2, height, point.z - side.z * width / 2,
      point.x + side.x * width / 2, height, point.z + side.z * width / 2,
    );
    uvs.push(0, t * 7, 1, t * 7);
    if (index < samples) {
      const base = index * 2;
      indices.push(base, base + 2, base + 1, base + 1, base + 2, base + 3);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

/** Build a foam contour from the terrain/water intersection. */
export function addShoreline(parent) {
  const segments = 92;
  const positions = [];
  for (let iz = 0; iz < 70; iz += 1) {
    for (let ix = 0; ix < segments; ix += 1) {
      const x0 = -HALF_WIDTH + ix / segments * HALF_WIDTH * 2;
      const x1 = -HALF_WIDTH + (ix + 1) / segments * HALF_WIDTH * 2;
      const z0 = -HALF_DEPTH + iz / 70 * HALF_DEPTH * 2;
      const z1 = -HALF_DEPTH + (iz + 1) / 70 * HALF_DEPTH * 2;
      const points = [
        [x0, z0, terrainHeightAt(x0, z0) - WATER_LEVEL],
        [x1, z0, terrainHeightAt(x1, z0) - WATER_LEVEL],
        [x1, z1, terrainHeightAt(x1, z1) - WATER_LEVEL],
        [x0, z1, terrainHeightAt(x0, z1) - WATER_LEVEL],
      ];
      const crossings = [];
      for (let edge = 0; edge < 4; edge += 1) {
        const first = points[edge];
        const second = points[(edge + 1) % 4];
        if (first[2] * second[2] > 0) continue;
        const t = Math.abs(first[2]) / (Math.abs(first[2]) + Math.abs(second[2]) || 1);
        crossings.push([
          first[0] + (second[0] - first[0]) * t,
          first[1] + (second[1] - first[1]) * t,
        ]);
      }
      if (crossings.length === 2) {
        positions.push(crossings[0][0], WATER_LEVEL + 0.012, crossings[0][1]);
        positions.push(crossings[1][0], WATER_LEVEL + 0.012, crossings[1][1]);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  const material = new THREE.LineBasicMaterial({
    color: "#e9f4dd", transparent: true, opacity: 0.55, depthWrite: false,
  });
  const lines = new THREE.LineSegments(geometry, material);
  lines.renderOrder = 3;
  parent.add(lines);
  return lines;
}
