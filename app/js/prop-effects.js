import * as THREE from "three";

/**
 * Render YAML-defined prop effects in the room board.
 *
 * An effect set is a list of effect descriptors, each with ordered layers.
 * Three layer types are supported: `transform` (animated transformation of
 * the host), `material` (emissive/opacity/colour changes on the host's
 * meshes), and `particle` (a procedural additive/soft sprite overlay).
 *
 * The returned controller is inert when motion is reduced so visual snapshots
 * stay deterministic; `createPropEffects` returns null in that case.
 */

const PARTICLE_TEXTURES = new Map();

function sharedTexture(url, loader) {
  if (!PARTICLE_TEXTURES.has(url)) {
    PARTICLE_TEXTURES.set(url, new Promise(resolve => {
      loader.load(url, texture => {
        texture.colorSpace = THREE.SRGBColorSpace;
        resolve(texture);
      }, undefined, () => resolve(null));
    }));
  }
  return PARTICLE_TEXTURES.get(url);
}

function anchorPosition(bounds, anchor, offset) {
  const center = bounds.getCenter(new THREE.Vector3());
  const baseY = bounds.min.y;
  const topY = bounds.max.y;
  const height = Math.max(0.0001, topY - baseY);
  const localY = anchor === "base" ? 0 : anchor === "center" ? height / 2 : height;
  return new THREE.Vector3(center.x + offset[0], localY + offset[1], center.z + offset[2]);
}

function transformLayer({ visual, layer }) {
  const basePosition = visual.position.clone();
  const baseQuaternion = visual.quaternion.clone();
  const baseScale = visual.scale.clone();
  const axis = new THREE.Vector3(...(layer.axis || [0, 1, 0]));
  if (axis.lengthSq() === 0) axis.set(0, 1, 0);
  axis.normalize();
  let elapsed = Number(layer.phase) || 0;
  const period = Math.max(0.05, Number(layer.period) || 3);
  const amplitude = Number(layer.amplitude) || 0;

  function update(delta) {
    elapsed += delta;
    const wave = Math.sin((elapsed / period) * Math.PI * 2);
    if (layer.motion === "bob") {
      visual.position.copy(basePosition);
      visual.position.y += wave * amplitude;
    } else if (layer.motion === "pulse") {
      visual.scale.copy(baseScale).multiplyScalar(1 + wave * amplitude * 0.1);
    } else if (layer.motion === "sway" || layer.motion === "shake") {
      const spin = new THREE.Quaternion().setFromAxisAngle(axis, wave * amplitude);
      visual.quaternion.copy(baseQuaternion).multiply(spin);
      if (layer.motion === "shake") {
        visual.position.copy(basePosition);
        visual.position.x += Math.sin(elapsed * 9) * amplitude * 0.25;
        visual.position.z += Math.cos(elapsed * 11) * amplitude * 0.25;
      }
    } else {
      const radians = (elapsed / period) * Math.PI * 2;
      const spin = new THREE.Quaternion().setFromAxisAngle(axis, radians);
      visual.quaternion.copy(baseQuaternion).multiply(spin);
    }
  }

  function dispose() {
    visual.position.copy(basePosition);
    visual.quaternion.copy(baseQuaternion);
    visual.scale.copy(baseScale);
  }

  return { update, dispose };
}

function materialLayer({ model, layer }) {
  const saved = [];
  const emissive = layer.emissive ? new THREE.Color(layer.emissive) : null;
  const tint = layer.color ? new THREE.Color(layer.color) : null;
  const baseIntensity = Number(layer.emissive_intensity) || 0;
  const flicker = Number(layer.flicker) || 0;
  const flickerHz = Number(layer.flicker_hz) || 6;
  let elapsed = 0;

  model.traverse(node => {
    if (!node.isMesh || !node.material) return;
    const original = node.material;
    if (Array.isArray(original)) return;
    const clone = original.clone();
    saved.push([node, original, clone]);
    if (emissive && clone.emissive) {
      clone.emissive.copy(emissive);
      clone.emissiveIntensity = baseIntensity;
    }
    if (tint) clone.color.copy(tint);
    if (typeof layer.opacity === "number") {
      clone.transparent = true;
      clone.opacity = layer.opacity;
    }
    node.material = clone;
  });

  function update(delta) {
    if (!flicker) return;
    elapsed += delta;
    const modulation = 1 + Math.sin(elapsed * flickerHz * Math.PI * 2) * flicker;
    for (const [, , clone] of saved) {
      if (clone.emissive) clone.emissiveIntensity = baseIntensity * Math.max(0, modulation);
    }
  }

  function dispose() {
    for (const [node, original, clone] of saved) {
      node.material = original;
      clone.dispose();
    }
    saved.length = 0;
  }

  return { update, dispose };
}

