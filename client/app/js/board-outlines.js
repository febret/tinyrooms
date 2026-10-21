import * as THREE from "three";

import { hasActivePropActions } from "./prop-actions.js";

const MASK_VERTEX = `
  #include <common>
  #include <morphtarget_pars_vertex>
  #include <skinning_pars_vertex>
  void main() {
    #include <begin_vertex>
    #include <morphtarget_vertex>
    #include <skinbase_vertex>
    #include <skinning_vertex>
    #include <project_vertex>
  }
`;

const MASK_FRAGMENT = `
  uniform sampler2D sceneDepth;
  uniform vec2 resolution;
  uniform vec3 category;
  void main() {
    // Reject fragments hidden by the room, so overlapping props keep their visible silhouette.
    float depth = texture2D(sceneDepth, gl_FragCoord.xy / resolution).r;
    if (gl_FragCoord.z > depth + 0.00002) discard;
    gl_FragColor = vec4(category, 1.0);
  }
`;

const COMPOSITE_VERTEX = `
  varying vec2 outlineUv;
  void main() {
    outlineUv = position.xy * 0.5 + 0.5;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const COMPOSITE_FRAGMENT = `
  uniform sampler2D sceneColor;
  uniform sampler2D mask;
  uniform vec2 resolution;
  varying vec2 outlineUv;

  void main() {
    vec4 original = texture2D(sceneColor, outlineUv);
    vec4 center = texture2D(mask, outlineUv);
    if (center.a > 0.5) {
      gl_FragColor = original;
      #include <colorspace_fragment>
      return;
    }

    vec2 pixel = 1.0 / resolution;
    float selected = 0.0;
    float activeEdge = 0.0;
    float glow = 0.0;
    for (int x = -2; x <= 2; x++) {
      for (int y = -2; y <= 2; y++) {
        float distance = length(vec2(float(x), float(y)));
        vec4 neighbor = texture2D(mask, outlineUv + vec2(float(x), float(y)) * pixel);
        if (distance <= 2.5) {
          selected = max(selected, neighbor.r * neighbor.a);
          activeEdge = max(activeEdge, neighbor.g * neighbor.a);
        }
        glow = max(glow, neighbor.r * neighbor.a * (1.0 - distance / 4.5));
      }
    }
    for (int x = -1; x <= 1; x++) {
      for (int y = -1; y <= 1; y++) {
        if (x == 0 && y == 0) continue;
        vec4 neighbor = texture2D(mask, outlineUv + vec2(float(x), float(y)) * pixel * 4.0);
        glow = max(glow, neighbor.r * neighbor.a * 0.12);
      }
    }

    vec3 color = original.rgb;
    float alpha = original.a;
    if (activeEdge > 0.5) {
      color = mix(color, vec3(0.012, 0.02, 0.027), 0.92);
      alpha = max(alpha, 0.95);
    }
    if (glow > 0.0) {
      color = mix(color, vec3(0.18, 0.50, 0.95), min(0.6, glow * 0.85));
      alpha = max(alpha, glow * 0.6);
    }
    if (selected > 0.5) {
      color = vec3(0.42, 0.76, 1.0);
      alpha = 1.0;
    }
    gl_FragColor = vec4(color, alpha);
    #include <colorspace_fragment>
  }
