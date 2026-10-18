import { escapeHtml } from "./presentation.js";
import { withBase } from "./base-path.js";

/** Full card faces are composed SVG: one layout for DOM cards and 3D textures. */
export const CARD_FACE_WIDTH = 310;
export const CARD_FACE_HEIGHT = 440;
// Bump when the layout changes so rasterized texture caches miss.
export const CARD_FACE_STYLE_VERSION = 1;

const FONT = "Georgia, 'Times New Roman', serif";
const TYPE_ACCENTS = {
  item: ["#9a3b32", "#5e1d18"],
  emote: ["#2c7393", "#123b52"],
  skill: ["#3b7d47", "#1a4424"],
  pack: ["#6c4a92", "#33204e"],
};
const DEFAULT_ACCENT = ["#7a6235", "#3f3016"];
const RARITY_COLORS = {
  common: "#8d99a3",
  uncommon: "#3f9a52",
  rare: "#3a76c4",
  epic: "#8e4fc6",
  legendary: "#e08a1e",
};
const BONUS_LABELS = {
  constitution: "CON",
  dexterity: "DEX",
  charisma: "CHA",
  fanciness: "FANCY",
  max_energy: "ENERGY",
};
const ART = { x: 24, y: 24, width: 262, height: 248 };
let instanceCounter = 0;

/** Accept a normalized client definition or a raw snake_case server payload. */
export function cardFaceFields(definition) {
  const raw = definition || {};
  const pick = (camel, snake) => raw[camel] ?? raw[snake];
  const energy = pick("energyCost", "energy_cost");
  return {
    label: String(raw.label || raw.id || "Card"),
    description: String(raw.description || ""),
    imageUrl: withBase(String(pick("imageUrl", "image_url") || "")),
    type: String(raw.type || ""),
    rarity: String(raw.rarity || ""),
    category: String(raw.category || ""),
    rank: String(raw.rank || ""),
    energyCost: typeof energy === "number" && energy > 0 ? energy : null,
    oneUse: Boolean(pick("oneUse", "one_use")),
    passive: Boolean(raw.passive),
    quest: Boolean(raw.quest),
    effect: String(raw.effect || ""),
    amount: Number(raw.amount || 0),
    bonuses: raw.bonuses && typeof raw.bonuses === "object" ? raw.bonuses : {},
  };
}