function particleLayer({ group, bounds, layer, loader, pixelScale }) {
  const max = Math.max(1, Number(layer.max_particles) || 40);
  const origin = anchorPosition(bounds, layer.anchor || "top", layer.offset || [0, 0, 0]);
  const [lifeMin, lifeMax] = layer.lifetime || [1.5, 2.5];
  const [sizeMin, sizeMax] = layer.size || [0.3, 0.8];
  const [alphaMin, alphaMax] = layer.opacity || [0.7, 0.0];
  const gravity = Number(layer.gravity) || 0;
  const speed = Number(layer.speed) || 0;
  const spread = THREE.MathUtils.degToRad(Number(layer.spread) || 0);

  const positions = new Float32Array(max * 3);
  const sizes = new Float32Array(max);
  const alphas = new Float32Array(max);
  const velocity = new Float32Array(max * 3);
  const age = new Float32Array(max);
  const life = new Float32Array(max);
  const alive = new Uint8Array(max);

  const geometry = new THREE.BufferGeometry();
  const positionAttribute = new THREE.BufferAttribute(positions, 3);
  positionAttribute.setUsage(THREE.DynamicDrawUsage);
  const sizeAttribute = new THREE.BufferAttribute(sizes, 1);
  sizeAttribute.setUsage(THREE.DynamicDrawUsage);
  const alphaAttribute = new THREE.BufferAttribute(alphas, 1);
  alphaAttribute.setUsage(THREE.DynamicDrawUsage);
  geometry.setAttribute("position", positionAttribute);
  geometry.setAttribute("size", sizeAttribute);
  geometry.setAttribute("alpha", alphaAttribute);
  geometry.setDrawRange(0, max);

  const uniforms = {
    uMap: { value: null },
    uColor: { value: new THREE.Color(layer.color || "#ffffff") },
    uScale: { value: pixelScale ? pixelScale() : 600 },
    uSizeScale: { value: Math.max(0.0001, Math.abs(group.scale.x) || 1) },
    uHasMap: { value: 0 },
  };
  const material = new THREE.ShaderMaterial({
    uniforms,
    transparent: true,
    depthWrite: false,
    blending: layer.additive ? THREE.AdditiveBlending : THREE.NormalBlending,
    vertexShader: `
      attribute float size;
      attribute float alpha;
      varying float vAlpha;
      uniform float uScale;
      uniform float uSizeScale;
      void main() {
        vAlpha = alpha;
        vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
        gl_PointSize = max(1.0, size * uSizeScale * (uScale / max(0.001, -mvPosition.z)));
        gl_Position = projectionMatrix * mvPosition;
      }
    `,
    fragmentShader: `
      uniform sampler2D uMap;
      uniform vec3 uColor;
      uniform float uHasMap;
      varying float vAlpha;
      void main() {
        if (vAlpha <= 0.001) discard;
        vec4 shape = uHasMap > 0.5 ? texture2D(uMap, gl_PointCoord) : vec4(1.0);
        gl_FragColor = vec4(uColor * shape.rgb, shape.a * vAlpha);
      }
    `,
  });

  const points = new THREE.Points(geometry, material);
  points.frustumCulled = false;
  points.visible = false;
  group.add(points);

  let ready = false;
  sharedTexture(layer.texture_url, loader).then(texture => {
    if (!texture) return;
    uniforms.uMap.value = texture;
    uniforms.uHasMap.value = 1;
    ready = true;
    points.visible = true;
  });

  let cursor = 0;
  let emitAccumulator = 0;

  function spawn() {
    const index = cursor;
    cursor = (cursor + 1) % max;
    const theta = Math.random() * Math.PI * 2;
    const tilt = Math.random() * spread;
    const horizontal = Math.sin(tilt) * speed;
    positions[index * 3] = origin.x;
    positions[index * 3 + 1] = origin.y;
    positions[index * 3 + 2] = origin.z;
    velocity[index * 3] = Math.cos(theta) * horizontal;
    velocity[index * 3 + 1] = Math.cos(tilt) * speed;
    velocity[index * 3 + 2] = Math.sin(theta) * horizontal;
    age[index] = 0;
    life[index] = lifeMin + Math.random() * Math.max(0, lifeMax - lifeMin);
    alive[index] = 1;
    sizes[index] = sizeMin;
    alphas[index] = alphaMin;
  }

  function update(delta) {
    if (ready) {
      emitAccumulator += (Number(layer.rate) || 0) * delta;
      let budget = max;
      while (emitAccumulator >= 1 && budget > 0) {
        spawn();
        emitAccumulator -= 1;
        budget -= 1;
      }
    } else {
      emitAccumulator = 0;
    }
    for (let index = 0; index < max; index += 1) {
      if (!alive[index]) {
        alphas[index] = 0;
        sizes[index] = 0;
        continue;
      }
      age[index] += delta;
      const progress = Math.min(1, age[index] / Math.max(0.0001, life[index]));
      if (progress >= 1) {
        alive[index] = 0;
        alphas[index] = 0;
        sizes[index] = 0;
        continue;
      }
      velocity[index * 3 + 1] += gravity * delta;
      positions[index * 3] += velocity[index * 3] * delta;
      positions[index * 3 + 1] += velocity[index * 3 + 1] * delta;
      positions[index * 3 + 2] += velocity[index * 3 + 2] * delta;
      sizes[index] = sizeMin + (sizeMax - sizeMin) * progress;
      alphas[index] = alphaMin + (alphaMax - alphaMin) * progress;
    }
    if (pixelScale) uniforms.uScale.value = pixelScale();
    // Prop scale lives on the host group; point sprites must be scaled
    // explicitly since gl_PointSize ignores the model matrix.
    uniforms.uSizeScale.value = Math.max(0.0001, Math.abs(group.scale.x) || 1);
    positionAttribute.needsUpdate = true;
    sizeAttribute.needsUpdate = true;
    alphaAttribute.needsUpdate = true;
  }

  function dispose() {
    group.remove(points);
    geometry.dispose();
    material.dispose();
  }

  return {
    update,
    dispose,
    get sizeScale() {
      return uniforms.uSizeScale.value;
    },
  };
}