`;

/** Composite crisp pixel-width silhouettes from visible prop geometry onto the room board. */
export function createBoardOutlines(renderer, scene, camera) {
  const resolution = new THREE.Vector2(1, 1);
  const sceneTarget = new THREE.WebGLRenderTarget(1, 1, { depthBuffer: true, samples: 4 });
  sceneTarget.texture.colorSpace = renderer.outputColorSpace;
  sceneTarget.depthTexture = new THREE.DepthTexture(1, 1, THREE.UnsignedIntType);
  sceneTarget.depthTexture.minFilter = THREE.NearestFilter;
  sceneTarget.depthTexture.magFilter = THREE.NearestFilter;
  const maskTarget = new THREE.WebGLRenderTarget(1, 1, { depthBuffer: true });
  maskTarget.texture.minFilter = THREE.NearestFilter;
  maskTarget.texture.magFilter = THREE.NearestFilter;
  const maskScene = new THREE.Scene();
  const selectedMask = new THREE.Scene();
  const maskMaterials = [new THREE.ShaderMaterial({
    vertexShader: MASK_VERTEX, fragmentShader: MASK_FRAGMENT, side: THREE.DoubleSide,
    uniforms: { sceneDepth: { value: sceneTarget.depthTexture }, resolution: { value: resolution }, category: { value: new THREE.Vector3(1, 0, 0) } },
  }), new THREE.ShaderMaterial({
    vertexShader: MASK_VERTEX, fragmentShader: MASK_FRAGMENT, side: THREE.DoubleSide,
    uniforms: { sceneDepth: { value: sceneTarget.depthTexture }, resolution: { value: resolution }, category: { value: new THREE.Vector3(0, 1, 0) } },
  })];
  const compositeMaterial = new THREE.ShaderMaterial({
    vertexShader: COMPOSITE_VERTEX, fragmentShader: COMPOSITE_FRAGMENT,
    depthTest: false, depthWrite: false, transparent: false, toneMapped: false,
    uniforms: { sceneColor: { value: sceneTarget.texture }, mask: { value: maskTarget.texture }, resolution: { value: resolution } },
  });
  const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), compositeMaterial);
  const compositeScene = new THREE.Scene();
  compositeScene.add(quad);
  const compositeCamera = new THREE.Camera();
  const records = new Set();
  let highlighted = 0;
  let selectedCount = 0;

  function attach(record) {
    if (!record.model || record.outlines) return;
    record.outlines = [];
    record.model.traverse(source => {
      if (!source.isMesh || !source.geometry) return;
      const proxy = source.isSkinnedMesh
        ? new THREE.SkinnedMesh(source.geometry, maskMaterials[0])
        : new THREE.Mesh(source.geometry, maskMaterials[0]);
      if (source.isSkinnedMesh) {
        proxy.bind(source.skeleton, source.bindMatrix);
        proxy.bindMode = source.bindMode;
      }
      if (source.morphTargetInfluences) proxy.morphTargetInfluences = source.morphTargetInfluences;
      proxy.matrixAutoUpdate = false;
      proxy.frustumCulled = false;
      proxy.visible = false;
      maskScene.add(proxy);
      record.outlines.push({ source, proxy });
    });
    records.add(record);
  }

  function update(record, selected, showActive) {
    const kind = selected ? 1 : showActive && hasActivePropActions(record.prop) ? 2 : 0;
    if (kind && !record.outlines) attach(record);
    if (kind && !record.outlines?.length) return false;
    if ((record.outlineKind || 0) === kind) return false;
    if (record.outlineKind) highlighted -= 1;
    if (record.outlineKind === 1) selectedCount -= 1;
    if (kind) highlighted += 1;
    if (kind === 1) selectedCount += 1;
    record.outlineKind = kind;
    for (const { proxy } of record.outlines || []) {
      proxy.visible = Boolean(kind);
      if (kind) proxy.material = maskMaterials[kind === 1 ? 0 : 1];
      if (kind === 1) selectedMask.add(proxy);
      else maskScene.add(proxy);
    }
    return true;
  }

  function remove(record) {
    if (record.outlineKind) highlighted -= 1;
    if (record.outlineKind === 1) selectedCount -= 1;
    for (const { proxy } of record.outlines || []) proxy.parent?.remove(proxy);
    records.delete(record);
    record.outlines = null;
    record.outlineKind = 0;
  }

  function resize(width, height) {
    const pixelRatio = renderer.getPixelRatio();
    const w = Math.max(1, Math.round(width * pixelRatio));
    const h = Math.max(1, Math.round(height * pixelRatio));
    if (resolution.x === w && resolution.y === h) return;
    resolution.set(w, h);
    sceneTarget.setSize(w, h);
    maskTarget.setSize(w, h);
  }

  const clearColor = new THREE.Color();
  function render() {
    if (!highlighted) {
      renderer.render(scene, camera);
      return;
    }
    const previousTarget = renderer.getRenderTarget();
    renderer.setRenderTarget(sceneTarget);
    renderer.render(scene, camera);
    for (const record of records) {
      if (!record.outlineKind) continue;
      for (const { source, proxy } of record.outlines) {
        proxy.matrix.copy(source.matrixWorld);
        let visible = source.visible;
        for (let parent = source.parent; visible && parent; parent = parent.parent) visible = parent.visible;
        proxy.visible = visible;
      }
    }
    renderer.setRenderTarget(maskTarget);
    renderer.getClearColor(clearColor);
    const clearAlpha = renderer.getClearAlpha();
    const autoClear = renderer.autoClear;
    renderer.setClearColor(0, 0);
    renderer.autoClear = true;
    renderer.render(maskScene, camera);
    if (selectedCount) {
      renderer.autoClear = false;
      renderer.clearDepth();
      // The selected mask must overwrite active pixels at shared edges.
      renderer.render(selectedMask, camera);
    }
    renderer.autoClear = autoClear;
    renderer.setRenderTarget(previousTarget);
    renderer.setClearColor(clearColor, clearAlpha);
    renderer.autoClear = true;
    renderer.render(compositeScene, compositeCamera);
    renderer.autoClear = autoClear;
  }

  function dispose() {
    for (const record of [...records]) remove(record);
    sceneTarget.dispose();
    maskTarget.dispose();
    maskMaterials.forEach(material => material.dispose());
    quad.geometry.dispose();
    compositeMaterial.dispose();
  }

  return { update, remove, resize, render, dispose };
}