/** Approximate rendered width; deterministic so DOM and texture layouts agree. */
export function estimateTextWidth(text, size) {
  let units = 0;
  for (const character of String(text)) {
    if (character === " ") units += 0.28;
    else if (/[iljt.,'!:|]/.test(character)) units += 0.32;
    else if (/[mwMW]/.test(character)) units += 0.86;
    else if (/[A-Z0-9+]/.test(character)) units += 0.68;
    else units += 0.54;
  }
  return units * size;
}

/** Greedily wrap words to `maxWidth`; overflowing final lines end in an ellipsis. */
export function wrapText(text, size, maxWidth, maxLines) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let current = "";
  for (const word of words) {
    const candidate = current ? `${current} ${word}` : word;
    if (!current || estimateTextWidth(candidate, size) <= maxWidth) {
      current = candidate;
      continue;
    }
    lines.push(current);
    current = word;
  }
  if (current) lines.push(current);
  if (lines.length <= maxLines) return lines;
  const kept = lines.slice(0, maxLines);
  let last = kept[maxLines - 1];
  while (last.includes(" ") && estimateTextWidth(`${last}…`, size) > maxWidth) last = last.slice(0, last.lastIndexOf(" "));
  kept[maxLines - 1] = `${last.replace(/[.,;:]$/, "")}…`;
  return kept;
}

/** Fit the title on one line when possible, else two smaller lines. */
export function fitTitle(label) {
  for (let size = 24; size >= 17; size -= 1) {
    if (estimateTextWidth(label, size) <= 214) return { size, lines: [label] };
  }
  return { size: 16, lines: wrapText(label, 16, 214, 2) };
}

function typeLine(fields) {
  const kind = fields.type === "pack" ? "Card Pack" : fields.type || "Card";
  const detail = fields.type === "emote" ? fields.category : fields.type === "skill" ? fields.rank : "";
  return [kind, detail || fields.rarity].filter(Boolean).join(" · ").toUpperCase();
}

function statsLine(fields) {
  const parts = Object.entries(fields.bonuses).map(([key, value]) => `${BONUS_LABELS[key] || key.replaceAll("_", " ").toUpperCase()} ${value > 0 ? "+" : ""}${value}`);
  if (fields.effect && fields.amount) parts.push(`+${fields.amount} ${fields.effect.toUpperCase()}`);
  else if (fields.effect === "light") parts.push("LIGHT");
  if (fields.oneUse) parts.push("ONE USE");
  if (fields.quest) parts.push("QUEST");
  return parts.join(" · ");
}

function textLines(lines, { x, y, size, lineHeight, fill, weight = "normal", style = "normal", spacing = 0 }) {
  return lines.map((line, index) => `<text x="${x}" y="${y + index * lineHeight}" text-anchor="middle" font-family="${FONT}" font-size="${size}" font-weight="${weight}" font-style="${style}" letter-spacing="${spacing}" fill="${fill}">${escapeHtml(line)}</text>`).join("");
}

function diamond(cx, cy, radius, fill) {
  return `<path d="M${cx} ${cy - radius}L${cx + radius} ${cy}L${cx} ${cy + radius}L${cx - radius} ${cy}Z" fill="${fill}" stroke="#5a3a12" stroke-width="1"/>`;
}

/**
 * Return a standalone SVG document string for one card's full face.
 * Options: `imageHref` overrides the art URL (data URLs for rasterizing),
 * `idPrefix` makes gradient ids deterministic, and `label` exposes the SVG as an
 * accessible image; otherwise it is decorative because its control is labelled.
 */
export function cardFaceSvg(definition, { imageHref, idPrefix, label, className = "card-face" } = {}) {
  const fields = cardFaceFields(definition);
  const id = idPrefix || `cf${(instanceCounter += 1).toString(36)}`;
  const [accent, accentDark] = TYPE_ACCENTS[fields.type] || DEFAULT_ACCENT;
  const rarityKey = fields.rarity.toLowerCase();
  const art = imageHref ?? fields.imageUrl;
  const title = fitTitle(fields.label);
  const titleTop = title.lines.length === 1 ? 289 + title.size * 0.35 : 281;
  const stats = statsLine(fields);
  const descriptionTop = stats ? 382 : 366;
  const description = wrapText(fields.description, 12.5, 248, stats ? 3 : 4);
  const accessibility = label ? `role="img" aria-label="${escapeHtml(label)}"` : 'aria-hidden="true" focusable="false"';
  return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" class="${escapeHtml(className)}" viewBox="0 0 ${CARD_FACE_WIDTH} ${CARD_FACE_HEIGHT}" width="${CARD_FACE_WIDTH}" height="${CARD_FACE_HEIGHT}" ${accessibility} data-card-type="${escapeHtml(fields.type || "card")}">
<defs>
<linearGradient id="${id}-gold" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f7e2a3"/><stop offset=".35" stop-color="#c8963d"/><stop offset=".6" stop-color="#f4d58c"/><stop offset="1" stop-color="#8d5d1f"/></linearGradient>
<radialGradient id="${id}-paper" cx=".5" cy=".45" r=".75"><stop offset="0" stop-color="#fbf1d8"/><stop offset=".7" stop-color="#ecd9ab"/><stop offset="1" stop-color="#d4b67a"/></radialGradient>
<linearGradient id="${id}-accent" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${accent}"/><stop offset="1" stop-color="${accentDark}"/></linearGradient>
<clipPath id="${id}-art"><rect x="${ART.x}" y="${ART.y}" width="${ART.width}" height="${ART.height}" rx="9"/></clipPath>
</defs>
<rect x="1" y="1" width="${CARD_FACE_WIDTH - 2}" height="${CARD_FACE_HEIGHT - 2}" rx="20" fill="url(#${id}-gold)" stroke="#4a2f0e" stroke-width="2"/>
<rect x="9" y="9" width="${CARD_FACE_WIDTH - 18}" height="${CARD_FACE_HEIGHT - 18}" rx="14" fill="url(#${id}-paper)" stroke="#7a5520" stroke-width="1.5"/>
<rect x="15" y="15" width="${CARD_FACE_WIDTH - 30}" height="${CARD_FACE_HEIGHT - 30}" rx="10" fill="none" stroke="#b88a3e" stroke-width="1" stroke-dasharray="2 3"/>
<rect x="${ART.x}" y="${ART.y}" width="${ART.width}" height="${ART.height}" rx="9" fill="#16222c"/>
${art ? `<image href="${escapeHtml(art)}" xlink:href="${escapeHtml(art)}" x="${ART.x}" y="${ART.y}" width="${ART.width}" height="${ART.height}" preserveAspectRatio="xMidYMid slice" clip-path="url(#${id}-art)"/>` : ""}
<rect x="${ART.x}" y="${ART.y}" width="${ART.width}" height="${ART.height}" rx="9" fill="none" stroke="url(#${id}-gold)" stroke-width="4"/>
<rect x="${ART.x + 3}" y="${ART.y + 3}" width="${ART.width - 6}" height="${ART.height - 6}" rx="7" fill="none" stroke="#2c1a06" stroke-opacity=".55" stroke-width="1"/>
${diamond(155, 9, 6, "url(#" + id + "-gold)")}${diamond(155, CARD_FACE_HEIGHT - 9, 6, "url(#" + id + "-gold)")}${diamond(9, 289, 6, "url(#" + id + "-gold)")}${diamond(CARD_FACE_WIDTH - 9, 289, 6, "url(#" + id + "-gold)")}
<path d="M26 262H284L296 289L284 316H26L14 289Z" fill="url(#${id}-accent)" stroke="url(#${id}-gold)" stroke-width="3"/>
${textLines(title.lines, { x: 155, y: titleTop, size: title.size, lineHeight: title.size + 2, fill: "#fff8e6", weight: "bold" })}
${textLines([typeLine(fields)], { x: 155, y: 336, size: 10.5, lineHeight: 0, fill: "#6b4a1d", weight: "bold", spacing: 1.2 })}
<path d="M70 345H140M170 345H240" stroke="#b88a3e" stroke-width="1"/>${diamond(155, 345, 4, "#c8963d")}
${stats ? textLines([stats], { x: 155, y: 364, size: 13, lineHeight: 0, fill: "#3c2a10", weight: "bold" }) : ""}
${textLines(description, { x: 155, y: descriptionTop, size: 12.5, lineHeight: 15, fill: "#4a3618", style: "italic" })}
${fields.energyCost !== null ? `<g><title>Energy cost</title><circle cx="38" cy="38" r="17" fill="#2f6fa8" stroke="url(#${id}-gold)" stroke-width="3"/>${textLines([String(fields.energyCost)], { x: 38, y: 44, size: 17, lineHeight: 0, fill: "#ffffff", weight: "bold" })}</g>` : ""}
${RARITY_COLORS[rarityKey] ? `<g><title>${escapeHtml(fields.rarity)}</title><circle cx="272" cy="38" r="14" fill="${RARITY_COLORS[rarityKey]}" stroke="url(#${id}-gold)" stroke-width="3"/>${textLines([fields.rarity[0].toUpperCase()], { x: 272, y: 43.5, size: 14, lineHeight: 0, fill: "#ffffff", weight: "bold" })}</g>` : ""}
</svg>`;
}
