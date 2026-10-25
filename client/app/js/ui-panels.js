import { escapeHtml } from "./presentation.js";

export function actionsBarMarkup(state, dialogActions, selectionActions, actionSound) {
  if (state.ui.dropTargeting) {
    const drop = state.ui.dropTargeting;
    const count = drop.quantity > 1 ? ` ×${drop.quantity}` : "";
    return `<span class="targeting-hint">Drop ${escapeHtml(drop.label)}${escapeHtml(count)} — click a spot in the room or a container</span>
      <button type="button" class="cancel" data-action-index="-1" data-sound="click">Cancel</button>`;
  }
  if (state.ui.targeting) {
    return `<span class="targeting-hint">Use ${escapeHtml(state.ui.targeting.label)} — confirm with the button or click the target again</span>
      <button type="button" class="cancel" data-action-index="-1" data-sound="click">Cancel</button>`;
  }
  const actions = state.room?.dialog ? dialogActions(state) : selectionActions(state);
  if (!actions.length) {
    return `<span class="actions-empty">${state.room ? "Select a card or peep to see its actions." : "Welcome to Tinyrooms."}</span>`;
  }
  return actions.map((action, index) => {
    const tone = action.label === "Inspect" || action.label.startsWith("Open") ? "neutral" : action.label === "Close" ? "cancel" : action.tone || "neutral";
    const label = escapeHtml(action.label);
    const className = action.icon ? `${tone} icon-action` : tone;
    const accessible = action.icon ? ` aria-label="${label}" title="${label}"` : "";
    const content = action.icon ? `<img src="${escapeHtml(action.icon)}" alt="">` : label;
    const sound = action.sound || actionSound(action);
    return `<button type="button" class="${className}" data-action-index="${index}" data-sound="${escapeHtml(sound)}" data-focus-key="${escapeHtml(action.command || action.label)}"${accessible} ${action.disabled ? "disabled" : ""}>${content}</button>`;
  }).join("");
}

let lastPhoneFriendIndex = null;

export function syncPhoneFriendSelection(state, panelLayer) {
  if (state.views.main !== "phone" || state.ui.phoneApp !== "friends") {
    lastPhoneFriendIndex = null;
    return;
  }
  const index = Number(state.ui.phoneFriendIndex || 0);
  if (index === lastPhoneFriendIndex) return;
  lastPhoneFriendIndex = index;
  requestAnimationFrame(() => {
    panelLayer.querySelector(".phone-app-body .friend-entry.selected")?.scrollIntoView({ block: "nearest" });
  });
}

export function actionLogMarkup(state) {
  return `<header class="panel-header"><h2>Room activity</h2>
    <button type="button" class="icon-button" aria-label="Hide activity log">&times;</button></header>
    <div class="log-lines">${(state.room?.chatHistory || []).slice(-50).map(entry =>
      `<p class="log-line ${entry.kind === "chat" ? "chat" : "system"}">${escapeHtml(entry.kind === "chat" ? `${entry.speaker}: ${entry.text}` : entry.text)}</p>`
    ).join("") || `<p class="empty-state">No room events yet.</p>`}</div>`;
}
