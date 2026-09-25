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
  { id: "body-tank", label: "Tank Top", file: "body-tank.svg" },
  { id: "body-sweater", label: "Sweater", file: "body-sweater.svg" },
  { id: "body-jumpsuit", label: "Jumpsuit", file: "body-jumpsuit.svg" },
  { id: "body-tux", label: "Tuxedo", file: "body-tux.svg" },
  { id: "body-labcoat", label: "Lab Coat", file: "body-labcoat.svg" },
  { id: "body-sport", label: "Jersey", file: "body-sport.svg" },
  { id: "body-raincoat", label: "Raincoat", file: "body-raincoat.svg" },
  { id: "body-poncho", label: "Poncho", file: "body-poncho.svg" },
  { id: "body-onesie", label: "Onesie", file: "body-onesie.svg" },
  { id: "body-apron", label: "Apron", file: "body-apron.svg" },
  { id: "body-rocker", label: "Rock Star", file: "body-rocker.svg" },
];

export const HAIR_PARTS = [
  { id: "hair-short", label: "Short", front: "hair-short.svg", back: "hair-short-back.svg" },
  { id: "hair-long", label: "Long", front: "hair-long.svg", back: "hair-long-back.svg" },
  { id: "hair-bob", label: "Bob", front: "hair-bob.svg", back: "hair-bob-back.svg" },
  { id: "hair-curly", label: "Curly", front: "hair-curly.svg", back: "hair-curly-back.svg" },
  { id: "hair-ponytail", label: "Ponytail", front: "hair-ponytail.svg", back: "hair-ponytail-back.svg" },
  { id: "hair-messy", label: "Messy", front: "hair-messy.svg", back: "hair-messy-back.svg" },
  { id: "hair-afro", label: "Afro", front: "hair-afro.svg", back: "hair-afro-back.svg" },
  { id: "hair-mohawk", label: "Mohawk", front: "hair-mohawk.svg", back: "hair-mohawk-back.svg" },
  { id: "hair-mullet", label: "Mullet", front: "hair-mullet.svg", back: "hair-mullet-back.svg" },
  { id: "hair-bowl", label: "Bowl Cut", front: "hair-bowl.svg", back: "hair-bowl-back.svg" },
  { id: "hair-sideswept", label: "Side Swept", front: "hair-sideswept.svg", back: "hair-sideswept-back.svg" },
  { id: "hair-braids", label: "Braids", front: "hair-braids.svg", back: "hair-braids-back.svg" },
  { id: "hair-buns", label: "Space Buns", front: "hair-buns.svg", back: "hair-buns-back.svg" },
  { id: "hair-emo", label: "Emo Fringe", front: "hair-emo.svg", back: "hair-emo-back.svg" },
  { id: "hair-topknot", label: "Top Knot", front: "hair-topknot.svg", back: "hair-topknot-back.svg" },
  { id: "hair-viking", label: "Viking", front: "hair-viking.svg", back: "hair-viking-back.svg" },
];

export const SHOE_PARTS = [
  { id: "shoes-sneakers", label: "Sneakers", file: "shoes-sneakers.svg" },
  { id: "shoes-boots", label: "Boots", file: "shoes-boots.svg" },
  { id: "shoes-sandals", label: "Sandals", file: "shoes-sandals.svg" },
  { id: "shoes-flats", label: "Flats", file: "shoes-flats.svg" },
  { id: "shoes-rollerskates", label: "Rollerskates", file: "shoes-rollerskates.svg" },
  { id: "shoes-cowboy", label: "Cowboy", file: "shoes-cowboy.svg" },
  { id: "shoes-crocs", label: "Crocs", file: "shoes-crocs.svg" },
  { id: "shoes-heels", label: "Heels", file: "shoes-heels.svg" },
  { id: "shoes-cleats", label: "Cleats", file: "shoes-cleats.svg" },
  { id: "shoes-snow", label: "Snow Boots", file: "shoes-snow.svg" },
  { id: "shoes-clown", label: "Clown", file: "shoes-clown.svg" },
  { id: "shoes-platforms", label: "Platforms", file: "shoes-platforms.svg" },
  { id: "shoes-fins", label: "Swim Fins", file: "shoes-fins.svg" },
  { id: "shoes-slippers", label: "Slippers", file: "shoes-slippers.svg" },
  { id: "shoes-moon", label: "Moon Boots", file: "shoes-moon.svg" },
];

