/**
 * Card presentation themes. Tags choose the printed title ribbon; rarity owns
 * the frame, glow, and foil treatment. Both the DOM/SVG faces and the WebGL
 * preview read from this module so every surface stays in sync.
 */

export const TYPE_ACCENTS = {
  item: ["#9a3b32", "#5e1d18"],
  emote: ["#2c7393", "#123b52"],
  skill: ["#3b7d47", "#1a4424"],
  pack: ["#6c4a92", "#33204e"],
};

export const DEFAULT_TYPE_ACCENT = ["#7a6235", "#3f3016"];

export const RARITY_STYLES = {
  common: {
    key: "common",
    label: "Common",
    color: "#8d99a3",
    colorDark: "#4c545c",
    outline: "#d2d8dd",
    outlineDark: "#6f777d",
    glow: "#8d99a3",
    glowStrength: 0,
    haloOpacity: 0,
    emissive: 0.04,
    iridescence: 0,
    foil: 0.18,
  },
  uncommon: {
    key: "uncommon",
    label: "Uncommon",
    color: "#3f9a52",
    colorDark: "#1d5028",
    outline: "#8fe09c",
    outlineDark: "#2f6f3c",
    glow: "#5fd36f",
    glowStrength: 0.28,
    haloOpacity: 0.14,
    emissive: 0.14,
    iridescence: 0,
    foil: 0.38,
  },
  rare: {
    key: "rare",
    label: "Rare",
    color: "#3a76c4",
    colorDark: "#1d3f70",
    outline: "#8cc4ff",
    outlineDark: "#2b5b90",
    glow: "#5aa9ff",
    glowStrength: 0.52,
    haloOpacity: 0.3,
    emissive: 0.26,
    iridescence: 0.12,
    foil: 0.58,
  },
  epic: {
    key: "epic",
    label: "Epic",
    color: "#8e4fc6",
    colorDark: "#4a2470",
    outline: "#d9b0ff",
    outlineDark: "#6d3a9a",
    glow: "#c07bff",
    glowStrength: 0.8,
    haloOpacity: 0.48,
    emissive: 0.42,
    iridescence: 0.5,
    foil: 0.78,
  },
  legendary: {
    key: "legendary",
    label: "Legendary",
    color: "#e08a1e",
    colorDark: "#7a4308",
    outline: "#ffe39a",
    outlineDark: "#a5650f",
    glow: "#ffcf5f",
    glowStrength: 1,
    haloOpacity: 0.68,
    emissive: 0.64,
    iridescence: 0.88,
    foil: 1,
  },
};

const SUBJECT_ACCENTS = {
  reading: ["#c0504d", "#6e2725"],
  writing: ["#a06a3c", "#5b3518"],
  math: ["#3a76c4", "#1d3f70"],
  history: ["#a07a32", "#5a4214"],
  geography: ["#2f8f73", "#145040"],
  chemistry: ["#4a9a44", "#235020"],
  tech: ["#5a6fc4", "#2b376e"],
  sport: ["#c26a2f", "#6b3512"],
  biology: ["#3f9a52", "#1d5028"],
};

const PAINTBALL_ACCENTS = {
  cherry: ["#ff4d6d", "#8f1f35"],
  berry: ["#4ea8ff", "#1d5c99"],
  lime: ["#5cf29a", "#1f8a52"],
  lemon: ["#ffe066", "#9b7a12"],
  grape: ["#c77dff", "#6a2fa8"],
};

const FOOD_TAGS = new Set(["food", "produce", "ingredient", "crafted-ingredient", "dish"]);
const MEDICINE_TAGS = new Set(["medicine", "health", "medical"]);
const UTILITY_TAGS = new Set(["utility", "tool", "tools"]);
const CLEANING_TAGS = new Set(["scoop", "vacuum", "cleaning"]);
const PAINT_TAGS = new Set(["paintgun", "paintball-ammo"]);

const FOOD_ACCENT = ["#7f8f34", "#3f4a13"];
const MEDICINE_ACCENT = ["#2f8f8a", "#124f4c"];
const UTILITY_ACCENT = ["#53718c", "#263a4d"];
const CLEANING_ACCENT = ["#3f8996", "#19464f"];
const PAINT_ACCENT = ["#b8642a", "#64310f"];
const TOPIC_ACCENT = ["#a34558", "#561d2a"];