function buildLayer(context, layer) {
  if (!layer || typeof layer !== "object") return null;
  if (layer.type === "transform") return transformLayer({ visual: context.visual, layer });
  if (layer.type === "material") return materialLayer({ model: context.model, layer });
  if (layer.type === "particle") return particleLayer({ ...context, layer });
  return null;
}

/**
 * Build a controller for one prop's effect sets. Returns null when effects are
 * disabled (reduced motion) or the prop has no usable layers.
 */
export function createPropEffects({
  group,
  visual,
  model,
  bounds,
  effectSets,
  activeEffect,
  reducedMotion,
  textureLoader,
  pixelScale,
}) {
  if (reducedMotion || !effectSets || !Object.keys(effectSets).length) return null;
  const context = { group, visual, model, bounds, loader: textureLoader, pixelScale };
  let layers = [];

  function disposeLayers() {
    for (const controller of layers) controller.dispose();
    layers = [];
  }

  function build(setName) {
    disposeLayers();
    const effects = effectSets[setName];
    if (!Array.isArray(effects)) return;
    for (const effect of effects) {
      for (const layer of effect?.layers || []) {
        const controller = buildLayer(context, layer);
        if (controller) layers.push(controller);
      }
    }
  }

  build(activeEffect && effectSets[activeEffect] ? activeEffect : Object.keys(effectSets)[0]);

  return {
    update(delta) {
      for (const controller of layers) controller.update(delta);
    },
    setActiveEffect(setName) {
      if (!effectSets[setName] || setName === undefined) return;
      build(setName);
    },
    get activeCount() {
      return layers.length;
    },
    /** World-space scale applied to point sprites (mirrors the host prop scale). */
    get sizeScale() {
      const particle = layers.find(layer => typeof layer.sizeScale === "number");
      return particle ? particle.sizeScale : 1;
    },
    dispose: disposeLayers,
  };
}
