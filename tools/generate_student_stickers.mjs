// Generate deterministic Scammon Academia student stickers.
//
// Students are grouped into last-name families that share a palette, hair and
// signature accessory. Each student's outfit, shoes, eyes and extras also
// encode their favorite subjects and classroom trait. The generated roster is
// written to worlds/scammon-academia/peeps/students.json; the classrooms mod
// loads the same manifest so every avatar matches its student's attributes.

import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  hydrateDesign,
  partEntry,
  resolveLayers,
} from "../client/activities/sticker-designer/parts.js";

const here = dirname(fileURLToPath(import.meta.url));
const WORLD_DIR = join(here, "..", "worlds", "scammon-academia");
const OUTPUT_DIR = join(WORLD_DIR, "peeps");
const PARTS_DIR = join(here, "..", "client", "activities", "sticker-designer", "parts");
const MANIFEST_PATH = join(OUTPUT_DIR, "students.json");
const ROSTER_VERSION = 2;
const STUDENTS_PER_GRADE = 15;
const GRADES = 8;

const FIRST_NAMES = [
  "Jack", "Jill", "Lisa", "Tom", "Luca", "Jimmy", "Lana", "Rose",
  "Blue", "Red", "Gigi", "Toto", "Tato", "Robert",
];
const LAST_NAMES = [
  "Pesto", "Spaghetto", "Toto", "Tato", "Crickets", "Hearts",
  "Malinki", "BamBam", "Obert",
];
const SUBJECTS = [
  "reading", "writing", "math", "history", "geography",
  "chemistry", "tech", "sport", "biology",
];
const TRAITS = [
  "superfocused", "head-in-the-clouds", "extra-gas", "bad-sleeper", "runs-hot",
];

