import * as THREE from "three";
import { FontLoader } from "../vendor/three/examples/jsm/loaders/FontLoader.js";
import { TextGeometry } from "../vendor/three/examples/jsm/geometries/TextGeometry.js";
import { withBase } from "./base-path.js";

const FONT_ROOT = "/app/vendor/three/examples/fonts";
export const TEXT_FONTS = Object.freeze({
  sans: Object.freeze({ label: "Sans", url: `${FONT_ROOT}/helvetiker_regular.typeface.json` }),
  serif: Object.freeze({ label: "Serif", url: `${FONT_ROOT}/optimer_regular.typeface.json` }),
  mono: Object.freeze({ label: "Display", url: `${FONT_ROOT}/gentilis_regular.typeface.json` }),
});

const fontLoader = new FontLoader();
const fonts = new Map();

/** Text props never need a GLTF URL, including while their font is loading. */
export function isTextProp(prop) {
  return prop.renderKind === "text" || prop.render_kind === "text" || prop.propId === "builtin:text";
}

/** Cache only font promises/data; every rendered prop owns its geometry and material. */
export function loadTextFont(fontId = "sans") {
  const id = Object.prototype.hasOwnProperty.call(TEXT_FONTS, fontId) ? fontId : "sans";
  if (!fonts.has(id)) {
    const pending = fontLoader.loadAsync(withBase(TEXT_FONTS[id].url)).catch(error => {
      fonts.delete(id);
      throw error;
    });
    fonts.set(id, pending);
  }
  return fonts.get(id);
}

/** Build upright, shallow text centered on X/Z; the board supplies grounding and transforms. */
export async function createTextProp(text = {}, { loadFont = loadTextFont } = {}) {
  const recipe = text || {};
  const font = await loadFont(recipe.font_id || "sans");
  const content = typeof recipe.content === "string" ? recipe.content : "Text";
  const rendered = [...content.normalize("NFC").replace(/\r\n?/g, "\n")]
    .filter(character => character === "\n" || Object.prototype.hasOwnProperty.call(font.data.glyphs, character)).join("");
  const geometry = new TextGeometry(rendered, {
    font, size: 0.6, depth: 0.06, curveSegments: 4, steps: 1, bevelEnabled: false,
  });
  // An all-missing inscription is invisible, but still has finite prop bounds.
  if (!geometry.attributes.position.count) geometry.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0], 3));
  geometry.computeBoundingBox();
  if (!geometry.boundingBox.isEmpty()) {
    const center = geometry.boundingBox.getCenter(new THREE.Vector3());
    geometry.translate(-center.x, 0, -center.z);
  }
  const material = new THREE.MeshStandardMaterial({
    color: /^#[0-9a-f]{6}$/i.test(recipe.color) ? recipe.color : "#ffffff",
    roughness: 0.75,
  });
  const mesh = new THREE.Mesh(geometry, material);
  mesh.castShadow = mesh.receiveShadow = true;
  return mesh;
}
