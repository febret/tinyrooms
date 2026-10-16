import { cardGridMarkup, filterCards } from "../../app/js/editing/card-catalog-view.js";
import { escapeHtml } from "./util.js";

export function cardFieldMode(input) {
  const data = input.dataset;
  if (data.roomField === "cards") return "multiple";
  if (data.cardField?.endsWith(":card") || data.exitField?.endsWith(":requires")
    || data.dialogChoiceField?.endsWith(":give_card")) return "single";
  if (data.instanceField === "content" || data.taskField?.endsWith(":reward.cards")) return "multiple";
  if (data.instanceField === "draw_weight" || /:(ingredients|output)$/.test(data.recipeField || "")) return "mapping";
  return null;
}

export function readCardValue(value, mode) {
  if (mode === "single") return value ? [value] : [];
  if (mode === "multiple") return value.split(",").map(id => id.trim()).filter(Boolean);
  const parsed = JSON.parse(value || "{}");
  return Object.keys(Array.isArray(parsed) ? Object.assign({}, ...parsed) : parsed);
}

export function writeCardValue(value, mode, ids) {
  if (mode === "single") return ids[0] || "";
  if (mode === "multiple") {
    const original = readCardValue(value, mode);
    return ids.flatMap(id => original.includes(id) ? original.filter(existing => existing === id) : [id]).join(", ");
  }
  const parsed = JSON.parse(value || "{}");
  const original = Array.isArray(parsed) ? Object.assign({}, ...parsed) : parsed;
  return JSON.stringify(Object.fromEntries(ids.map(id => [id, original[id] ?? 1])), null, 2);
}

export function createCardSelector({ getCards, onChange, onError }) {
  const dialog = document.createElement("dialog");
  dialog.className = "card-selector card-catalog";
  dialog.setAttribute("aria-label", "Select cards");
  document.body.append(dialog);
  let target;
  let mode;
  let selected;
  let query = "";
  let source = "";
  let focusReturn;

  function renderGrid() {
    const cards = filterCards(getCards(), query, source);
    dialog.querySelector("[data-card-results]").innerHTML = cardGridMarkup(cards, { selectable: true, selected, multiple: mode !== "single" });
    dialog.querySelector("[data-card-count]").textContent = `${selected.size} selected · ${cards.length} shown`;
  }

  function open(input, button) {
    try {
      mode = cardFieldMode(input);
      selected = new Set(readCardValue(input.value, mode));
      target = input;
      focusReturn = button;
      query = "";
      source = "";
      const sources = [...new Set(getCards().map(card => card.source).filter(Boolean))].sort();
      dialog.innerHTML = `<header><h2>${mode === "single" ? "Select a card" : "Select cards"}</h2>
        <button type="button" data-card-cancel>Cancel</button></header>
        <div class="card-selector-filters">
          <input type="search" data-card-search aria-label="Search cards" placeholder="Search cards" autofocus>
          <select data-card-source aria-label="Cardset"><option value="">All cardsets</option>${sources.map(id => `<option value="${escapeHtml(id)}">${escapeHtml(id)}</option>`).join("")}</select>
          <span data-card-count role="status"></span>
        </div>
        <div data-card-results></div>
        <footer><button type="button" data-card-clear>Clear selection</button><button type="button" class="primary" data-card-apply>Use selected cards</button></footer>`;
      renderGrid();
      dialog.showModal();
    } catch (error) { onError(`Could not open card selector: ${error.message}`); }
  }

  dialog.addEventListener("input", event => {
    if (event.target.matches("[data-card-search]")) { query = event.target.value; renderGrid(); }
  });
  dialog.addEventListener("change", event => {
    const input = event.target;
    if (input.matches("[data-card-source]")) { source = input.value; renderGrid(); }
    if (input.name === "selected-card") {
      if (mode === "single") selected.clear();
      if (input.checked) selected.add(input.value);
      else selected.delete(input.value);
      dialog.querySelectorAll('input[name="selected-card"]').forEach(node => {
        node.closest(".card-tile").classList.toggle("is-selected", selected.has(node.value));
      });
      dialog.querySelector("[data-card-count]").textContent = `${selected.size} selected · ${filterCards(getCards(), query, source).length} shown`;
    }
  });
  dialog.addEventListener("keydown", event => event.stopPropagation());
  dialog.addEventListener("close", () => focusReturn?.isConnected && focusReturn.focus());
  dialog.addEventListener("click", event => {
    if (event.target.closest("[data-card-cancel]")) dialog.close();
    if (event.target.closest("[data-card-clear]")) { selected.clear(); renderGrid(); }
    if (event.target.closest("[data-card-apply]")) {
      try {
        target.value = writeCardValue(target.value, mode, [...selected]);
        onChange(target);
        dialog.close();
      } catch (error) { onError(`Could not apply card selection: ${error.message}`); }
    }
  });

  return {
    bind(root) {
      root.querySelectorAll("input,select,textarea").forEach(input => {
        if (!cardFieldMode(input)) return;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "card-select-button";
        button.textContent = cardFieldMode(input) === "single" ? "Choose card…" : "Choose cards…";
        button.onclick = event => { event.preventDefault(); open(input, button); };
        input.insertAdjacentElement("afterend", button);
      });
    },
  };
}