export const BACK_PARTS = [
  { id: "back-none", label: "None" },
  { id: "back-wings", label: "Wings", file: "back-wings.svg" },
  { id: "back-cape", label: "Cape", file: "back-cape.svg" },
  { id: "back-pack", label: "Backpack", file: "back-pack.svg" },
  { id: "back-jetpack", label: "Jetpack", file: "back-jetpack.svg" },
  { id: "back-shell", label: "Turtle Shell", file: "back-shell.svg" },
  { id: "back-fairy", label: "Fairy Wings", file: "back-fairy.svg" },
  { id: "back-balloons", label: "Balloons", file: "back-balloons.svg" },
  { id: "back-tail", label: "Dino Tail", file: "back-tail.svg" },
  { id: "back-robotarms", label: "Robot Arms", file: "back-robotarms.svg" },
  { id: "back-surfboard", label: "Surfboard", file: "back-surfboard.svg" },
  { id: "back-guitar", label: "Guitar Case", file: "back-guitar.svg" },
  { id: "back-dragon", label: "Dragon Wings", file: "back-dragon.svg" },
  { id: "back-banner", label: "Hero Banner", file: "back-banner.svg" },
  { id: "back-propeller", label: "Propeller", file: "back-propeller.svg" },
];

export const FACE_PARTS = [
  { id: "face-none", label: "None" },
  { id: "face-blush", label: "Blush", file: "face-blush.svg" },
  { id: "face-glasses", label: "Glasses", file: "face-glasses.svg" },
  { id: "face-mask", label: "Mask", file: "face-mask.svg" },
  { id: "face-freckles", label: "Freckles", file: "face-freckles.svg" },
  { id: "face-mustache", label: "Mustache", file: "face-mustache.svg" },
  { id: "face-goatee", label: "Goatee", file: "face-goatee.svg" },
  { id: "face-beard", label: "Beard", file: "face-beard.svg" },
  { id: "face-scar", label: "Scar", file: "face-scar.svg" },
  { id: "face-bandage", label: "Bandage", file: "face-bandage.svg" },
  { id: "face-warpaint", label: "Warpaint", file: "face-warpaint.svg" },
  { id: "face-shades", label: "Shades", file: "face-shades.svg" },
  { id: "face-eyepatch", label: "Eye Patch", file: "face-eyepatch.svg" },
  { id: "face-monocle", label: "Monocle", file: "face-monocle.svg" },
  { id: "face-bandana", label: "Bandana", file: "face-bandana.svg" },
  { id: "face-sticker", label: "Star Sticker", file: "face-sticker.svg" },
];

export const EYES_PARTS = [
  { id: "eyes-none", label: "None" },
  { id: "eyes-dots", label: "Beady", file: "eyes-dots.svg" },
  { id: "eyes-round", label: "Round", file: "eyes-round.svg" },
  { id: "eyes-wide", label: "Wide", file: "eyes-wide.svg" },
  { id: "eyes-oval", label: "Oval", file: "eyes-oval.svg" },
  { id: "eyes-happy", label: "Happy", file: "eyes-happy.svg" },
  { id: "eyes-wink", label: "Wink", file: "eyes-wink.svg" },
  { id: "eyes-sleepy", label: "Sleepy", file: "eyes-sleepy.svg" },
  { id: "eyes-angry", label: "Angry", file: "eyes-angry.svg" },
  { id: "eyes-sad", label: "Sad", file: "eyes-sad.svg" },
  { id: "eyes-starry", label: "Starry", file: "eyes-starry.svg" },
  { id: "eyes-heart", label: "Heart", file: "eyes-heart.svg" },
  { id: "eyes-swirl", label: "Swirly", file: "eyes-swirl.svg" },
  { id: "eyes-x", label: "Dizzy", file: "eyes-x.svg" },
  { id: "eyes-cross", label: "Cross Eyed", file: "eyes-cross.svg" },
  { id: "eyes-squint", label: "Squint", file: "eyes-squint.svg" },
  { id: "eyes-surprised", label: "Surprised", file: "eyes-surprised.svg" },
  { id: "eyes-derp", label: "Derp", file: "eyes-derp.svg" },
  { id: "eyes-cat", label: "Cat Eyes", file: "eyes-cat.svg" },
  { id: "eyes-glow", label: "Laser Eyes", file: "eyes-glow.svg" },
  { id: "eyes-sparkle", label: "Sparkle", file: "eyes-sparkle.svg" },
];

