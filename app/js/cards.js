import { CARD_BACK } from "./board.js";
import { buildFavoriteCommand } from "./commands.js";
import { findInventoryCard, findRoomCard, findSelectedEntity } from "./state.js";
import { escapeHtml } from "./presentation.js";
import { longDescription, PLACEHOLDER_VIEWS, rarityLabel, tileMarkup } from "./views/view-helpers.js";
import { roomView } from "./views/room-view.js";
import { inventoryView } from "./views/inventory-view.js";
import { emotesView } from "./views/emotes-view.js";
import { skillsView } from "./views/skills-view.js";
import { friendsView } from "./views/friends-view.js";
import { selfView } from "./views/self-view.js";
import { propDetailsView } from "./views/prop-details-view.js";
import { journalView } from "./views/journal-view.js";
import { editRoomView } from "./views/edit-room-view.js";
import { placeholderView } from "./views/placeholder-view.js";

function coreMarkup(definition, favorite, selected) {
  return `
    <button type="button" class="game-card core ${selected ? "selected" : ""}" data-core-id="${definition.id}"
      aria-label="${escapeHtml(definition.label)}${favorite ? ", favorite" : ""}" aria-pressed="${selected}" title="${escapeHtml(definition.label)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="" loading="lazy">
    </button>
  `;
}

function bindCardButtons(root, onSelect, onAction) {
  root.querySelectorAll("[data-stack-id]").forEach(button => {
    if (button.dataset.skillSlot !== undefined) return;
    button.onclick = () => onSelect({
      kind: button.dataset.scope === "room" ? "room-card" : "inventory-card",
      id: button.dataset.stackId,
    });
  });
  root.querySelectorAll("[data-core-id]").forEach(button => {
    button.onclick = () => onAction({ type: "core-toggle", id: button.dataset.coreId });
  });
  root.querySelectorAll("[data-close-view]").forEach(button => {
    button.onclick = () => onAction({ type: "close-view" });
  });
  root.querySelectorAll("[data-close-details]").forEach(button => {
    button.onclick = () => onAction({ type: "close-details" });
  });
  root.querySelectorAll("[data-skill-slot]").forEach(button => {
    button.onclick = () => onAction({ type: "skill-slot", index: Number(button.dataset.skillSlot), stackId: button.dataset.stackId || "" });
  });
  root.querySelectorAll("[data-friend-action]").forEach(button => {
    button.onclick = () => onAction({ type: "friend-action", action: button.dataset.friendAction, accountId: button.dataset.accountId });
  });
  root.querySelectorAll("[data-claim-bops]").forEach(button => {
    button.onclick = () => onAction({ type: "claim-bops" });
  });
  root.querySelectorAll("[data-level-up]").forEach(button => {
    button.onclick = () => onAction({ type: "level-up" });
  });
  root.querySelectorAll("[data-swap-sticker]").forEach(button => {
    button.onclick = () => onAction({ type: "swap-sticker" });
  });
  root.querySelectorAll("[data-emote-category]").forEach(button => {
    button.onclick = () => onAction({ type: "emote-category", category: button.dataset.emoteCategory });
  });
  root.querySelectorAll("[data-journal-tab]").forEach(button => {
    button.onclick = () => onAction({ type: "journal-tab", tab: button.dataset.journalTab });
  });
  root.querySelectorAll("[data-journal-month]").forEach(button => {
    button.onclick = () => onAction({ type: "journal-month", delta: Number(button.dataset.journalMonth) });
  });
  root.querySelectorAll("[data-prop-command]").forEach(button => {
    button.onclick = () => onAction({ command: button.dataset.propCommand });
  });
}

