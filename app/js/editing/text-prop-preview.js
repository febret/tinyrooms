import * as THREE from "three";
import { createTextProp } from "../text-props.js";

/** A small on-demand preview, framed around the text rather than a room floor. */
export function createTextPropPreview(canvas, status) {
  let renderer;
  try { renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true }); }
  catch {
    status.textContent = "3D preview is unavailable on this device.";
    return { render() {}, dispose() {} };
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 1000);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x647b86, 2));
  const light = new THREE.DirectionalLight(0xffffff, 2.5);
  light.position.set(-3, 5, 8);
  scene.add(light);
  let mesh, disposed = false, generation = 0;
  const release = model => { model.geometry.dispose(); model.material.dispose(); };
  function draw() {
    if (disposed || !mesh) return;
    const width = Math.max(1, canvas.clientWidth), height = Math.max(1, canvas.clientHeight);
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    const box = new THREE.Box3().setFromObject(mesh);
    const size = box.getSize(new THREE.Vector3());
    const distance = Math.max(size.y, size.x / camera.aspect, 0.3) / (2 * Math.tan(THREE.MathUtils.degToRad(17.5))) * 1.3;
    camera.position.set(0, 0, distance + size.z);
    camera.lookAt(0, 0, 0);
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
  }
  const resize = new ResizeObserver(draw);
  resize.observe(canvas);
  return {
    async render(text) {
      const version = ++generation;
      canvas.dataset.boardReady = "false";
      status.textContent = "Loading preview…";
      try {
        const model = await createTextProp(text);
        if (disposed || version !== generation) { release(model); return; }
        if (mesh) { scene.remove(mesh); release(mesh); }
        mesh = model;
        mesh.geometry.computeBoundingBox();
        const center = mesh.geometry.boundingBox.getCenter(new THREE.Vector3());
        mesh.geometry.translate(0, -center.y, 0);
        mesh.rotation.set(-0.08, -0.18, 0);
        scene.add(mesh);
        draw();
        canvas.dataset.boardReady = "true";
        status.textContent = "";
      } catch {
        if (!disposed && version === generation) status.textContent = "Could not render preview.";
      }
    },
    dispose() {
      disposed = true;
      generation++;
      resize.disconnect();
      if (mesh) release(mesh);
      renderer.dispose();
      renderer.forceContextLoss();
    },
  };
}
