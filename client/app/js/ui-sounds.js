import { playSound, preloadSounds } from "./audio.js";
import { findInventoryCard, findRoomCard } from "./state.js";

function play(state, sound) {
  if (!sound) return;
  playSound(sound, Boolean(state?.ui?.soundEnabled));
}

function stackSound(state, selection) {
  if (!state || !selection) return "";
  const stack = selection.kind === "room-card"
    ? findRoomCard(state, selection.id)
    : selection.kind === "inventory-card" ? findInventoryCard(state, selection.id) : null;
  return stack?.definition?.sounds?.select || "";
}

/** Return the custom or default sound for selecting an entity. */
export function selectionSound(state, selection) {
  if (!selection) return "select";
  if (selection.kind === "prop") {
    const prop = state?.room?.props?.find(entry => entry.id === selection.id);
    return prop?.sounds?.select || "select";
  }
  return stackSound(state, selection) || "select";
}

/** Return the custom or default sound for an action. */
export function actionSound(action) {
  if (typeof action?.sound === "string" && action.sound) return action.sound;
  const type = action?.local?.type || action?.type;
  if (type === "open-view" || type === "open-shop") return "open";
  if (type === "close-view") return "close";
  if (type === "toggle-sell-mode") return "toggle";
  if (type === "inspect-card") return "card";
  if (type === "start-targeting" || type === "start-drop") return "card";
  if (type === "open-pack") return "open";
  if (type === "play-emote") return "card";
  if (type === "toggle-sound" || type === "toggle-emote-menu" || type === "toggle-titles") return "toggle";
  if (typeof action?.command === "string" && action.command.startsWith(".go ")) return "";
  return "click";
}

/** Play selection feedback for board and list selections. */
export function playSelectionSound(state, selection) {
  play(state, selectionSound(state, selection));
}

/** Play action feedback before a command or local action runs. */
export function playActionSound(state, action) {
  play(state, actionSound(action));
}

/** Play the room transition sound once per room change. */
export function playRoomSound(state) {
  play(state, "room");
}

/** Play a toast's custom sound, or the conventional tone sound. */
export function playToastSound(state, item) {
  if (!item || item.silent) return;
  const fallback = item.tone === "error" ? "error" : item.tone === "success" ? "success" : "tap";
  play(state, item.sound || fallback);
}

/** Install one delegated click sound with explicit per-button overrides. */
export function installButtonSoundHandler({ document, store }) {
  let warmed = false;
  document.addEventListener("click", event => {
    const button = event.target.closest?.("button, [role='button']");
    if (!button || button.disabled || button.getAttribute("aria-disabled") === "true") return;
    if (button.closest("#cutscene-layer") || button.dataset.sound === "none") return;
    const state = store.getState();
    if (!state.ui.soundEnabled) return;
    if (!warmed) {
      warmed = true;
      preloadSounds(["tap", "click", "select", "open", "close", "success"]);
    }
    if (button.dataset.sound) {
      playSound(button.dataset.sound, true);
      return;
    }
    if (button.closest("[data-action-index]") || button.id === "prop-default-action") return;
    if (button.hasAttribute("data-stack-id") || button.hasAttribute("data-room-picker-prop")
      || button.hasAttribute("data-task-id")) return;
    playSound("click", true);
  }, true);
}
