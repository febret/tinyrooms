// The sticker part catalog, palettes, and design recipes.
//
// Every part is an SVG authored on a shared 200x220 canvas so layers stack
// without per-part offsets. Parts reference palette tokens such as {{hair}};
// the composer substitutes the chosen colors before rasterizing.

export const DESIGN_VERSION = 1;

const SKIN = [
  ["#fbe9d7", "#e4c6a8"],
  ["#f4d3b0", "#d6ab84"],
  ["#e6b885", "#c3905e"],
  ["#c78e5a", "#9f6c3d"],
  ["#a66a3c", "#7e4c28"],
  ["#7a4a2b", "#59341d"],
  ["#b9c6cf", "#8fa1ac"],
  ["#d2d2d2", "#a9a9a9"],
];

const HAIR = [
  ["#2b2b2b", "#141414"],
  ["#6b3f22", "#482814"],
  ["#8a4b2a", "#5f321f"],
  ["#d9b25a", "#a88231"],
  ["#c15a2a", "#8f3d1a"],
  ["#b83a3a", "#8a2323"],
  ["#e07a9a", "#b4526f"],
  ["#7a4b8f", "#563364"],
  ["#3f5fa0", "#2a4272"],
  ["#2f8f8f", "#1f6666"],
  ["#4f8a4a", "#356330"],
  ["#e8e4da", "#c2bcae"],
];

const FABRIC = [
  ["#3f5a72", "#2a3f52"],
  ["#2f4470", "#1d2d4d"],
  ["#4f8fc0", "#356a94"],
  ["#2f8f86", "#1f6560"],
  ["#3f6b3f", "#294a29"],
  ["#6b6b2f", "#4a4a1f"],
  ["#a63f3f", "#772828"],
  ["#d06a4f", "#9b4a35"],
  ["#c79a3a", "#936f24"],
  ["#6a3f6a", "#482848"],
  ["#3a3a42", "#232329"],
  ["#d9cbaa", "#b0a07c"],
];

const FACE = [
  ["#e07a7a", "#b45252"],
  ["#e08a5a", "#b45f35"],
  ["#d9b04a", "#a8832a"],
  ["#5ab08a", "#3a7f60"],
  ["#5a9ad0", "#3a6b9a"],
  ["#8a5ac0", "#5f3a8a"],
  ["#2b2b2b", "#161616"],
  ["#efeae0", "#c8c2b4"],
];

export const BODY_PARTS = [
  { id: "body-tee", label: "Tee & Shorts", file: "body-tee.svg" },
  { id: "body-hoodie", label: "Hoodie", file: "body-hoodie.svg" },
  { id: "body-dress", label: "Dress", file: "body-dress.svg" },
  { id: "body-overalls", label: "Overalls", file: "body-overalls.svg" },
];

export const HAIR_PARTS = [
  { id: "hair-short", label: "Short", front: "hair-short.svg", back: "hair-short-back.svg" },
  { id: "hair-long", label: "Long", front: "hair-long.svg", back: "hair-long-back.svg" },
  { id: "hair-bob", label: "Bob", front: "hair-bob.svg", back: "hair-bob-back.svg" },
  { id: "hair-curly", label: "Curly", front: "hair-curly.svg", back: "hair-curly-back.svg" },
  { id: "hair-ponytail", label: "Ponytail", front: "hair-ponytail.svg", back: "hair-ponytail-back.svg" },
  { id: "hair-messy", label: "Messy", front: "hair-messy.svg", back: "hair-messy-back.svg" },
];

export const SHOE_PARTS = [
  { id: "shoes-sneakers", label: "Sneakers", file: "shoes-sneakers.svg" },
  { id: "shoes-boots", label: "Boots", file: "shoes-boots.svg" },
  { id: "shoes-sandals", label: "Sandals", file: "shoes-sandals.svg" },
  { id: "shoes-flats", label: "Flats", file: "shoes-flats.svg" },
];

export const BACK_PARTS = [
  { id: "back-none", label: "None" },
  { id: "back-wings", label: "Wings", file: "back-wings.svg" },
  { id: "back-cape", label: "Cape", file: "back-cape.svg" },
  { id: "back-pack", label: "Backpack", file: "back-pack.svg" },
];

export const FACE_PARTS = [
  { id: "face-none", label: "None" },
  { id: "face-eyes", label: "Eyes", file: "face-eyes.svg" },
  { id: "face-blush", label: "Blush", file: "face-blush.svg" },
  { id: "face-glasses", label: "Glasses", file: "face-glasses.svg" },
  { id: "face-mask", label: "Mask", file: "face-mask.svg" },
];

export const CATEGORIES = [
  {
    id: "body",
    label: "Body",
    partSlot: "body",
    parts: BODY_PARTS,
    palettes: [
      { slot: "skin", label: "Skin", palette: SKIN },
      { slot: "shirt", label: "Top", palette: FABRIC },
      { slot: "pants", label: "Bottoms", palette: FABRIC },
    ],
  },
  {
    id: "hair",
    label: "Hair",
    partSlot: "hair",
    parts: HAIR_PARTS,
    palettes: [{ slot: "hair", label: "Hair", palette: HAIR }],
  },
  {
    id: "shoes",
    label: "Shoes",
    partSlot: "shoes",
    parts: SHOE_PARTS,
    palettes: [{ slot: "shoes", label: "Shoes", palette: FABRIC }],
  },
  {
    id: "back",
    label: "Back",
    partSlot: "back",
    parts: BACK_PARTS,
    palettes: [{ slot: "accent", label: "Accessory", palette: FABRIC }],
  },
  {
    id: "face",
    label: "Face",
    partSlot: "face",
    parts: FACE_PARTS,
    palettes: [{ slot: "face", label: "Decoration", palette: FACE }],
  },
];

