import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  BACK_PARTS,
  BASE_BODY_FILE,
  BODY_PARTS,
  defaultDesign,
  EYES_PARTS,
  FACE_PARTS,
  HAIR_PARTS,
  MOUTH_PARTS,
  resolveLayers,
  SHOE_PARTS,
} from "../../client/activities/sticker-designer/parts.js";

const here = dirname(fileURLToPath(import.meta.url));
const partsDir = join(here, "..", "..", "client", "activities", "sticker-designer", "parts");

const PART_SETS = [BODY_PARTS, HAIR_PARTS, SHOE_PARTS, BACK_PARTS, FACE_PARTS, EYES_PARTS, MOUTH_PARTS];

test("every referenced sticker part exists and uses the shared canvas", async () => {
  const files = new Set();
  for (const parts of PART_SETS) {
    for (const part of parts) {
      if (part.file) files.add(part.file);
      if (part.back) files.add(part.back);
      if (part.front) files.add(part.front);
    }
  }
  files.add(BASE_BODY_FILE);
  const available = new Set(await readdir(partsDir));
  for (const file of files) {
    assert.ok(available.has(file), `missing sticker part ${file}`);
    const markup = await readFile(join(partsDir, file), "utf8");
    assert.match(markup, /<svg[^>]*width="200"[^>]*height="220"/, `${file} must use the 200x220 canvas`);
    assert.match(markup, /viewBox="0 0 200 220"/, `${file} must use the shared viewBox`);
  }
});

test("sticker parts only reference known color tokens", async () => {
  const colors = defaultDesign().colors;
  const known = new Set(Object.keys(colors));
  const files = (await readdir(partsDir)).filter(file => file.endsWith(".svg"));
  for (const file of files) {
    const markup = await readFile(join(partsDir, file), "utf8");
    for (const match of markup.matchAll(/\{\{(\w+)\}\}/g)) {
      assert.ok(known.has(match[1]), `${file} references unknown color token {{${match[1]}}}`);
    }
  }
});

test("face with painterly detail carries an explicit dark palette color", () => {
  assert.equal(typeof defaultDesign().colors.faceDark, "string");
  assert.match(defaultDesign().colors.faceDark, /^#[0-9a-f]{6}$/i);
  const bandana = FACE_PARTS.find(part => part.id === "face-bandana");
  assert.ok(bandana);
  assert.equal(bandana.layer, undefined);
});

test("layer order keeps clothing, face details, hair and glasses stacked correctly", () => {
  const design = {
    ...defaultDesign(),
    body: "body-hoodie",
    hair: "hair-short",
    shoes: "shoes-sneakers",
    back: "back-pack",
    face: "face-glasses",
    eyes: "eyes-round",
    mouth: "mouth-smile",
  };
  const layers = resolveLayers(design);
  const index = file => layers.indexOf(file);
  assert.ok(index(BASE_BODY_FILE) < index("body-hoodie.svg"));
  assert.ok(index("body-hoodie.svg") < index("back-pack-front.svg"));
  assert.ok(index("back-pack-front.svg") < index("shoes-sneakers.svg"));
  assert.ok(index("shoes-sneakers.svg") < index("eyes-round.svg"));
  assert.ok(index("eyes-round.svg") < index("mouth-smile.svg"));
  assert.equal(layers.at(-1), "face-glasses.svg");
});

test("under-face parts render before eyes and over-face parts render after hair", () => {
  const beard = resolveLayers({ ...defaultDesign(), face: "face-beard" });
  const glasses = resolveLayers({ ...defaultDesign(), face: "face-glasses" });
  assert.ok(beard.indexOf("face-beard.svg") < beard.indexOf("eyes-dots.svg"));
  assert.ok(glasses.indexOf("face-glasses.svg") > glasses.indexOf("hair-short.svg"));
  assert.ok(beard.includes(BASE_BODY_FILE));
});
