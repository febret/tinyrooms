import * as THREE from "three";
import { OrbitControls } from "../vendor/three/examples/jsm/controls/OrbitControls.js";
import { disposeBoardTree } from "./board/board-helpers.js";

const AUTO_ROTATION_SPEED = 0.6;
const AUTO_ROTATION_INTERVAL = 1 / 30;

/**
 * Shared WebGL stage for the small inspectors: renderer, camera, lights, optional
 * orbit controls, and resize handling. Callers add content to `pivot`, frame it with
 * `frame`, and dispose it through the returned stage so GPU resources are released.
 */
export function createViewerStage({ canvas, interactive, lighting = {} }) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 200);
  const pivot = new THREE.Group();
  scene.add(pivot);
  scene.add(new THREE.HemisphereLight("#fff2d5", "#496e69", lighting.hemisphere ?? 1.5));
  const key = new THREE.DirectionalLight("#fff4de", lighting.key ?? 1.7);
  key.position.set(4, 7, 6);
  scene.add(key);
  const fill = new THREE.DirectionalLight("#bcd9ff", lighting.fill ?? 0.7);
  fill.position.set(-5, 3, -4);
  scene.add(fill);

  let controls = null;
  if (interactive) {
    controls = new OrbitControls(camera, canvas);
    controls.enablePan = false;
    controls.enableDamping = true;
    controls.dampingFactor = 0.12;
  }

  let disposed = false;
  let extraRoots = [];
  let dirty = true;
  let autoElapsed = 0;

  function invalidate() {
    dirty = true;
  }

  function frame(displayWidth, displayHeight) {
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
    invalidate();
  }

  function resize() {
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    invalidate();
  }

  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();
  controls?.addEventListener("change", invalidate);

  return {
    scene,
    camera,
    pivot,
    controls,
    renderer,
    frame,
    resize,
    invalidate,
    /** Own extra GPU roots (e.g. loaded GLTF scenes) that the pivot tree does not reach. */
    addDisposable(...roots) {
      extraRoots = extraRoots.concat(roots);
    },
    /**
     * Draw only when something changed. Auto-rotating viewers step at 30fps so
     * a small preview never runs a full 60fps WebGL pass in the background.
     * A zero delta forces a draw, which loaders use after binding a texture.
     */
    renderFrame(delta, autoRotate = false) {
      if (disposed) return false;
      const force = !(delta > 0);
      if (autoRotate && !force) {
        autoElapsed += delta;
        if (autoElapsed < AUTO_ROTATION_INTERVAL) return false;
        pivot.rotation.y += autoElapsed * AUTO_ROTATION_SPEED;
        autoElapsed = 0;
        dirty = true;
      } else if (!autoRotate) {
        autoElapsed = 0;
        controls?.update();
      }
      if (!dirty && !force) return false;
      dirty = false;
      renderer.render(scene, camera);
      return true;
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      controls?.removeEventListener("change", invalidate);
      observer.disconnect();
      controls?.dispose();
      disposeBoardTree([pivot, ...extraRoots]);
      renderer.dispose();
      // dispose() frees GPU objects but keeps the canvas context alive until GC.
      // Preview canvases are replaced often, so release the context immediately
      // rather than letting them accumulate and evict the room board's context.
      renderer.forceContextLoss();
    },
  };
}
