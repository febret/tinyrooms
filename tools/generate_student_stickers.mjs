// Generate random peep sticker images for Scammon Academia students.
//
// Reuses the sticker designer's own part catalog and randomizer
// (activities/sticker-designer/parts.js) to compose stacked, recolored SVG
// layers into standalone avatar files under the world's peeps directory.
//
// Usage: node tools/generate_student_stickers.mjs [count]

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { randomDesign, resolveLayers } from "../activities/sticker-designer/parts.js";

const here = dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = join(here, "..", "worlds", "scammon-academia", "peeps");
const PARTS_DIR = join(here, "..", "activities", "sticker-designer", "parts");
const COUNT = Number.parseInt(process.argv[2] || "40", 10);

const partCache = new Map();

async function partText(file) {
  if (!partCache.has(file)) {
    partCache.set(file, await readFile(join(PARTS_DIR, file), "utf8"));
  }
  return partCache.get(file);
}

function paint(svgText, colors) {
  return svgText.replace(/\{\{(\w+)\}\}/g, (_match, key) => colors[key] || "#000000");
}

function innerSvg(svgText) {
  const match = /<svg[^>]*>([\s\S]*?)<\/svg>/i.exec(svgText);
  return match ? match[1] : svgText;
}

async function compose(design) {
  const layers = resolveLayers(design);
  const pieces = [];
  for (const file of layers) {
    pieces.push(`<g>${innerSvg(paint(await partText(file), design.colors))}</g>`);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="220" viewBox="0 0 200 220">${pieces.join("")}</svg>`;
}

await mkdir(OUTPUT_DIR, { recursive: true });
for (let index = 1; index <= COUNT; index += 1) {
  const design = randomDesign();
  const svg = await compose(design);
  const name = `student-sticker-${String(index).padStart(2, "0")}.svg`;
  await writeFile(join(OUTPUT_DIR, name), svg, "utf8");
}
console.log(`wrote ${COUNT} student sticker avatars to ${OUTPUT_DIR}`);