// Each family keeps a recognizable palette, hair range and signature extra.
const FAMILIES = {
  Pesto: {
    primary: ["#3f6b3f", "#294a29"],
    secondary: ["#2f4470", "#1d2d4d"],
    hair: [["#2b2b2b", "#141414"], ["#6b3f22", "#482814"]],
    skin: [["#fbe9d7", "#e4c6a8"], ["#f4d3b0", "#d6ab84"], ["#e6b885", "#c3905e"]],
    accent: ["#c79a3a", "#936f24"],
    face: ["#3f6b3f", "#294a29"],
    hairs: ["hair-short", "hair-sideswept", "hair-bowl"],
    shoes: ["shoes-flats", "shoes-sneakers"],
    faceHint: "face-glasses",
  },
  Spaghetto: {
    primary: ["#a63f3f", "#772828"],
    secondary: ["#d9cbaa", "#b0a07c"],
    hair: [["#6b3f22", "#482814"], ["#c15a2a", "#8f3d1a"]],
    skin: [["#f4d3b0", "#d6ab84"], ["#e6b885", "#c3905e"], ["#c78e5a", "#9f6c3d"]],
    accent: ["#d9cbaa", "#b0a07c"],
    face: ["#6b3f22", "#482814"],
    hairs: ["hair-messy", "hair-ponytail", "hair-bob"],
    shoes: ["shoes-sneakers", "shoes-cleats"],
    faceHint: "face-freckles",
  },
  Toto: {
    primary: ["#2f8f86", "#1f6560"],
    secondary: ["#3a3a42", "#232329"],
    hair: [["#2b2b2b", "#141414"], ["#3f5fa0", "#2a4272"]],
    skin: [["#e6b885", "#c3905e"], ["#c78e5a", "#9f6c3d"], ["#a66a3c", "#7e4c28"]],
    accent: ["#f4c430", "#b58a12"],
    face: ["#2f8f8f", "#1f6666"],
    hairs: ["hair-topknot", "hair-bowl", "hair-mohawk"],
    shoes: ["shoes-sneakers", "shoes-platforms"],
    faceHint: "face-goggles",
  },
  Tato: {
    primary: ["#6a3f6a", "#482848"],
    secondary: ["#d06a4f", "#9b4a35"],
    hair: [["#7a4b8f", "#563364"], ["#2b2b2b", "#141414"]],
    skin: [["#c78e5a", "#9f6c3d"], ["#a66a3c", "#7e4c28"], ["#7a4a2b", "#59341d"]],
    accent: ["#d06a4f", "#9b4a35"],
    face: ["#8a5ac0", "#5f3a8a"],
    hairs: ["hair-emo", "hair-mohawk", "hair-buns"],
    shoes: ["shoes-boots", "shoes-rollerskates"],
    faceHint: "face-sticker",
  },
  Crickets: {
    primary: ["#4f8a4a", "#356330"],
    secondary: ["#6b6b2f", "#4a4a1f"],
    hair: [["#2b2b2b", "#141414"], ["#6b3f22", "#482814"]],
    skin: [["#a66a3c", "#7e4c28"], ["#7a4a2b", "#59341d"], ["#c78e5a", "#9f6c3d"]],
    accent: ["#5ab08a", "#3a7f60"],
    face: ["#4f8a4a", "#356330"],
    hairs: ["hair-curly", "hair-afro", "hair-braids"],
    shoes: ["shoes-boots", "shoes-sandals"],
    faceHint: "face-freckles",
  },
  Hearts: {
    primary: ["#d06a7a", "#9b3f52"],
    secondary: ["#6a3f6a", "#482848"],
    hair: [["#8a4b2a", "#5f321f"], ["#2b2b2b", "#141414"], ["#d9b25a", "#a88231"]],
    skin: [["#fbe9d7", "#e4c6a8"], ["#f4d3b0", "#d6ab84"], ["#e6b885", "#c3905e"]],
    accent: ["#e8e4da", "#c2bcae"],
    face: ["#e07a9a", "#b4526f"],
    hairs: ["hair-long", "hair-buns", "hair-braids"],
    shoes: ["shoes-flats", "shoes-slippers"],
    faceHint: "face-blush",
  },
  Malinki: {
    primary: ["#a63f7a", "#742750"],
    secondary: ["#3a3a42", "#232329"],
    hair: [["#2b2b2b", "#141414"], ["#e07a9a", "#b4526f"]],
    skin: [["#fbe9d7", "#e4c6a8"], ["#e6b885", "#c3905e"], ["#a66a3c", "#7e4c28"]],
    accent: ["#e8e4da", "#c2bcae"],
    face: ["#7a4b8f", "#563364"],
    hairs: ["hair-long", "hair-bob", "hair-emo"],
    shoes: ["shoes-boots", "shoes-heels"],
    faceHint: "face-shades",
  },
  BamBam: {
    primary: ["#3f5fa0", "#2a4272"],
    secondary: ["#d06a4f", "#9b4a35"],
    hair: [["#2b2b2b", "#141414"], ["#d9b25a", "#a88231"]],
    skin: [["#e6b885", "#c3905e"], ["#c78e5a", "#9f6c3d"], ["#a66a3c", "#7e4c28"]],
    accent: ["#e07a3f", "#a84f1f"],
    face: ["#3f5fa0", "#2a4272"],
    hairs: ["hair-mohawk", "hair-short", "hair-messy"],
    shoes: ["shoes-cleats", "shoes-sneakers"],
    faceHint: "face-headband",
  },
  Obert: {
    primary: ["#2f4470", "#1d2d4d"],
    secondary: ["#3a3a42", "#232329"],
    hair: [["#6b3f22", "#482814"], ["#2b2b2b", "#141414"], ["#e8e4da", "#c2bcae"]],
    skin: [["#fbe9d7", "#e4c6a8"], ["#f4d3b0", "#d6ab84"], ["#e6b885", "#c3905e"]],
    accent: ["#c79a3a", "#936f24"],
    face: ["#3f5fa0", "#2a4272"],
    hairs: ["hair-sideswept", "hair-bowl", "hair-viking"],
    shoes: ["shoes-boots", "shoes-flats"],
    faceHint: "face-monocle",
  },
};

