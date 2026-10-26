import * as THREE from "three";
import { GLTFLoader } from "../../app/vendor/three/examples/jsm/loaders/GLTFLoader.js";
import { disposeBoardTree } from "../../app/js/board-helpers.js";
import { createViewerStage } from "../../app/js/viewer-stage.js";

const loader = new GLTFLoader();

/**
 * Full model preview for the Asset Bakery.
 *
 * Auto-loads the selected task's GLB into the shared viewer stage (orbit,
 * auto-rotate turntable, fitted framing). `setModel` is idempotent: it only
 * rebuilds when the URL changes, so it is safe to call on every render.
 */
export function createModelPreview({ canvas, onError }) {
  const stage = createViewerStage({ canvas, interactive: true });

  let disposed = false;
  let frame = null;
  let last = 0;
  let signature = "";
  let host = null;
  let modelScenes = [];
  let generation = 0;

  function tick(now) {
    const delta = Math.min(0.05, Math.max(0, (now - last) / 1000));
    last = now;
    stage.renderFrame(delta, true);
    frame = requestAnimationFrame(tick);
  }

  function start() {
    if (frame !== null) return;
    last = performance.now();
    frame = requestAnimationFrame(tick);
  }

  function clear() {
    if (host) {
      stage.pivot.remove(host);
      disposeBoardTree([host, ...modelScenes]);
    }
    host = null;
    modelScenes = [];
  }

  function setModel(url) {
    const key = String(url || "");
    if (key === signature) return;
    signature = key;
    generation += 1;
    const ticket = generation;
    clear();
    if (!key) return;
    loader.load(
      key,
      gltf => {
        if (disposed || ticket !== generation || key !== signature) {
          disposeBoardTree(gltf.scenes || [gltf.scene]);
          return;
        }
        const model = gltf.scene;
        const bounds = new THREE.Box3().setFromObject(model);
        if (bounds.isEmpty() || ![...bounds.min.toArray(), ...bounds.max.toArray()].every(Number.isFinite)) {
          disposeBoardTree(gltf.scenes || [model]);
          onError?.(new Error("empty model"));
          return;
        }
        const size = bounds.getSize(new THREE.Vector3());
        const center = bounds.getCenter(new THREE.Vector3());
        host = new THREE.Group();
        const visual = new THREE.Group();
        visual.position.set(-center.x, -bounds.min.y, -center.z);
        visual.add(model);
        model.traverse(node => {
          if (node.isMesh) node.castShadow = node.receiveShadow = false;
        });
        host.add(visual);
        stage.pivot.add(host);
        modelScenes = gltf.scenes || [model];
        stage.addDisposable(...modelScenes);
        stage.frame(Math.max(size.x, size.z, 0.5), Math.max(size.y, 0.5));
        stage.resize();
        stage.renderFrame(0, false);
        start();
      },
      undefined,
      () => {
        if (!disposed && ticket === generation) onError?.(new Error("load failed"));
      },
    );
  }

  start();

  return {
    setModel,
    resize() {
      stage.resize();
    },
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

let thumbRenderer = null;
let thumbChain = Promise.resolve();

function thumbRendererFor(size) {
  if (thumbRenderer && thumbRenderer.size === size) return thumbRenderer;
  thumbRenderer?.renderer.dispose();
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight("#fff2d5", "#496e69", 1.5));
  const key = new THREE.DirectionalLight("#fff4de", 1.7);
  key.position.set(4, 7, 6);
  scene.add(key);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 200);
  thumbRenderer = { canvas, renderer, scene, camera, size };
  return thumbRenderer;
}

/**
 * Render a small square thumbnail data URL for a GLB. Calls are serialized
 * through a single shared renderer so scrolling a long task list cannot
 * stampede the GPU or the network.
 */
export function renderModelThumb(url, { size = 112 } = {}) {
  const key = String(url || "");
  const run = thumbChain.then(
    () =>
      new Promise((resolve, reject) => {
        if (!key) {
          reject(new Error("no url"));
          return;
        }
        loader.load(
          key,
          gltf => {
            try {
              const { canvas, renderer, scene, camera } = thumbRendererFor(size);
              const model = gltf.scene;
              const bounds = new THREE.Box3().setFromObject(model);
              if (bounds.isEmpty()) {
                disposeBoardTree(gltf.scenes || [model]);
                reject(new Error("empty model"));
                return;
              }
              const sizing = bounds.getSize(new THREE.Vector3());
              const center = bounds.getCenter(new THREE.Vector3());
              const radius = Math.max(sizing.x, sizing.y, sizing.z, 0.5);
              const holder = new THREE.Group();
              holder.position.set(-center.x, -center.y, -center.z);
              holder.add(model);
              scene.add(holder);
              camera.position.set(radius * 1.05, radius * 0.9, radius * 1.5);
              camera.lookAt(0, 0, 0);
              renderer.setSize(size, size, false);
              renderer.render(scene, camera);
              const dataUrl = canvas.toDataURL("image/png");
              scene.remove(holder);
              disposeBoardTree(gltf.scenes || [model]);
              resolve(dataUrl);
            } catch (error) {
              reject(error);
            }
          },
          undefined,
          () => reject(new Error("load failed")),
        );
      }),
  );
  // Keep the chain alive across individual failures.
  thumbChain = run.catch(() => {});
  return run;
}