const PART_LOOKUP = {
  body: BODY_PARTS,
  hair: HAIR_PARTS,
  shoes: SHOE_PARTS,
  back: BACK_PARTS,
  face: FACE_PARTS,
};

export function partEntry(slot, id) {
  return (PART_LOOKUP[slot] || []).find(part => part.id === id) || null;
}

export function resolveLayers(design) {
  const layers = [];
  const back = partEntry("back", design.back);
  if (back?.file) layers.push(back.file);
  const hair = partEntry("hair", design.hair);
  if (hair?.back) layers.push(hair.back);
  const body = partEntry("body", design.body);
  if (body?.file) layers.push(body.file);
  const shoes = partEntry("shoes", design.shoes);
  if (shoes?.file) layers.push(shoes.file);
  if (hair?.front) layers.push(hair.front);
  const face = partEntry("face", design.face);
  if (face?.file) layers.push(face.file);
  return layers;
}

export function defaultDesign() {
  return {
    version: DESIGN_VERSION,
    body: "body-tee",
    hair: "hair-short",
    shoes: "shoes-sneakers",
    back: "back-none",
    face: "face-none",
    colors: {
      skin: SKIN[0][0],
      skinDark: SKIN[0][1],
      shirt: FABRIC[0][0],
      shirtDark: FABRIC[0][1],
      pants: FABRIC[4][0],
      pantsDark: FABRIC[4][1],
      hair: HAIR[1][0],
      hairDark: HAIR[1][1],
      shoes: FABRIC[10][0],
      shoesDark: FABRIC[10][1],
      accent: FABRIC[8][0],
      accentDark: FABRIC[8][1],
      face: FACE[0][0],
    },
  };
}

export const STARTER_PRESETS = [
  {
    label: "Sunny",
    design: {
      version: DESIGN_VERSION,
      body: "body-tee", hair: "hair-short", shoes: "shoes-sneakers", back: "back-cape", face: "face-blush",
      colors: {
        skin: "#f4d3b0", skinDark: "#d6ab84",
        shirt: "#c79a3a", shirtDark: "#936f24",
        pants: "#3f5a72", pantsDark: "#2a3f52",
        hair: "#6b3f22", hairDark: "#482814",
        shoes: "#a63f3f", shoesDark: "#772828",
        accent: "#4f8fc0", accentDark: "#356a94",
        face: "#e07a7a",
      },
    },
  },
  {
    label: "Midnight",
    design: {
      version: DESIGN_VERSION,
      body: "body-hoodie", hair: "hair-messy", shoes: "shoes-boots", back: "back-wings", face: "face-glasses",
      colors: {
        skin: "#b9c6cf", skinDark: "#8fa1ac",
        shirt: "#2f4470", shirtDark: "#1d2d4d",
        pants: "#3a3a42", pantsDark: "#232329",
        hair: "#7a4b8f", hairDark: "#563364",
        shoes: "#2b2b2b", shoesDark: "#141414",
        accent: "#5a9ad0", accentDark: "#3a6b9a",
        face: "#efeae0",
      },
    },
  },
  {
    label: "Meadow",
    design: {
      version: DESIGN_VERSION,
      body: "body-overalls", hair: "hair-ponytail", shoes: "shoes-sandals", back: "back-none", face: "face-eyes",
      colors: {
        skin: "#e6b885", skinDark: "#c3905e",
        shirt: "#d9cbaa", shirtDark: "#b0a07c",
        pants: "#3f6b3f", pantsDark: "#294a29",
        hair: "#4f8a4a", hairDark: "#356330",
        shoes: "#6b6b2f", shoesDark: "#4a4a1f",
        accent: "#c79a3a", accentDark: "#936f24",
        face: "#2b2b2b",
      },
    },
  },
];

export function randomDesign(rng = Math.random) {
  const pick = list => list[Math.floor(rng() * list.length)];
  const pickPair = list => list[Math.floor(rng() * list.length)];
  const skinPair = pickPair(SKIN);
  const hairPair = pickPair(HAIR);
  const topPair = pickPair(FABRIC);
  const bottomPair = pickPair(FABRIC);
  const shoePair = pickPair(FABRIC);
  const accentPair = pickPair(FABRIC);
  const facePair = pickPair(FACE);
  return {
    version: DESIGN_VERSION,
    body: pick(BODY_PARTS).id,
    hair: pick(HAIR_PARTS).id,
    shoes: pick(SHOE_PARTS).id,
    back: pick(BACK_PARTS).id,
    face: pick(FACE_PARTS).id,
    colors: {
      skin: skinPair[0], skinDark: skinPair[1],
      shirt: topPair[0], shirtDark: topPair[1],
      pants: bottomPair[0], pantsDark: bottomPair[1],
      hair: hairPair[0], hairDark: hairPair[1],
      shoes: shoePair[0], shoesDark: shoePair[1],
      accent: accentPair[0], accentDark: accentPair[1],
      face: facePair[0],
    },
  };
}

export function cloneDesign(design) {
  return {
    ...design,
    colors: { ...design.colors },
  };
}

export function darken(hex, amount = 0.28) {
  const value = String(hex || "").replace("#", "");
  if (value.length !== 6) return hex;
  const channels = [0, 2, 4].map(index => {
    const channel = parseInt(value.slice(index, index + 2), 16);
    return Math.max(0, Math.round(channel * (1 - amount)));
  });
  return `#${channels.map(channel => channel.toString(16).padStart(2, "0")).join("")}`;
}

export function applyPalettePair(design, slot, base, dark) {
  design.colors[slot] = base;
  design.colors[`${slot}Dark`] = dark;
}