function normalizeTags(tags) {
  if (!Array.isArray(tags)) return [];
  return [...new Set(tags.map(tag => String(tag).trim().toLowerCase()).filter(Boolean))].sort();
}

function hashTag(text) {
  let hash = 2166136261;
  for (let index = 0; index < text.length; index += 1) {
    hash ^= text.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function hslToHex(hue, saturation, lightness) {
  const s = saturation / 100;
  const l = lightness / 100;
  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  const section = hue / 60;
  const second = chroma * (1 - Math.abs((section % 2) - 1));
  const offset = l - chroma / 2;
  const [red, green, blue] = section < 1 ? [chroma, second, 0]
    : section < 2 ? [second, chroma, 0]
      : section < 3 ? [0, chroma, second]
        : section < 4 ? [0, second, chroma]
          : section < 5 ? [second, 0, chroma]
            : [chroma, 0, second];
  const channel = value => Math.round((value + offset) * 255).toString(16).padStart(2, "0");
  return `#${channel(red)}${channel(green)}${channel(blue)}`;
}

function hashAccent(tag) {
  const hash = hashTag(tag);
  const hue = hash % 360;
  return [hslToHex(hue, 46, 42), hslToHex(hue, 52, 20)];
}

function subjectPalette(name) {
  return SUBJECT_ACCENTS[name] || hashAccent(`subject:${name}`);
}

/** Rules run in priority order; the first family with a matching tag wins. */
const TAG_RULES = [
  {
    test: tag => tag.startsWith("paintball-color-"),
    palette: tag => PAINTBALL_ACCENTS[tag.slice("paintball-color-".length)] || hashAccent(tag),
  },
  {
    test: tag => tag.startsWith("subject:"),
    palette: tag => subjectPalette(tag.slice("subject:".length)),
  },
  {
    test: tag => tag.startsWith("skill:"),
    palette: tag => {
      const name = tag.slice("skill:".length).replace(/^skill-/, "");
      return SUBJECT_ACCENTS[name] || ["#b8862f", "#6b4a12"];
    },
  },
  { test: tag => MEDICINE_TAGS.has(tag), palette: () => MEDICINE_ACCENT },
  { test: tag => FOOD_TAGS.has(tag), palette: () => FOOD_ACCENT },
  { test: tag => tag === "supermarket", palette: () => ["#5f8f4a", "#2a4a1d"] },
  { test: tag => UTILITY_TAGS.has(tag), palette: () => UTILITY_ACCENT },
  { test: tag => CLEANING_TAGS.has(tag), palette: () => CLEANING_ACCENT },
  { test: tag => PAINT_TAGS.has(tag), palette: () => PAINT_ACCENT },
  { test: tag => tag === "topic", palette: () => TOPIC_ACCENT },
];

export function cardRarityKey(rarity) {
  const key = String(rarity || "").trim().toLowerCase();
  return RARITY_STYLES[key] ? key : "common";
}

export function rarityStyle(rarity) {
  return RARITY_STYLES[cardRarityKey(rarity)];
}

/** Return the first curated tag accent, or a deterministic hue for unknown tags. */
export function tagAccent(tags) {
  const normalized = normalizeTags(tags);
  if (!normalized.length) return null;
  for (const rule of TAG_RULES) {
    const tag = normalized.find(candidate => rule.test(candidate));
    if (!tag) continue;
    const [accent, accentDark] = rule.palette(tag);
    return { tag, accent, accentDark };
  }
  const tag = normalized[0];
  const [accent, accentDark] = hashAccent(tag);
  return { tag, accent, accentDark };
}

/** Resolve every presentation value a card face or preview needs. */
export function cardTheme(definition) {
  const raw = definition || {};
  const type = String(raw.type || "");
  const tags = normalizeTags(raw.tags);
  const rarity = rarityStyle(raw.rarity);
  const tag = tagAccent(tags);
  const [typeAccent, typeAccentDark] = TYPE_ACCENTS[type] || DEFAULT_TYPE_ACCENT;
  return {
    tags,
    type,
    rarityKey: rarity.key,
    rarity,
    tag,
    accent: tag ? tag.accent : typeAccent,
    accentDark: tag ? tag.accentDark : typeAccentDark,
    outline: rarity.outline,
    outlineDark: rarity.outlineDark,
    glow: rarity.glow,
    glowStrength: rarity.glowStrength,
    foil: rarity.foil,
    iridescence: rarity.iridescence,
  };
}