function boardModal(state) {
  const view = state.views.main;
  if (!view || !state.room) return "";
  if (view === "room") return roomView(state);
  if (view === "inventory") return inventoryView(state);
  if (view === "emotes") return emotesView(state);
  if (view === "skills") return skillsView(state);
  if (view === "friends") return friendsView(state);
  if (view === "self") return selfView(state);
  if (view === "prop-details") return propDetailsView(state);
  if (view === "journal") return journalView(state);
  if (view === "edit-room") return editRoomView(state);
  if (view in PLACEHOLDER_VIEWS) return placeholderView(view);
  return "";
}

function detailsModal(state) {
  const roomCard = findRoomCard(state, state.views.details);
  const inventoryCard = findInventoryCard(state, state.views.details);
  const stack = roomCard || inventoryCard;
  if (!stack) return "";
  return `
    <section class="details-popup" role="dialog" aria-modal="false" aria-label="Card Details: ${escapeHtml(stack.definition.label)}">
      <button type="button" class="quiet details-close" data-close-details="1" aria-label="Close card details">Close</button>
      <div class="details-book">
        <img class="details-front" src="${escapeHtml(stack.definition.imageUrl)}" alt="${escapeHtml(stack.definition.label)} card front">
        <img class="details-back" src="${stack.definition.imageUrl.startsWith("/assets/world/") ? CARD_BACK : "/assets/base/base-pack-back.webp"}" alt="Card back">
        <div class="details-page" tabindex="0" data-details-page="1" aria-label="Card information">
          <h2>${escapeHtml(stack.definition.label)}</h2>
          <p>${escapeHtml(longDescription(stack.definition))}</p>
          <dl class="details-metrics">
            <div><dt>Quantity</dt><dd>${escapeHtml(stack.quantity)}</dd></div>
            <div><dt>Stack limit</dt><dd>${escapeHtml(stack.definition.stackLimit || 1)}</dd></div>
            ${stack.scope ? `<div><dt>Scope</dt><dd>${escapeHtml(stack.scope)}</dd></div>` : ""}
            <div><dt>Pinned</dt><dd>${stack.pinned ? "Yes" : "No"}</dd></div>
            ${inventoryCard ? `<div><dt>Equipped</dt><dd>${stack.equipped ? "Yes" : "No"}</dd></div>` : ""}
          </dl>
        </div>
        <p class="rarity-pill">${escapeHtml(rarityLabel(stack.definition))}</p>
      </div>
    </section>
  `;
}

export function describeSelection(state) {
  if (!state.room) return { tag: "Tinyrooms", title: "Sign in", description: "Create an account or log in to enter the world.", imageUrl: "" };
  const selected = findSelectedEntity(state);
  if (!selected || state.selection.kind === "room") {
    return { tag: "Room", title: state.room.label, description: state.room.description || state.room.note || "Current room.", imageUrl: state.room.board.imageUrl };
  }
  if (state.selection.kind === "core") return { tag: "Core", title: selected.label, description: state.selection.id === "journal" ? "Your tasks and memories. Not available yet." : selected.description, imageUrl: selected.imageUrl };
  if (state.selection.kind === "room-card" || state.selection.kind === "inventory-card") return { tag: rarityLabel(selected.definition), title: selected.definition.label, description: selected.definition.description, imageUrl: selected.definition.imageUrl };
  if (state.selection.kind === "prop") return { tag: "Prop", title: selected.label, description: selected.description, imageUrl: "" };
  if (state.selection.kind === "peep") return { tag: selected.kind === "npc" ? "NPC" : "Peep", title: selected.label, description: selected.description || "A peep in this room.", imageUrl: selected.stickerUrl };
  return { tag: "Selection", title: "Tinyrooms", description: "", imageUrl: "" };
}

