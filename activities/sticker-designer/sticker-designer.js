const Tiny = window.TinyActivity;
const grid = document.querySelector("#grid");
const summary = document.querySelector("#summary");
const confirmButton = document.querySelector("#confirm");
const announceButton = document.querySelector("#announce");
const connection = document.querySelector("#connection");

let state = null;
let selected = "";
let confirming = false;
let gridMarkup = "";

function currentStickerName() {
  return String(state?.user?.sticker || "");
}

function normalizeSticker(choice) {
  return {
    name: String(choice?.name || ""),
    imageUrl: Tiny.image(choice?.image_url || ""),
  };
}

function render() {
  if (!state) return;
  connection.textContent = state.user
    ? state.user.initialStickerComplete ? "" : "Choose your first sticker to enter Tinyrooms."
    : "Waiting for Tinyrooms…";
  const stickers = Array.isArray(state.stickers) ? state.stickers.map(normalizeSticker) : [];
  const current = currentStickerName();
  const focusedSticker = grid.contains(document.activeElement) ? document.activeElement.dataset.sticker : null;
  if (!selected) selected = current || stickers[0]?.name || "";
  const markup = stickers.map(sticker => `
    <button type="button" class="sticker" data-sticker="${Tiny.escape(sticker.name)}" aria-pressed="${sticker.name === selected}">
      <img src="${Tiny.escape(sticker.imageUrl)}" alt="${Tiny.escape(sticker.name)}">
      <strong>${Tiny.escape(sticker.name.replace(/\.png$/i, ""))}</strong>
      <span class="current">${sticker.name === current ? "Current sticker" : sticker.name === selected ? "Selected" : "Choose this"}</span>
    </button>
  `).join("");
  summary.textContent = current && selected === current
    ? "You are keeping your current sticker."
    : state.user?.initialStickerComplete ? "Confirm to update your room marker." : "Confirm your sticker to enter Tinyrooms.";
  confirmButton.disabled = !selected || confirming;
  if (markup !== gridMarkup) {
    gridMarkup = markup;
    grid.innerHTML = markup;
    grid.querySelectorAll("[data-sticker]").forEach(button => {
      button.onclick = () => {
        selected = button.dataset.sticker;
        Tiny.sound("flip");
        render();
      };
    });
    if (focusedSticker) {
      [...grid.querySelectorAll("[data-sticker]")].find(button => button.dataset.sticker === focusedSticker)?.focus({ preventScroll: true });
    }
  }
}

confirmButton.onclick = async () => {
  if (!selected || confirming) return;
  confirming = true;
  confirmButton.disabled = true;
  try {
    const result = await Tiny.confirmSticker(selected);
    Tiny.celebrate();
    Tiny.toast(result.message || "Sticker confirmed.");
  } catch (error) {
    Tiny.toast(error instanceof Error ? error.message : String(error), true);
  } finally {
    confirming = false;
    confirmButton.disabled = !selected;
  }
};

announceButton.onclick = () => {
  Tiny.notify(selected ? `Ready to confirm ${selected}` : "Still choosing a sticker");
};

Tiny.subscribe(nextState => {
  state = nextState;
  render();
});
