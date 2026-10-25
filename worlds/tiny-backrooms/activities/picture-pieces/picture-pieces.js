import { LEVELS, checkArrangement, codePhrase, imageUrlFor } from "./puzzle.js";

const tabs = document.querySelector("#tabs");
const hint = document.querySelector("#level-hint");
const slotsRoot = document.querySelector("#slots");
const trayRoot = document.querySelector("#tray");
const status = document.querySelector("#status");
const connection = document.querySelector("#connection");
const checkButton = document.querySelector("#check");
const shuffleButton = document.querySelector("#shuffle");

let levelId = "br";
let slots = [null, null, null, null];
let tray = [0, 1, 2, 3];
let selected = null;

function image(url, alt) {
  const element = document.createElement("img");
  element.src = window.TinyActivity ? window.TinyActivity.image(url) : url;
  element.alt = alt;
  element.draggable = false;
  return element;
}

function shuffle(order) {
  const values = [...order];
  for (let index = values.length - 1; index > 0; index -= 1) {
    const other = Math.floor(Math.random() * (index + 1));
    [values[index], values[other]] = [values[other], values[index]];
  }
  return values;
}

function renderTabs() {
  tabs.textContent = "";
  for (const [id, level] of Object.entries(LEVELS)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = level.label;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(id === levelId));
    button.onclick = () => {
      levelId = id;
      resetBoard();
    };
    tabs.append(button);
  }
  hint.textContent = LEVELS[levelId].hint;
}

function resetBoard() {
  slots = [null, null, null, null];
  tray = shuffle([0, 1, 2, 3]);
  selected = null;
  status.textContent = "Place each quarter where it belongs, upright, then read the symbols.";
  renderTabs();
  renderBoard();
}

function renderBoard() {
  slotsRoot.textContent = "";
  const level = LEVELS[levelId];
  slots.forEach((slot, index) => {
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "piece-slot";
    cell.setAttribute("aria-label", `Quarter slot ${index + 1}`);
    if (slot === null) {
      const empty = document.createElement("span");
      empty.className = "empty";
      empty.textContent = `${index + 1}`;
      cell.append(empty);
    } else {
      const art = image(imageUrlFor(level.pieces[slot.piece]), `Quarter ${slot.piece + 1}`);
      art.style.transform = `rotate(${slot.rotation}deg)`;
      cell.append(art);
    }
    cell.onclick = () => {
      if (selected !== null && slot === null) {
        slots[index] = { piece: selected, rotation: 0 };
        tray = tray.filter(piece => piece !== selected);
        selected = null;
        renderBoard();
        return;
      }
      if (slot !== null && selected === null) {
        slot.rotation = (slot.rotation + 90) % 360;
        renderBoard();
        return;
      }
      if (slot !== null) {
        tray.push(slot.piece);
        slots[index] = { piece: selected, rotation: 0 };
        selected = null;
        renderBoard();
      }
    };
    cell.ondblclick = () => {
      if (slot !== null) {
        tray.push(slot.piece);
        slots[index] = null;
        renderBoard();
      }
    };
    slotsRoot.append(cell);
  });

  trayRoot.textContent = "";
  tray.forEach(piece => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "piece-loose";
    chip.setAttribute("aria-pressed", String(selected === piece));
    chip.setAttribute("aria-label", `Loose quarter ${piece + 1}`);
    chip.append(image(imageUrlFor(level.pieces[piece]), `Loose quarter ${piece + 1}`));
    chip.onclick = () => {
      selected = selected === piece ? null : piece;
      renderBoard();
    };
    trayRoot.append(chip);
  });
}

checkButton.onclick = () => {
  const result = checkArrangement(levelId, slots);
  if (result.ok) {
    const code = codePhrase(levelId);
    status.innerHTML = "";
    const done = document.createElement("span");
    done.className = "pieces-code";
    done.textContent = `The symbols read: ${code}. Feed them to the exit door in order.`;
    status.append(done);
    if (window.TinyActivity) {
      window.TinyActivity.celebrate();
      window.TinyActivity.notify(`Photograph restored: ${code}`);
    }
  } else {
    status.textContent = `${result.placed} of 4 quarters sit right. Keep turning them.`;
    if (window.TinyActivity) window.TinyActivity.toast("Not yet. The grain hides the order.", true);
  }
};

shuffleButton.onclick = () => {
  resetBoard();
};

if (window.TinyActivity) {
  window.TinyActivity.subscribe(() => {
    if (connection.textContent) connection.textContent = "";
  });
}

resetBoard();