export function selectionActions(state) {
  if (!state.room) return [];
  if (state.selection.kind === "room") {
    return [
      { label: "Open Room View", local: { type: "open-view", view: "room" }, tone: "primary" },
      ...state.room.quickActions.map(action => ({
        ...action,
        tone: action.command.startsWith(".go ") ? "positive" : "neutral",
      })),
    ];
  }
  if (state.selection.kind === "core") {
    const definition = state.user?.coreCards?.[state.selection.id];
    if (!definition) return [];
    return [
      { label: state.views.main === state.selection.id ? "Close" : `Open ${definition.label}`, local: { type: "open-view", view: state.selection.id }, tone: "primary" },
      { label: state.user?.favorites?.includes(state.selection.id) ? "Unfavorite" : "Favorite", command: buildFavoriteCommand(state.selection.id), tone: "positive" },
    ];
  }
  if (state.selection.kind === "prop") {
    const prop = findSelectedEntity(state);
    if (!prop) return [];
    return [
      { label: "Inspect", local: { type: "open-view", view: "prop-details" }, tone: "primary" },
      ...prop.quickActions.map(action => ({ ...action, tone: "neutral" })),
    ];
  }
  if (state.selection.kind === "peep") {
    const peep = findSelectedEntity(state);
    if (!peep) return [];
    const actions = (peep.quickActions || []).map(action => ({ ...action, tone: "neutral" }));
    if (state.user && peep.id === state.user.id) {
      actions.unshift({ label: "Open Self", local: { type: "open-view", view: "self" }, tone: "primary" });
      const pinned = (state.user.pinnedPeeps || []).includes(peep.id);
      actions.push({ label: pinned ? "Unpin" : "Pin", command: `.pin_peep @peep:${peep.id}`, tone: "neutral" });
      actions.push({ label: "Swap Sticker…", local: { type: "swap-sticker" }, tone: "positive" });
    } else if (peep.kind === "user") {
      actions.push({ label: "Add Friend", command: `.friend add @peep:${peep.id}`, tone: "positive" });
    }
    return actions;
  }
  if (state.selection.kind === "room-card" || state.selection.kind === "inventory-card") {
    const isRoom = state.selection.kind === "room-card";
    const stack = isRoom ? findRoomCard(state, state.selection.id) : findInventoryCard(state, state.selection.id);
    if (!stack) return [];
    const intent = isRoom ? "pickup" : "drop";
    const quickActions = stack.quickActions || [];
    const actions = [
      { label: "Inspect", local: { type: "open-details", stackId: stack.stackId }, tone: "primary" },
      ...quickActions.flatMap(action => {
        if (action.command.startsWith(`.${intent} `)) {
          const disabled = (isRoom && stack.pinned) || stack.quantity < 1;
          const tone = isRoom ? "positive" : "negative";
          const direct = {
            label: isRoom ? "Pick up 1" : "Drop 1",
            command: action.command,
            tone,
            disabled,
          };
          if (stack.quantity > 1) {
            return [direct, {
              label: isRoom ? "Pick up…" : "Drop…",
              local: { type: "quantity", stackId: stack.stackId, max: stack.quantity, intent },
              tone,
              disabled,
            }];
          }
          return [direct];
        }
        return [{ ...action, tone: "neutral" }];
      }),
    ];
    if (!isRoom) actions.push(...inventoryStackActions(stack));
    return actions;
  }
  return [];
}

function inventoryStackActions(stack) {
  const definition = stack.definition || {};
  const actions = [];
  const type = definition.type || "item";
  if (type === "emote") {
    actions.push({ label: "Play", command: `.emote @card:${stack.stackId}`, tone: "primary" });
  } else if (type === "skill") {
    actions.push({ label: "Slot…", local: { type: "open-view", view: "skills" }, tone: "primary" });
  } else if (type === "item" || type === "action") {
    if (stack.equipped) {
      if (!definition.passive && !definition.decorative) {
        actions.push({ label: "Use", command: `.use @card:${stack.stackId}`, tone: "primary" });
        if ((definition.target || "") === "peep") {
          actions.push({ label: "Use on…", local: { type: "start-targeting", stackId: stack.stackId, label: definition.label }, tone: "positive" });
        }
      }
      actions.push({ label: "Unequip", command: `.unequip @card:${stack.stackId}`, tone: "neutral" });
    } else if (!definition.passive && !definition.decorative) {
      actions.push({ label: "Equip", command: `.equip @card:${stack.stackId}`, tone: "positive" });
    }
  }
  if ((definition.stackLimit || 1) > 1 && stack.quantity > 1) {
    actions.push({
      label: "Split…",
      local: { type: "quantity", stackId: stack.stackId, max: stack.quantity - 1, intent: "split", minimum: 1 },
      tone: "neutral",
    });
  }
  if ((definition.stackLimit || 1) > 1) {
    actions.push({ label: "Merge…", local: { type: "merge", stackId: stack.stackId }, tone: "neutral" });
  }
  return actions;
}

