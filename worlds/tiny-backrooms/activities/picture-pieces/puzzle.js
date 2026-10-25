export const LEVELS = {
  br: {
    label: "Backrooms photograph",
    hint: "Yellow hum. The door wants HOLLOW EYE, KNOTTED BELL, BRASS KEY, PAPER MOTH.",
    pieces: ["tb-piece-br-0", "tb-piece-br-1", "tb-piece-br-2", "tb-piece-br-3"],
    code: ["hollow-eye", "knotted-bell", "brass-key", "paper-moth"],
  },
  ud: {
    label: "Upside Down photograph",
    hint: "Cold blue ash. The door wants ASHEN STAR, PETAL MAW, IRON FANG, DROWNED BELL.",
    pieces: ["tb-piece-ud-0", "tb-piece-ud-1", "tb-piece-ud-2", "tb-piece-ud-3"],
    code: ["ashen-star", "petal-maw", "iron-fang", "drowned-bell"],
  },
  op: {
    label: "Outer Plane photograph",
    hint: "Violet static. The door wants YAWNING SIGIL, SIXTEEN THROATS, BLACK TIDE, CROOKED CROWN.",
    pieces: ["tb-piece-op-0", "tb-piece-op-1", "tb-piece-op-2", "tb-piece-op-3"],
    code: ["yawning-sigil", "sixteen-throats", "black-tide", "crooked-crown"],
  },
};

export function displayName(symbol) {
  return String(symbol || "").split("-").map(word => word.toUpperCase()).join(" ");
}

export function imageUrlFor(pieceId) {
  return `/assets/world/tiny-backrooms/cards/${pieceId}.png`;
}

function normalizeRotation(rotation) {
  const value = Number(rotation) || 0;
  return ((value % 360) + 360) % 360;
}

export function checkArrangement(levelId, slots) {
  const level = LEVELS[levelId];
  if (!level || !Array.isArray(slots) || slots.length !== 4) {
    return { ok: false, placed: 0 };
  }
  let placed = 0;
  for (let index = 0; index < 4; index += 1) {
    const slot = slots[index] || {};
    if (Number(slot.piece) === index && normalizeRotation(slot.rotation) === 0) {
      placed += 1;
    }
  }
  return { ok: placed === 4, placed };
}

export function codeOrder(levelId) {
  const level = LEVELS[levelId];
  return level ? [...level.code] : [];
}

export function codePhrase(levelId) {
  return codeOrder(levelId).map(displayName).join(", ");
}
