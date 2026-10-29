import * as THREE from "three";

import { hasActivePropActions } from "../props/prop-actions.js";

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
  void main() {
    gl_FragColor = vec4(1.0);
  }
`;

const HULL_VERTEX = `
  #include <common>
  #include <morphtarget_pars_vertex>
  #include <skinning_pars_vertex>
  uniform vec2 resolution;
  uniform float width;
  void main() {
    #include <beginnormal_vertex>
    #include <morphnormal_vertex>
    #include <skinbase_vertex>
    #include <skinnormal_vertex>
    #include <defaultnormal_vertex>
    #include <begin_vertex>
    #include <morphtarget_vertex>
    #include <skinning_vertex>
    vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);
    vec4 clipPosition = projectionMatrix * mvPosition;
    vec4 clipNormal = projectionMatrix * vec4(transformedNormal, 0.0);
    vec2 direction = clipNormal.xy;
    float directionLength = length(direction);
    direction = directionLength > 1e-4 ? direction / directionLength : vec2(0.0);
    clipPosition.xy += direction * (width * 2.0 / resolution) * clipPosition.w;
    // Pull the rim a hair toward the camera so contact edges do not z-fight.
    clipPosition.z -= 0.00002 * clipPosition.w;
    gl_Position = clipPosition;
  }
`;

const HULL_FRAGMENT = `
  uniform vec3 color;
  uniform float opacity;
  void main() {
    gl_FragColor = vec4(color, opacity);
    #include <colorspace_fragment>
  }
