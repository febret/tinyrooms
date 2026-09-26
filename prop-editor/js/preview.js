import * as THREE from "three";
import { GLTFLoader } from "/app/vendor/three/examples/jsm/loaders/GLTFLoader.js";
import { disposeBoardTree } from "/app/js/board-helpers.js";
import { createViewerStage } from "/app/js/viewer-stage.js";
import { createPropEffects } from "/app/js/prop-effects.js";

const loader = new GLTFLoader();
const textureLoader = new THREE.TextureLoader();

function effectSignature(effectSets, activeEffect) {
  try {
    return JSON.stringify([effectSets, activeEffect]);
  } catch {
    return "";
  }
}

/**
 * Full-bleed model preview for the Prop Editor.
 *
 * Renders the selected prop's model with its active effect set (transform,
 * material, and particle layers), matching how the room board renders effects.
 * `setProp` is idempotent: it only rebuilds when the model, scale, or effect
 * signature changes, so it is safe to call on every editor render.
 */
export function createPreviewViewer({ canvas }) {
  const stage = createViewerStage({ canvas, interactive: true });

  let disposed = false;
  let frame = null;
  let last = 0;
  let signature = "";
  let host = null;
  let visual = null;
  let effects = null;
  let modelScenes = [];

  function tick(now) {
    const delta = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    effects?.update(delta);
    stage.renderFrame(delta, false);
    frame = requestAnimationFrame(tick);
  }

  function start() {
    if (frame !== null) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  }

  function clear() {
    effects?.dispose();
    effects = null;
    if (host) {
      stage.pivot.remove(host);
      disposeBoardTree([host, ...modelScenes]);
    }
    host = null;
    visual = null;
    modelScenes = [];
    delete canvas.dataset.modelReady;
    delete canvas.dataset.modelError;
    canvas.dataset.fxCount = "0";
  }

  function pixelScale() {
    return stage.renderer.domElement.height / (2 * Math.tan((stage.camera.fov * Math.PI / 180) / 2));
  }

  function setProp({ modelUrl = "", scale = 1, effectSets = {}, activeEffect = null }) {
    const key = `${modelUrl}|${scale}|${effectSignature(effectSets, activeEffect)}`;
    if (key === signature) return;
    signature = key;
    clear();
    if (!modelUrl) return;
    loader.load(modelUrl, gltf => {
      if (disposed || key !== signature) {
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        return;
      }
      const model = gltf.scene;
      const bounds = new THREE.Box3().setFromObject(model);
      if (bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray()].every(Number.isFinite)) {
        disposeBoardTree(gltf.scenes || [model]);
        canvas.dataset.modelError = "true";
        return;
      }
      const size = bounds.getSize(new THREE.Vector3());
      const center = bounds.getCenter(new THREE.Vector3());
      host = new THREE.Group();
      host.scale.setScalar(scale);
      visual = new THREE.Group();
      visual.position.set(-center.x, -bounds.min.y, -center.z);
      visual.add(model);
      model.traverse(node => {
        if (node.isMesh) node.castShadow = node.receiveShadow = false;
      });
      host.add(visual);
      stage.pivot.add(host);
      modelScenes = gltf.scenes || [model];
      stage.addDisposable(...modelScenes);
      stage.frame(Math.max(size.x, size.z, 0.5) * scale, Math.max(size.y, 0.5) * scale);
      stage.resize();
      effects = createPropEffects({
        group: host,
        visual,
        model,
        bounds,
        effectSets,
        activeEffect,
        reducedMotion: false,
        textureLoader,
        pixelScale,
      });
      canvas.dataset.fxCount = String(effects?.activeCount || 0);
      canvas.dataset.modelReady = "true";
      stage.renderFrame(0, false);
      start();
    }, undefined, () => {
      if (key !== signature) return;
      canvas.dataset.modelError = "true";
    });
  }

  start();

  return {
    setProp,
    dispose() {
      if (disposed) return;
      disposed = true;
      if (frame !== null) cancelAnimationFrame(frame);
      frame = null;
      clear();
      stage.dispose();
    },
  };
}
