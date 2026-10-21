import * as THREE from "three";
import { OrbitControls } from "../vendor/three/examples/jsm/controls/OrbitControls.js";
import { disposeBoardTree } from "./board-helpers.js";

const AUTO_ROTATION_SPEED = 0.6;

/**
 * Shared WebGL stage for the small inspectors: renderer, camera, lights, optional
 * orbit controls, and resize handling. Callers add content to `pivot`, frame it with
 * `frame`, and dispose it through the returned stage so GPU resources are released.
 */
export function createViewerStage({ canvas, interactive }) {
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
  }

  let disposed = false;
  let extraRoots = [];

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

  return {
    scene,
    camera,
    pivot,
    controls,
    renderer,
    frame,
    resize,
    /** Own extra GPU roots (e.g. loaded GLTF scenes) that the pivot tree does not reach. */
    addDisposable(...roots) {
      extraRoots = extraRoots.concat(roots);
    },
    renderFrame(delta, autoRotate = false) {
      if (disposed) return;
      if (autoRotate) pivot.rotation.y += delta * AUTO_ROTATION_SPEED;
      else controls?.update();
      renderer.render(scene, camera);
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      observer.disconnect();
      controls?.dispose();
      disposeBoardTree([pivot, ...extraRoots]);
      renderer.dispose();
    },
  };
}