`;

const ACTIVE_STYLE = { width: 2.5, opacity: 0.92, color: [0.012, 0.02, 0.027] };
const SELECTED_STYLES = [
  { width: 5.7, opacity: 0.10, color: [0.18, 0.50, 0.95] },
  { width: 4.5, opacity: 0.35, color: [0.18, 0.50, 0.95] },
  { width: 2.5, opacity: 1, color: [0.42, 0.76, 1.0] },
];

/**
 * Draw pixel-width prop silhouettes with a hardware stencil and screen-space hull.
 *
 * The previous implementation rendered the whole scene into an MSAA target,
 * rendered a full-resolution mask, then ran a full-screen composite with up to
 * 33 mask taps per pixel. This version uses the depth buffer already in the
 * default framebuffer for occlusion, writes the visible silhouette to stencil,
 * and draws an expanded hull only where the stencil says "outside".
 */
export function createBoardOutlines(renderer, camera) {
  const stencilSupported = Boolean(renderer.getContextAttributes?.().stencil);
  const resolution = new THREE.Vector2(1, 1);
  const activeScene = new THREE.Scene();
  const selectedScene = new THREE.Scene();
  const stencilMaterial = new THREE.ShaderMaterial({
    vertexShader: MASK_VERTEX,
    fragmentShader: MASK_FRAGMENT,
    side: THREE.DoubleSide,
    colorWrite: false,
    depthWrite: false,
    depthTest: true,
    stencilWrite: true,
    stencilFunc: THREE.AlwaysStencilFunc,
    stencilRef: 1,
    stencilFuncMask: 0xff,
    stencilWriteMask: 0xff,
    stencilFail: THREE.KeepStencilOp,
    stencilZFail: THREE.KeepStencilOp,
    stencilZPass: THREE.ReplaceStencilOp,
  });
  const hullMaterial = new THREE.ShaderMaterial({
    vertexShader: HULL_VERTEX,
    fragmentShader: HULL_FRAGMENT,
    uniforms: {
      resolution: { value: resolution },
      width: { value: 2.5 },
      color: { value: new THREE.Color() },
      opacity: { value: 1 },
    },
    side: THREE.FrontSide,
    transparent: true,
    depthTest: true,
    depthWrite: false,
    blending: THREE.NormalBlending,
    toneMapped: false,
    polygonOffset: true,
    polygonOffsetFactor: -1,
    polygonOffsetUnits: -1,
    stencilWrite: true,
    stencilFunc: THREE.NotEqualStencilFunc,
    stencilRef: 1,
    stencilFuncMask: 0xff,
    stencilWriteMask: 0,
    stencilFail: THREE.KeepStencilOp,
    stencilZFail: THREE.KeepStencilOp,
    stencilZPass: THREE.KeepStencilOp,
  });
  const records = new Set();
  let lastPasses = 0;

  function attach(record) {
    if (!record.model || record.outlines) return;
    record.outlines = [];
    record.model.traverse(source => {
      if (!source.isMesh || !source.geometry) return;
      const proxy = source.isSkinnedMesh
        ? new THREE.SkinnedMesh(source.geometry, stencilMaterial)
        : new THREE.Mesh(source.geometry, stencilMaterial);
      if (source.isSkinnedMesh) {
        proxy.bind(source.skeleton, source.bindMatrix);
        proxy.bindMode = source.bindMode;
      }
      if (source.morphTargetInfluences) proxy.morphTargetInfluences = source.morphTargetInfluences;
      proxy.userData.source = source;
      proxy.matrixAutoUpdate = false;
      proxy.frustumCulled = false;
      proxy.visible = false;
      record.outlines.push({ source, proxy });
    });
    records.add(record);
  }

  function detachProxies(record) {
    for (const { proxy } of record.outlines || []) {
      proxy.parent?.remove(proxy);
      proxy.visible = false;
    }
  }

  function update(record, selected, showActive) {
    if (!stencilSupported) return false;
    const kind = selected ? 1 : showActive && hasActivePropActions(record.prop) ? 2 : 0;
    if (kind && !record.outlines) attach(record);
    if (kind && !record.outlines?.length) return false;
    if ((record.outlineKind || 0) === kind) return false;
    record.outlineKind = kind;
    detachProxies(record);
    if (!kind) return true;
    const scene = kind === 1 ? selectedScene : activeScene;
    for (const { proxy } of record.outlines || []) {
      proxy.visible = true;
      scene.add(proxy);
    }
    return true;
  }

  function remove(record) {
    detachProxies(record);
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
  }

  function syncProxyTransforms(scene) {
    for (const proxy of scene.children) {
      const source = proxy.userData.source;
      let visible = source.visible;
      for (let parent = source.parent; visible && parent; parent = parent.parent) visible = parent.visible;
      proxy.visible = visible;
      if (!visible) continue;
      proxy.matrix.copy(source.matrixWorld);
      proxy.matrixWorld.copy(source.matrixWorld);
      proxy.matrixWorldNeedsUpdate = false;
    }
  }

  function drawMask(scene) {
    if (!scene.children.length) return false;
    scene.overrideMaterial = stencilMaterial;
    renderer.render(scene, camera);
    scene.overrideMaterial = null;
    lastPasses += 1;
    return true;
  }

  function drawHull(scene, style) {
    hullMaterial.uniforms.width.value = style.width;
    hullMaterial.uniforms.opacity.value = style.opacity;
    hullMaterial.uniforms.color.value.setRGB(...style.color);
    scene.overrideMaterial = hullMaterial;
    renderer.render(scene, camera);
    scene.overrideMaterial = null;
    lastPasses += 1;
  }

  function render() {
    lastPasses = 0;
    if (!stencilSupported || (!activeScene.children.length && !selectedScene.children.length)) return;
    syncProxyTransforms(activeScene);
    syncProxyTransforms(selectedScene);
    const previousAutoClear = renderer.autoClear;
    renderer.autoClear = false;
    if (activeScene.children.length) {
      renderer.clearStencil();
      if (drawMask(activeScene)) drawHull(activeScene, ACTIVE_STYLE);
    }
    if (selectedScene.children.length) {
      renderer.clearStencil();
      if (drawMask(selectedScene)) {
        for (const style of SELECTED_STYLES) drawHull(selectedScene, style);
      }
    }
    renderer.autoClear = previousAutoClear;
  }

  function dispose() {
    for (const record of [...records]) remove(record);
    stencilMaterial.dispose();
    hullMaterial.dispose();
  }

  function diagnostics() {
    return {
      supported: stencilSupported,
      active: activeScene.children.length,
      selected: selectedScene.children.length,
      passes: lastPasses,
    };
  }

  return { update, remove, resize, render, diagnostics, dispose };
}