export const MOUTH_PARTS = [
  { id: "mouth-none", label: "None" },
  { id: "mouth-line", label: "Straight", file: "mouth-line.svg" },
  { id: "mouth-smile", label: "Smile", file: "mouth-smile.svg" },
  { id: "mouth-grin", label: "Grin", file: "mouth-grin.svg" },
  { id: "mouth-frown", label: "Frown", file: "mouth-frown.svg" },
  { id: "mouth-open", label: "Open", file: "mouth-open.svg" },
  { id: "mouth-oh", label: "Surprised", file: "mouth-oh.svg" },
  { id: "mouth-smirk", label: "Smirk", file: "mouth-smirk.svg" },
  { id: "mouth-tongue", label: "Tongue Out", file: "mouth-tongue.svg" },
  { id: "mouth-teeth", label: "Teeth", file: "mouth-teeth.svg" },
  { id: "mouth-fangs", label: "Fangs", file: "mouth-fangs.svg" },
  { id: "mouth-wavy", label: "Wavy", file: "mouth-wavy.svg" },
  { id: "mouth-kiss", label: "Kissy", file: "mouth-kiss.svg" },
  { id: "mouth-whistle", label: "Whistle", file: "mouth-whistle.svg" },
  { id: "mouth-lips", label: "Lips", file: "mouth-lips.svg" },
  { id: "mouth-grimace", label: "Grimace", file: "mouth-grimace.svg" },
  { id: "mouth-chatter", label: "Chattering", file: "mouth-chatter.svg" },
  { id: "mouth-sing", label: "Singing", file: "mouth-sing.svg" },
  { id: "mouth-yawn", label: "Yawn", file: "mouth-yawn.svg" },
  { id: "mouth-buck", label: "Buck Teeth", file: "mouth-buck.svg" },
  { id: "mouth-blep", label: "Blep", file: "mouth-blep.svg" },
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
    id: "eyes",
    label: "Eyes",
    partSlot: "eyes",
    parts: EYES_PARTS,
    palettes: [{ slot: "face", label: "Eye Color", palette: FACE }],
  },
  {
    id: "mouth",
    label: "Mouth",
    partSlot: "mouth",
    parts: MOUTH_PARTS,
    palettes: [{ slot: "face", label: "Mouth Color", palette: FACE }],
  },
  {
    id: "face",
    label: "Extras",
    partSlot: "face",
    parts: FACE_PARTS,
    palettes: [{ slot: "face", label: "Extras Color", palette: FACE }],
  },
];

const PART_LOOKUP = {
  body: BODY_PARTS,
  hair: HAIR_PARTS,
  shoes: SHOE_PARTS,
  back: BACK_PARTS,
  face: FACE_PARTS,
  eyes: EYES_PARTS,
  mouth: MOUTH_PARTS,
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
  const eyes = partEntry("eyes", design.eyes);
  if (eyes?.file) layers.push(eyes.file);
  const mouth = partEntry("mouth", design.mouth);
  if (mouth?.file) layers.push(mouth.file);
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
    eyes: "eyes-dots",
    mouth: "mouth-smile",
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
      body: "body-tee", hair: "hair-short", shoes: "shoes-sneakers", back: "back-cape",
      face: "face-blush", eyes: "eyes-happy", mouth: "mouth-smile",
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
      body: "body-hoodie", hair: "hair-messy", shoes: "shoes-boots", back: "back-wings",
      face: "face-glasses", eyes: "eyes-starry", mouth: "mouth-smirk",
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
      body: "body-overalls", hair: "hair-ponytail", shoes: "shoes-sandals", back: "back-none",
      face: "face-none", eyes: "eyes-dots", mouth: "mouth-grin",
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
  const skinPair = pick(SKIN);
  const hairPair = pick(HAIR);
  const topPair = pick(FABRIC);
  const bottomPair = pick(FABRIC);
  const shoePair = pick(FABRIC);
  const accentPair = pick(FABRIC);
  const facePair = pick(FACE);
  return {
    version: DESIGN_VERSION,
    body: pick(BODY_PARTS).id,
    hair: pick(HAIR_PARTS).id,
    shoes: pick(SHOE_PARTS).id,
    back: pick(BACK_PARTS).id,
    face: pick(FACE_PARTS).id,
    eyes: pick(EYES_PARTS).id,
    mouth: pick(MOUTH_PARTS).id,
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

export function hydrateDesign(partial) {
  const base = defaultDesign();
  if (!partial || typeof partial !== "object") return base;
  const design = { ...base };
  for (const category of CATEGORIES) {
    const value = partial[category.partSlot];
    if (typeof value === "string" && partEntry(category.partSlot, value)) {
      design[category.partSlot] = value;
    }
  }
  design.version = DESIGN_VERSION;
  design.colors = { ...base.colors, ...(partial.colors && typeof partial.colors === "object" ? partial.colors : {}) };
  return design;
}

export function cloneDesign(design) {
  const hydrated = hydrateDesign(design);
  return {
    ...hydrated,
    colors: { ...hydrated.colors },
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
