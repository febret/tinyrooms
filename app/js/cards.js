import { CARD_BACK } from "./board.js";
import { buildFavoriteCommand } from "./commands.js";
import { findInventoryCard, findRoomCard, findSelectedEntity } from "./state.js";
import { escapeHtml } from "./presentation.js";

function rarityLabel(definition) {
  return definition?.rarity || (definition?.type === "core" ? "Core" : definition?.type ? definition.type : "Card");
}

function longDescription(definition) {
  const lines = [definition?.description || "No description available."];
  if (definition?.category) lines.push(`${definition.category} emote.`);
  if (definition?.rank) lines.push(`Rank: ${definition.rank}.`);
  if (definition?.oneUse) lines.push("One use.");
  if (definition?.passive) lines.push("Passive while equipped or slotted.");
  if (definition?.target) lines.push(`Target: ${definition.target}.`);
  if (definition?.effect) lines.push(`Effect: ${definition.effect}.`);
  if (definition?.amount) lines.push(`Amount: ${definition.amount}.`);
  if (definition?.duration) lines.push(`Duration: ${definition.duration} seconds.`);
  if (definition?.bonuses && Object.keys(definition.bonuses).length) {
    lines.push(`Bonuses: ${Object.entries(definition.bonuses).map(([key, value]) => `${key.replaceAll("_", " ")} ${value > 0 ? "+" : ""}${value}`).join(", ")}.`);
  }
  return lines.join(" ");
}

function tileMarkup(definition, stack, selected, scope) {
  const label = `${definition.label}${stack.quantity > 1 ? `, ${stack.quantity} copies` : ""}${stack.pinned ? ", pinned" : ""}${stack.equipped ? ", equipped" : ""}`;
  return `
    <button type="button" class="game-card ${selected ? "selected" : ""} ${stack.equipped ? "is-equipped" : ""}"
      data-stack-id="${escapeHtml(stack.stackId)}" data-scope="${scope}" aria-label="${escapeHtml(label)}"
      aria-pressed="${selected}" title="${escapeHtml(`${definition.label} · ${rarityLabel(definition)}`)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="" loading="lazy">
      ${stack.quantity > 1 ? `<span class="card-badge quantity-badge" aria-hidden="true">×${escapeHtml(stack.quantity)}</span>` : ""}
      ${stack.pinned ? '<span class="card-badge pin-badge" aria-hidden="true">◆</span>' : ""}
      ${stack.equipped ? '<span class="card-badge equipped-badge" aria-hidden="true">✓</span>' : ""}
    </button>
  `;
}

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
}

function cardsGrid(stacks, scope, selection, emptyText) {
  const kind = scope === "room" ? "room-card" : "inventory-card";
  return `
    <div class="cards-grid">
      ${stacks.length
        ? stacks.map(stack => tileMarkup(stack.definition, stack, selection.kind === kind && selection.id === stack.stackId, scope)).join("")
        : `<div class="empty-state">${emptyText}</div>`}
    </div>
  `;
}

function inventorySection(state, title, predicate) {
  const stacks = state.room?.inventory?.filter(predicate) || [];
  return `
    <section class="inventory-group">
      <header><h3>${escapeHtml(title)}</h3><span>${stacks.length}</span></header>
      ${cardsGrid(stacks, "inventory", state.selection, "Nothing here yet.")}
    </section>
  `;
}

const PLACEHOLDER_VIEWS = {
  skills: ["Skills", "Skill slots are not available yet."],
  journal: ["Journal", "Tasks and memories are not available yet."],
  friends: ["Friends", "Friend lists are not available yet."],
};

function modalShell({ extraClass = "", ariaLabel, title, subtitle = "", body }) {
  return `
    <section class="board-modal ${extraClass}" role="dialog" aria-modal="false" aria-label="${escapeHtml(ariaLabel)}">
      <header class="modal-header">
        <div><h2>${title}</h2>${subtitle}</div>
        <button type="button" class="quiet" data-close-view="1">Close</button>
      </header>
      ${body}
    </section>
  `;
}

function boardModal(state) {
  const view = state.views.main;
  if (!view || !state.room) return "";
  if (view === "room") {
    return modalShell({
      extraClass: "room-view",
      ariaLabel: "Room View",
      title: `You see these in <span>${escapeHtml(state.room.label)}</span>:`,
      subtitle: `<p>${escapeHtml(state.room.description)}</p>`,
      body: cardsGrid(state.room.roomCards, "room", state.selection, "No room cards are visible in this room."),
    });
  }
  if (view === "inventory") {
    return modalShell({
      extraClass: "wide inventory-view",
      ariaLabel: "Inventory",
      title: "Your Inventory",
      subtitle: `<p class="inventory-balance">${escapeHtml(state.user?.bops ?? 0)} Bops</p>`,
      body: `
        <div class="modal-scroll">
          ${inventorySection(state, "Items", stack => stack.definition?.type !== "emote" && stack.definition?.type !== "skill")}
          ${inventorySection(state, "Emotes", stack => stack.definition?.type === "emote")}
          ${inventorySection(state, "Skills", stack => stack.definition?.type === "skill")}
        </div>
      `,
    });
  }
  if (view === "emotes") {
    const emotes = state.room.inventory.filter(stack => stack.definition?.type === "emote");
    return modalShell({
      ariaLabel: "Emotes",
      title: "Your Emotes",
      body: cardsGrid(emotes, "inventory", state.selection, "You do not own any emotes yet."),
    });
  }
  if (view in PLACEHOLDER_VIEWS) {
    const [label, emptyText] = PLACEHOLDER_VIEWS[view];
    return modalShell({
      ariaLabel: label,
      title: `Your ${label}`,
      body: `<div class="empty-state">${emptyText}</div>`,
    });
  }
  if (view === "self") {
    return modalShell({
      extraClass: "self-view",
      ariaLabel: "Self",
      title: escapeHtml(state.user?.username || "You"),
      body: `
        <div class="profile-identity">
          ${state.user?.stickerUrl ? `<img class="profile-sticker" src="${escapeHtml(state.user.stickerUrl)}" alt="${escapeHtml(state.user.username)}'s sticker">` : ""}
          <span class="profile-level">Level ${state.user?.level || 0}${state.user?.level === 0 ? " - Guest" : ""}</span>
        </div>
        <dl class="profile-counters">
          <div><dt>Bops</dt><dd>${state.user?.bops || 0}</dd></div>
          <div><dt>Kudos</dt><dd>${state.user?.kudos || 0}</dd></div>
          <div><dt>Energy</dt><dd>${state.user?.sharedEnergy || 0}</dd></div>
        </dl>
        <p class="profile-location">Remembered room: <strong>${escapeHtml(state.user?.rememberedRoom === state.room.id ? state.room.label : state.user?.rememberedRoom || state.room.label)}</strong></p>
      `,
    });
  }
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
  if (state.selection.kind === "prop" || state.selection.kind === "peep") {
    return findSelectedEntity(state)?.quickActions.map(action => ({ ...action, tone: "neutral" })) || [];
  }
  if (state.selection.kind === "room-card" || state.selection.kind === "inventory-card") {
    const isRoom = state.selection.kind === "room-card";
    const stack = isRoom ? findRoomCard(state, state.selection.id) : findInventoryCard(state, state.selection.id);
    if (!stack) return [];
    const intent = isRoom ? "pickup" : "drop";
    const quickActions = stack.quickActions || [];
    return [
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
  }
  return [];
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
