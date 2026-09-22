import * as THREE from "three";
import { OrbitControls } from "../vendor/three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "../vendor/three/examples/jsm/loaders/GLTFLoader.js";
import { disposeBoardTree } from "./board-helpers.js";

const loader = new GLTFLoader();
const AUTO_ROTATION_SPEED = 0.6;

/** Create one small WebGL model viewer bound to a canvas. */
function createModelViewer({ canvas, modelUrl, scale, interactive, reducedMotion }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 200);
  const pivot = new THREE.Group();
  scene.add(pivot);
  scene.add(new THREE.HemisphereLight("#fff2d5", "#496e69", 1.5));
  const key = new THREE.DirectionalLight("#fff4de", 1.7);
  key.position.set(4, 7, 6);
  scene.add(key);
  const fill = new THREE.DirectionalLight("#bcd9ff", 0.7);
  fill.position.set(-5, 3, -4);
  scene.add(fill);

  let controls = null;
  if (interactive) {
    controls = new OrbitControls(camera, canvas);
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
    controls.minDistance = 1.4;
    controls.maxDistance = 14;
  }

  let disposed = false;
  let modelScenes = [];
  let displayWidth = 2;
  let displayHeight = 1.8;

  function frameObject() {
    const center = displayHeight * 0.5;
    const radius = Math.max(displayWidth, displayHeight, 0.5);
    camera.position.set(radius * 1.05, center + displayHeight * 0.35, radius * 1.5);
    camera.lookAt(0, center, 0);
    if (controls) {
      controls.target.set(0, center, 0);
      controls.minDistance = radius * 0.7;
      controls.maxDistance = radius * 6;
      controls.update();
    }
  }

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
      displayWidth = Math.max(size.x, size.z, 0.5);
      displayHeight = Math.max(size.y, 0.5);
      const center = bounds.getCenter(new THREE.Vector3());
      const visual = new THREE.Group();
      visual.scale.setScalar(scale);
      visual.position.set(-center.x * scale, -bounds.min.y * scale, -center.z * scale);
      visual.add(model);
      model.traverse(node => {
        if (node.isMesh) node.castShadow = node.receiveShadow = false;
      });
      pivot.add(visual);
      modelScenes = gltf.scenes || [model];
      frameObject();
      resize();
      canvas.dataset.modelReady = "true";
      renderer.render(scene, camera);
    }, undefined, () => {
      canvas.dataset.modelError = "true";
    });
  }

  function resize() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();
  loadModel();

  return {
    modelUrl,
    scale,
    render(delta) {
      if (disposed) return;
      if (!interactive && !reducedMotion) pivot.rotation.y += delta * AUTO_ROTATION_SPEED;
      else if (interactive) controls?.update();
      renderer.render(scene, camera);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      observer.disconnect();
      controls?.dispose();
      disposeBoardTree([pivot, ...modelScenes]);
      renderer.dispose();
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
