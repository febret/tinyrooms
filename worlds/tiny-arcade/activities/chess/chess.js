import {
  FILES,
  activityState,
  canReset,
  capturedPieces,
  controller,
  movesFrom,
  needsPromotion,
  pieceColor,
  pieceKind,
  pieceLabel,
  pieceSvg,
  piecesBySquare,
} from "./model.js";

const Tiny = window.TinyActivity;
const board = document.querySelector("#board");
const connection = document.querySelector("#connection");
const statusView = document.querySelector("#status");
const detailsView = document.querySelector("#details");
const energyView = document.querySelector("#energy");
const resetButton = document.querySelector("#reset");
const capturedBlack = document.querySelector("#captured-black");
const capturedWhite = document.querySelector("#captured-white");
const promotionShade = document.querySelector("#promotion");
const promotionOptions = document.querySelector("#promotion-options");

let host = null;
let selected = "";
let pendingMove = null;

function squareLabel(square, piece) {
  if (!piece) return `Empty square ${square}`;
  const color = pieceColor(piece.code) === "w" ? "White" : "Black";
  return `${color} ${pieceLabel(pieceKind(piece.code))} on ${square}`;
}

function sendInput(payload) {
  const target = controller(host);
  if (!target) {
    Tiny.toast("Open Chess from the lobby first.", true);
    return Promise.reject(new Error("missing controller"));
  }
  return Tiny.command(`.activity_input ${payload} @prop:${target}`);
}

function clearPromotion() {
  pendingMove = null;
  promotionOptions.textContent = "";
  promotionShade.hidden = true;
}

function choosePromotion(promotion) {
  const move = pendingMove;
  clearPromotion();
  if (!move) return;
  selected = "";
  void sendInput(`move:${move.source}${move.target}${promotion}`)
    .then(() => Tiny.sound("flip"))
    .catch(error => Tiny.toast(error instanceof Error ? error.message : String(error), true));
}

function showPromotion(source, target) {
  pendingMove = { source, target };
  promotionOptions.textContent = "";
  for (const promotion of ["q", "r", "b", "n"]) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = pieceSvg(promotion.toUpperCase(), "w");
    button.setAttribute("aria-label", `Promote to ${pieceLabel(promotion.toUpperCase())}`);
    button.onclick = () => choosePromotion(promotion);
    promotionOptions.append(button);
  }
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "quiet small";
  cancel.textContent = "Cancel";
  cancel.onclick = clearPromotion;
  promotionOptions.append(cancel);
  promotionShade.hidden = false;
  promotionOptions.querySelector("button")?.focus();
}

function sendMove(source, target) {
  selected = "";
  void sendInput(`move:${source}${target}`)
    .then(() => Tiny.sound("flip"))
    .catch(error => Tiny.toast(error instanceof Error ? error.message : String(error), true));
}

function selectSquare(square, state) {
  const targets = selected ? movesFrom(state, selected) : [];
  if (selected && targets.includes(square)) {
    const boardPieces = piecesBySquare(state);
    const piece = boardPieces.get(selected);
    if (piece && needsPromotion(piece, square)) {
      showPromotion(selected, square);
      return;
    }
    sendMove(selected, square);
    return;
  }
  if (movesFrom(state, square).length) {
    selected = square;
    const piece = piecesBySquare(state).get(square);
    detailsView.textContent = `Selected ${squareLabel(square, piece)}. Choose a highlighted destination.`;
  } else {
    selected = "";
    detailsView.textContent = state.status;
  }
  renderBoard(state);
}

function renderTray(pieces) {
  const captured = capturedPieces(pieces);
  capturedBlack.innerHTML = captured.black.map(kind => `<span class="captured-piece">${pieceSvg(kind, "b")}</span>`).join("");
  capturedWhite.innerHTML = captured.white.map(kind => `<span class="captured-piece">${pieceSvg(kind, "w")}</span>`).join("");
}

function renderBoard(state) {
  board.textContent = "";
  const pieces = piecesBySquare(state);
  const last = state.last_move && typeof state.last_move === "object" ? state.last_move : null;
  const targets = selected ? movesFrom(state, selected) : [];
  for (let rank = 8; rank >= 1; rank -= 1) {
    for (let file = 0; file < 8; file += 1) {
      const square = `${FILES[file]}${rank}`;
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = `chess-cell ${((file + rank) % 2 === 0 ? "dark" : "light")}`;
      cell.dataset.file = FILES[file];
      cell.dataset.rank = String(rank);
      const piece = pieces.get(square);
      cell.setAttribute("aria-label", squareLabel(square, piece));
      cell.dataset.selected = String(selected === square);
      cell.dataset.target = String(targets.includes(square));
      cell.dataset.last = String(last && (last.from === square || last.to === square));
      cell.dataset.threat = String(state.hazards?.[square] === "threat");
      cell.dataset.check = String(state.hazards?.[square] === "check");
      if (file === 0) {
        const rankLabel = document.createElement("span");
        rankLabel.className = "cell-coord cell-rank";
        rankLabel.textContent = String(rank);
        cell.append(rankLabel);
      }
      if (rank === 1) {
        const fileLabel = document.createElement("span");
        fileLabel.className = "cell-coord cell-file";
        fileLabel.textContent = FILES[file];
        cell.append(fileLabel);
      }
      if (piece) {
        const token = document.createElement("span");
        token.className = `chess-piece ${pieceColor(piece.code) === "w" ? "white" : "black"}`;
        token.innerHTML = pieceSvg(pieceKind(piece.code), pieceColor(piece.code));
        cell.append(token);
      } else if (targets.includes(square)) {
        const dot = document.createElement("span");
        dot.className = "move-dot";
        cell.append(dot);
      }
      cell.addEventListener("click", () => selectSquare(square, state));
      board.append(cell);
    }
  }
  renderTray(state.pieces);
}

function render() {
  if (!host) return;
  connection.textContent = "";
  const energy = Number(host.user?.counters?.energy);
  energyView.textContent = Number.isFinite(energy) ? String(Math.round(energy)) : "—";
  resetButton.hidden = !canReset(host);
  const state = activityState(host);
  if (!state) {
    statusView.textContent = "Chess";
    detailsView.textContent = "The shared board state is still loading.";
    board.textContent = "";
    return;
  }
  if (selected && !movesFrom(state, selected).length) selected = "";
  statusView.textContent = state.status;
  if (!pendingMove && !selected) detailsView.textContent = "Anyone in the arcade can play either side.";
  renderBoard(state);
}

resetButton.addEventListener("click", () => {
  void sendInput("reset").catch(error => Tiny.toast(error instanceof Error ? error.message : String(error), true));
});

promotionShade.addEventListener("click", event => {
  if (event.target === promotionShade) clearPromotion();
});

board.addEventListener("keydown", event => {
  if (event.key === "Escape" && (selected || pendingMove)) {
    event.preventDefault();
    clearPromotion();
    selected = "";
    render();
  }
});

Tiny.subscribe(next => {
  host = next;
  render();
});
