import * as THREE from "three";
import { GLTFLoader } from "../vendor/three/examples/jsm/loaders/GLTFLoader.js";
import { disposeBoardTree } from "./board-helpers.js";
import { createViewerStage } from "./viewer-stage.js";

const loader = new GLTFLoader();

/** Create one small WebGL model viewer bound to a canvas. */
function createModelViewer({ canvas, modelUrl, scale, interactive, reducedMotion }) {
  const stage = createViewerStage({ canvas, interactive });

  let disposed = false;
  let modelScenes = [];

  function loadModel() {
    loader.load(modelUrl, gltf => {
      if (disposed) {
        disposeBoardTree(gltf.scenes || [gltf.scene]);
        return;
      }
      const model = gltf.scene;
      const bounds = new THREE.Box3().setFromObject(model);
      if (bounds.isEmpty()) {
        disposeBoardTree(gltf.scenes || [model]);
        return;
      }
      const size = bounds.getSize(new THREE.Vector3()).multiplyScalar(scale);
      const displayWidth = Math.max(size.x, size.z, 0.5);
      const displayHeight = Math.max(size.y, 0.5);
      const center = bounds.getCenter(new THREE.Vector3());
      const visual = new THREE.Group();
      visual.scale.setScalar(scale);
      visual.position.set(-center.x * scale, -bounds.min.y * scale, -center.z * scale);
      visual.add(model);
      model.traverse(node => {
        if (node.isMesh) node.castShadow = node.receiveShadow = false;
      });
      stage.pivot.add(visual);
      modelScenes = gltf.scenes || [model];
      stage.addDisposable(...modelScenes);
      stage.frame(displayWidth, displayHeight);
      stage.resize();
      canvas.dataset.modelReady = "true";
      stage.renderFrame(0, false);
    }, undefined, () => {
      canvas.dataset.modelError = "true";
    });
  }

  loadModel();

  return {
    modelUrl,
    scale,
    render(delta) {
      stage.renderFrame(delta, !interactive && !reducedMotion);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      stage.dispose();
    },
  };
}

/**
 * Keep WebGL model viewers in sync with canvases carrying `data-prop-model`.
 * One shared animation frame drives every mounted viewer.
 */
export function createPropViewerManager() {
  const viewers = new Map();
  let frame = null;
  let last = 0;

  function tick(now) {
    const delta = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    for (const viewer of viewers.values()) viewer.render(delta);
    frame = requestAnimationFrame(tick);
  }

  function start() {
    if (frame !== null) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  }

  function stopIfEmpty() {
    if (viewers.size === 0 && frame !== null) {
      cancelAnimationFrame(frame);
      frame = null;
    }
  }

  function sync(root, reducedMotion) {
    const canvases = [...root.querySelectorAll("canvas[data-prop-model]")];
    // Drop viewers whose canvas left the DOM (views closed or replaced).
    for (const [canvas, viewer] of viewers) {
      if (!canvas.isConnected) {
        viewer.dispose();
        viewers.delete(canvas);
      }
    }
    for (const canvas of canvases) {
      const modelUrl = canvas.dataset.propModel;
      const scale = Number(canvas.dataset.propScale) || 1;
      const existing = viewers.get(canvas);
      if (existing && existing.modelUrl === modelUrl && existing.scale === scale) continue;
      existing?.dispose();
      viewers.set(canvas, createModelViewer({
        canvas,
        modelUrl,
        scale,
        interactive: canvas.dataset.propInteractive === "true",
        reducedMotion: Boolean(reducedMotion),
      }));
    }
    if (viewers.size) start();
    else stopIfEmpty();
  }

  function dispose() {
    for (const viewer of viewers.values()) viewer.dispose();
    viewers.clear();
    stopIfEmpty();
  }

  return { sync, dispose };
}