const SUBJECT_STYLES = {
  reading: {
    body: ["body-sweater", "body-dress"],
    face: ["face-glasses"],
    eyes: ["eyes-round", "eyes-happy"],
    mouth: ["mouth-smile"],
    shoes: ["shoes-flats", "shoes-slippers"],
    back: ["back-pack"],
    accent: ["#c96a4a", "#8e3f2a"],
  },
  writing: {
    body: ["body-hoodie", "body-apron"],
    face: ["face-pencil"],
    eyes: ["eyes-oval", "eyes-round"],
    mouth: ["mouth-smirk"],
    shoes: ["shoes-flats"],
    back: ["back-banner"],
    accent: ["#3f5fa0", "#2a4272"],
  },
  math: {
    body: ["body-labcoat", "body-sweater"],
    face: ["face-monocle", "face-glasses"],
    eyes: ["eyes-squint", "eyes-oval"],
    mouth: ["mouth-line", "mouth-smile"],
    shoes: ["shoes-platforms"],
    back: ["back-none"],
    accent: ["#2f8f86", "#1f6560"],
  },
  history: {
    body: ["body-tux", "body-dress"],
    face: ["face-monocle"],
    eyes: ["eyes-oval", "eyes-round"],
    mouth: ["mouth-smile"],
    shoes: ["shoes-cowboy", "shoes-boots"],
    back: ["back-banner"],
    accent: ["#c79a3a", "#936f24"],
  },
  geography: {
    body: ["body-poncho", "body-raincoat"],
    face: ["face-freckles"],
    eyes: ["eyes-round", "eyes-happy"],
    mouth: ["mouth-grin"],
    shoes: ["shoes-sandals", "shoes-boots"],
    back: ["back-surfboard", "back-balloons"],
    accent: ["#3f8f5f", "#296340"],
  },
  chemistry: {
    body: ["body-labcoat"],
    face: ["face-goggles"],
    eyes: ["eyes-sparkle", "eyes-round"],
    mouth: ["mouth-grin"],
    shoes: ["shoes-sneakers"],
    back: ["back-none"],
    accent: ["#2f8f86", "#1f6560"],
  },
  tech: {
    body: ["body-jumpsuit", "body-hoodie"],
    face: ["face-goggles", "face-glasses"],
    eyes: ["eyes-glow", "eyes-round"],
    mouth: ["mouth-smirk"],
    shoes: ["shoes-sneakers", "shoes-platforms"],
    back: ["back-robotarms", "back-propeller"],
    accent: ["#3f5fa0", "#2a4272"],
  },
  sport: {
    body: ["body-sport", "body-tank"],
    face: ["face-headband", "face-bandana"],
    eyes: ["eyes-squint", "eyes-happy"],
    mouth: ["mouth-grin", "mouth-teeth"],
    shoes: ["shoes-cleats", "shoes-sneakers"],
    back: ["back-jetpack", "back-none"],
    accent: ["#e07a3f", "#a84f1f"],
  },
  biology: {
    body: ["body-overalls", "body-apron"],
    face: ["face-freckles"],
    eyes: ["eyes-round", "eyes-happy"],
    mouth: ["mouth-smile"],
    shoes: ["shoes-sandals", "shoes-sneakers"],
    back: ["back-shell", "back-fairy"],
    accent: ["#4f8a4a", "#356330"],
  },
};

const TRAIT_STYLES = {
  superfocused: {
    hair: ["hair-bowl", "hair-sideswept", "hair-short", "hair-topknot"],
    eyes: ["eyes-squint", "eyes-round", "eyes-oval"],
    mouth: ["mouth-line", "mouth-smirk", "mouth-smile"],
    face: ["face-glasses", "face-monocle"],
    shoes: ["shoes-flats", "shoes-sneakers"],
    back: ["back-none", "back-pack"],
  },
  "head-in-the-clouds": {
    hair: ["hair-messy", "hair-curly", "hair-afro", "hair-emo"],
    eyes: ["eyes-starry", "eyes-sparkle", "eyes-happy"],
    mouth: ["mouth-smile", "mouth-grin"],
    face: ["face-blush"],
    shoes: ["shoes-slippers", "shoes-sneakers"],
    back: ["back-balloons", "back-fairy", "back-wings"],
  },
  "extra-gas": {
    hair: ["hair-messy", "hair-mohawk", "hair-short"],
    eyes: ["eyes-wide", "eyes-surprised", "eyes-happy"],
    mouth: ["mouth-grin", "mouth-teeth"],
    face: ["face-sweat"],
    shoes: ["shoes-sneakers", "shoes-rollerskates"],
    back: ["back-jetpack", "back-propeller"],
  },
  "bad-sleeper": {
    body: ["body-onesie"],
    hair: ["hair-messy", "hair-mullet", "hair-emo"],
    eyes: ["eyes-sleepy", "eyes-oval"],
    mouth: ["mouth-yawn", "mouth-blep"],
    face: ["face-tired"],
    shoes: ["shoes-slippers"],
    back: ["back-none"],
  },
  "runs-hot": {
    body: ["body-tank", "body-sport"],
    hair: ["hair-short", "hair-mohawk", "hair-topknot"],
    eyes: ["eyes-angry", "eyes-squint"],
    mouth: ["mouth-frown", "mouth-grimace", "mouth-teeth"],
    face: ["face-sweat"],
    shoes: ["shoes-cleats", "shoes-sneakers"],
    back: ["back-none"],
  },
};