/** Render core cards, equipped/inventory previews, board-modal views, and card details. */
export function createCardsView({ handRoot, panelRoot, detailRoot, onSelect, onAction }) {
  const rendered = new WeakMap();
  function update(root, markup) {
    if (rendered.get(root) === markup) return false;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const identity = active && ["stackId", "coreId", "coreExpand", "closeView", "closeDetails", "detailsPage"]
      .find(key => active.dataset[key] !== undefined);
    const value = identity ? active.dataset[identity] : null;
    const scrollSelector = ".modal-scroll, .board-modal, .details-popup, .details-page, .card-hand-strip, .equipped-hand";
    const scrolls = [...root.querySelectorAll(scrollSelector)]
      .map(element => ({ top: element.scrollTop, left: element.scrollLeft }));
    root.innerHTML = markup;
    rendered.set(root, markup);
    root.querySelectorAll(scrollSelector).forEach((element, index) => {
      element.scrollTop = scrolls[index]?.top || 0;
      element.scrollLeft = scrolls[index]?.left || 0;
    });
    if (identity) {
      [...root.querySelectorAll("button, [data-details-page]")].find(element => element.dataset[identity] === value)?.focus({ preventScroll: true });
    }
    bindCardButtons(root, onSelect, onAction);
    return true;
  }
  return {
    render(state) {
      const coreCards = state.user?.coreCards || {};
      const coreOrder = state.user?.coreOrder?.filter(id => coreCards[id]) || Object.keys(coreCards);
      const favorites = [...new Set(state.user?.favorites || [])].filter(id => coreOrder.includes(id));
      const visibleCore = state.views.coreExpanded
        ? coreOrder
        : favorites;
      const equipped = (state.room?.inventory || []).filter(stack => stack.equipped);
      const expandIcon = state.views.coreExpanded ? coreCards["arrow-left"]?.imageUrl : coreCards["arrow-right"]?.imageUrl;
      const handChanged = update(handRoot, `
        <div class="card-hand-section ${state.views.coreExpanded ? "expanded" : ""}">
          <div class="card-hand-strip" role="group" aria-label="Core cards">
            ${visibleCore.map(id => coreMarkup(coreCards[id], favorites.includes(id), state.views.main === id || state.selection.kind === "core" && state.selection.id === id)).join("")}
          </div>
          <button type="button" class="game-card core-expand" data-core-expand="1" aria-label="${state.views.coreExpanded ? "Collapse core cards" : "Expand core cards"}" aria-expanded="${state.views.coreExpanded}">
            ${expandIcon ? `<img src="${escapeHtml(expandIcon)}" alt="">` : ""}
          </button>
          ${equipped.length ? `<div class="equipped-hand ${state.views.coreExpanded ? "stashed" : ""}" role="group" aria-label="Equipped cards">
            ${equipped.map(stack => tileMarkup(stack.definition, stack, state.selection.kind === "inventory-card" && state.selection.id === stack.stackId, "inventory")).join("")}
          </div>` : ""}
        </div>
      `);
      update(panelRoot, boardModal(state));
      update(detailRoot, detailsModal(state));
      if (handChanged) {
        const expand = handRoot.querySelector("[data-core-expand]");
        if (expand) expand.onclick = () => onAction({ type: "toggle-core" });
      }
    },
  };
}
