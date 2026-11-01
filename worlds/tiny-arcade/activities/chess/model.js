export const FILES = "abcdefgh";
export const PROMOTIONS = ["q", "r", "b", "n"];
export const PIECE_VALUES = { P: 1, N: 3, B: 3, R: 5, Q: 9, K: 0 };
const PIECE_LABELS = { K: "king", Q: "queen", R: "rook", B: "bishop", N: "knight", P: "pawn" };

const SHAPES = {
  P: [
    '<circle cx="50" cy="28" r="13"/>',
    '<path d="M39 41 Q50 34 61 41 L58 62 Q50 68 42 62 Z"/>',
    '<rect x="34" y="62" width="32" height="8" rx="3"/>',
    '<path d="M28 70 Q50 62 72 70 L76 82 Q50 88 24 82 Z"/>',
    '<rect x="18" y="82" width="64" height="9" rx="4"/>',
  ],
  R: [
    '<path d="M27 18 H38 V27 H46 V18 H54 V27 H62 V18 H73 V43 H65 V67 H73 V83 H27 V67 H35 V43 H27 Z"/>',
    '<rect x="19" y="82" width="62" height="9" rx="3"/>',
    '<path d="M33 39 H67" class="piece-line" stroke-width="3"/>',
    '<path d="M31 63 H69" class="piece-line" stroke-width="3"/>',
  ],
  N: [
    '<path d="M31 83 L34 64 Q35 50 46 40 L42 30 L49 18 L59 27 L65 24 Q78 30 75 44 Q73 55 63 61 L66 72 L72 83 Z"/>',
    '<path d="M58 36 Q63 38 61 44 Q58 48 53 44 Q51 39 58 36 Z" class="piece-eye"/>',
    '<path d="M50 24 Q61 20 68 29" class="piece-line" stroke-width="3"/>',
    '<rect x="20" y="82" width="60" height="9" rx="4"/>',
  ],
  B: [
    '<circle cx="50" cy="18" r="7"/>',
    '<path d="M50 25 Q65 37 61 53 L58 64 H42 L39 53 Q35 37 50 25 Z"/>',
    '<path d="M43 17 H57 M50 10 V25" class="piece-line" stroke-width="3"/>',
    '<rect x="35" y="63" width="30" height="8" rx="3"/>',
    '<path d="M29 71 Q50 64 71 71 L75 82 Q50 88 25 82 Z"/>',
    '<rect x="18" y="82" width="64" height="9" rx="4"/>',
  ],
  Q: [
    '<circle cx="23" cy="25" r="5"/><circle cx="37" cy="17" r="5"/><circle cx="50" cy="13" r="5"/><circle cx="63" cy="17" r="5"/><circle cx="77" cy="25" r="5"/>',
    '<path d="M21 28 L31 56 H69 L79 28 L64 43 L50 19 L36 43 Z"/>',
    '<rect x="33" y="56" width="34" height="8" rx="3"/>',
    '<path d="M28 65 Q50 58 72 65 L76 82 Q50 88 24 82 Z"/>',
    '<rect x="17" y="82" width="66" height="9" rx="4"/>',
  ],
  K: [
    '<path d="M44 8 H56 V19 H67 V31 H56 V42 H44 V31 H33 V19 H44 Z"/>',
    '<path d="M24 37 Q50 27 76 37 L68 59 H32 Z"/>',
    '<rect x="34" y="59" width="32" height="8" rx="3"/>',
    '<path d="M28 67 Q50 60 72 67 L76 82 Q50 88 24 82 Z"/>',
    '<rect x="17" y="82" width="66" height="9" rx="4"/>',
  ],
};

export function pieceLabel(kind) {
  return PIECE_LABELS[kind] || "piece";
}

export function pieceSvg(kind, color) {
  const body = SHAPES[kind] || SHAPES.P;
  const tone = color === "w" ? "ivory" : "obsidian";
  return `<svg class="piece-art ${tone}" viewBox="0 0 100 100" aria-hidden="true" focusable="false"><g class="piece-body">${body.join("")}</g><ellipse class="piece-shine" cx="42" cy="31" rx="19" ry="10"/></svg>`;
}

export function squareFile(square) {
  return typeof square === "string" ? FILES.indexOf(square[0]) : -1;
}

export function squareIsLight(file, rank) {
  return (file + rank) % 2 === 0;
}

export function squareRank(square) {
  return typeof square === "string" ? Number(square.slice(1)) : Number.NaN;
}

export function isSquare(square) {
  return squareFile(square) >= 0 && Number.isInteger(squareRank(square)) && squareRank(square) >= 1 && squareRank(square) <= 8;
}

export function pieceColor(code) {
  return typeof code === "string" && code.length === 2 ? code[0] : "";
}

export function pieceKind(code) {
  return typeof code === "string" && code.length === 2 ? code[1] : "";
}

export function activityState(hostState) {
  const activity = hostState?.room?.activities?.chess;
  if (!activity || activity.kind !== "chess") return null;
  if (!activity.state || typeof activity.state !== "object") return null;
  return activity.state;
}

export function controller(hostState) {
  const value = hostState?.room?.activities?.chess?.controller;
  return typeof value === "string" && value ? value : "";
}

export function canReset(hostState) {
  return Boolean(hostState?.room?.activities?.chess?.capabilities?.reset);
}

export function piecesBySquare(state) {
  const pieces = new Map();
  for (const piece of Array.isArray(state?.pieces) ? state.pieces : []) {
    if (piece && isSquare(piece.square)) pieces.set(piece.square, piece);
  }
  return pieces;
}

export function movesFrom(state, square) {
  const moves = state?.moves;
  if (!moves || typeof moves !== "object") return [];
  const targets = moves[square];
  return Array.isArray(targets) ? targets.filter(isSquare) : [];
}

export function needsPromotion(piece, target) {
  if (pieceKind(piece?.code) !== "P" || !isSquare(target)) return false;
  const rank = squareRank(target);
  return pieceColor(piece.code) === "w" ? rank === 8 : rank === 1;
}

export function promotionMoves(state, source, target) {
  return movesFrom(state, source).includes(target) ? PROMOTIONS.map(promotion => `${source}${target}${promotion}`) : [];
}

export function capturedPieces(pieces) {
  const remaining = new Set((Array.isArray(pieces) ? pieces : []).map(piece => String(piece?.id || "")));
  const captured = { white: [], black: [] };
  const backRank = ["R", "N", "B", "Q", "K", "B", "N", "R"];
  for (const [side, prefix] of [["white", "w"], ["black", "b"]]) {
    for (let file = 0; file < 8; file += 1) {
      if (!remaining.has(`${prefix}${backRank[file]}${file}`)) captured[side].push(backRank[file]);
    }
    for (let file = 0; file < 8; file += 1) {
      if (!remaining.has(`${prefix}P${file}`)) captured[side].push("P");
    }
  }
  return captured;
}

export function moveValue(state, source, target) {
  const board = piecesBySquare(state);
  const victim = board.get(target);
  if (!victim) return 0;
  const mover = board.get(source);
  if (!mover || pieceColor(mover.code) === pieceColor(victim.code)) return 0;
  return PIECE_VALUES[pieceKind(victim.code)] || 0;
}