const FACIAL_HAIR = new Set(["face-beard", "face-mustache", "face-goatee"]);

function hashInt(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function makeRng(seed) {
  let state = seed >>> 0 || 1;
  return () => {
    state ^= state << 13;
    state ^= state >>> 17;
    state ^= state << 5;
    return (state >>> 0) / 4294967296;
  };
}

function pick(list, hash) {
  return list[hash % list.length];
}

function normalizePair(pair) {
  return { base: pair[0], dark: pair[1] };
}

function avatarFor(ordinal) {
  return `student-sticker-${String(ordinal).padStart(2, "0")}.svg`;
}

function buildRoster() {
  const combos = [];
  for (const first of FIRST_NAMES) {
    for (const last of LAST_NAMES) combos.push([first, last]);
  }
  const rng = makeRng(hashInt("tinyrooms-scammon-roster-v2"));
  for (let index = combos.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(rng() * (index + 1));
    [combos[index], combos[swap]] = [combos[swap], combos[index]];
  }
  const total = STUDENTS_PER_GRADE * GRADES;
  const students = [];
  for (let index = 0; index < total; index += 1) {
    const [first, last] = combos[index];
    const grade = Math.floor(index / STUDENTS_PER_GRADE) + 1;
    const seat = index % STUDENTS_PER_GRADE;
    const key = `${first}:${last}:${grade}:${seat}`;
    const favorites = [];
    const firstSubject = SUBJECTS[hashInt(`${key}:fav-a`) % SUBJECTS.length];
    let secondSubject = SUBJECTS[hashInt(`${key}:fav-b`) % SUBJECTS.length];
    if (secondSubject === firstSubject) {
      secondSubject = SUBJECTS[(SUBJECTS.indexOf(secondSubject) + 1) % SUBJECTS.length];
    }
    favorites.push(firstSubject, secondSubject);
    const remaining = SUBJECTS.filter(subject => !favorites.includes(subject));
    const tricky = remaining[hashInt(`${key}:tricky`) % remaining.length];
    const traitRoll = hashInt(`${key}:trait`) % 100;
    const trait = traitRoll < 50 ? null : TRAITS[hashInt(`${key}:trait-id`) % TRAITS.length];
    students.push({
      student_id: `student:${grade}:${String(seat).padStart(2, "0")}`,
      grade,
      first_name: first,
      last_name: last,
      favorites,
      tricky,
      trait,
      avatar: avatarFor(index + 1),
    });
  }
  return students;
}

function designFor(student) {
  const family = FAMILIES[student.last_name];
  if (!family) throw new Error(`No family style for ${student.last_name}`);
  const key = `${student.first_name}:${student.last_name}:${student.student_id}`;
  const hash = hashInt(key);
  const primary = SUBJECT_STYLES[student.favorites[0]] || SUBJECT_STYLES.reading;
  const secondary = SUBJECT_STYLES[student.favorites[1]] || SUBJECT_STYLES.math;
  const trait = TRAIT_STYLES[student.trait] || {};
  const skin = normalizePair(pick(family.skin, hashInt(`${key}:skin`)));
  const hair = normalizePair(pick(family.hair, hashInt(`${key}:hair-color`)));
  const familyPrimary = normalizePair(family.primary);
  const familySecondary = normalizePair(family.secondary);
  const familyAccent = normalizePair(family.accent);
  const familyFace = normalizePair(family.face);
  const subjectAccent = normalizePair(primary.accent);

  const body = pick(trait.body || primary.body, hashInt(`${key}:body`));
  const hairStyle = pick(trait.hair || family.hairs, hashInt(`${key}:hair`));
  const eyes = pick(trait.eyes || primary.eyes, hashInt(`${key}:eyes`));
  const mouth = pick(trait.mouth || primary.mouth, hashInt(`${key}:mouth`));
  const shoes = pick(trait.shoes || primary.shoes || family.shoes, hashInt(`${key}:shoes`));
  const back = pick(
    trait.back || primary.back || secondary.back || ["back-none"],
    hashInt(`${key}:back`),
  );

  let face = "face-none";
  if (student.trait === "bad-sleeper" || student.trait === "runs-hot") {
    face = pick(trait.face, hashInt(`${key}:trait-face`));
  } else {
    const subjectFace = primary.face || secondary.face;
    if (subjectFace) face = pick(subjectFace, hashInt(`${key}:face`));
    else if (family.faceHint) face = family.faceHint;
    else if (trait.face) face = pick(trait.face, hashInt(`${key}:trait-face`));
  }

  let facePair = familyFace;
  if (FACIAL_HAIR.has(face)) facePair = hair;
  else if (face === "face-tired" || face === "face-freckles" || face === "face-scar") facePair = skin;
  else if (face === "face-sweat") facePair = { base: "#9edcff", dark: "#4f9fc8" };
  else if (face.startsWith("face-glasses") || face === "face-goggles" || face === "face-shades" || face === "face-monocle") facePair = familyAccent;
  else if (face === "face-blush") facePair = { base: "#e07a7a", dark: "#b45252" };
  else if (
    face.startsWith("face-headband") ||
    face === "face-bandana" ||
    face === "face-mask" ||
    face === "face-sticker" ||
    face === "face-pencil" ||
    face === "face-warpaint"
  ) {
    facePair = subjectAccent;
  }

  const design = hydrateDesign({
    body,
    hair: hairStyle,
    shoes,
    back,
    face,
    eyes,
    mouth,
    colors: {
      skin: skin.base,
      skinDark: skin.dark,
      shirt: familyPrimary.base,
      shirtDark: familyPrimary.dark,
      pants: familySecondary.base,
      pantsDark: familySecondary.dark,
      hair: hair.base,
      hairDark: hair.dark,
      shoes: familySecondary.base,
      shoesDark: familySecondary.dark,
      accent: subjectAccent.base,
      accentDark: subjectAccent.dark,
      face: facePair.base,
      faceDark: facePair.dark,
    },
  });

  for (const slot of ["body", "hair", "shoes", "back", "face", "eyes", "mouth"]) {
    if (!partEntry(slot, design[slot])) throw new Error(`Invalid ${slot} part '${design[slot]}' for ${student.student_id}`);
  }
  return design;
}

const partCache = new Map();

async function partText(file) {
  if (!partCache.has(file)) partCache.set(file, await readFile(join(PARTS_DIR, file), "utf8"));
  return partCache.get(file);
}

function paint(svgText, colors) {
  return svgText.replace(/\{\{(\w+)\}\}/g, (_match, token) => colors[token] || "#000000");
}

function innerSvg(svgText) {
  const match = /<svg[^>]*>([\s\S]*?)<\/svg>/i.exec(svgText);
  return match ? match[1] : svgText;
}

async function compose(design) {
  const pieces = [];
  for (const file of resolveLayers(design)) {
    pieces.push(`<g>${innerSvg(paint(await partText(file), design.colors))}</g>`);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="200" height="220" viewBox="0 0 200 220">${pieces.join("")}</svg>`;
}

await mkdir(OUTPUT_DIR, { recursive: true });
const students = buildRoster();
const manifest = { version: ROSTER_VERSION, students };
await writeFile(MANIFEST_PATH, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
for (const student of students) {
  await writeFile(join(OUTPUT_DIR, student.avatar), await compose(designFor(student)), "utf8");
}
console.log(`wrote ${students.length} student avatars and ${MANIFEST_PATH}`);
