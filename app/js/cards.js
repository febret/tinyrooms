import { CARD_BACK } from "./board.js";
import {
  buildEmoteCommand,
  buildEquipCommand,
  buildFriendCommand,
  buildPinCommand,
  buildUnequipCommand,
  buildUseCommand,
} from "./commands.js";
import { findInventoryCard, findRoomCard, findSelectedEntity, findTask } from "./state.js";
import { escapeHtml } from "./presentation.js";
import { longDescription, rarityLabel, tileMarkup } from "./views/view-helpers.js";
import { roomView } from "./views/room-view.js";
import { inventoryView } from "./views/inventory-view.js";
import { emotesView } from "./views/emotes-view.js";
import { skillsView } from "./views/skills-view.js";
import { friendsView } from "./views/friends-view.js";
import { selfView } from "./views/self-view.js";
import { propDetailsView } from "./views/prop-details-view.js";
import { journalView } from "./views/journal-view.js";
import { editRoomView } from "./views/edit-room-view.js";
import { shopView } from "./views/shop-view.js";
import { bindEditorLibrary } from "./editing/library-filter.js";
import { availableLibrary } from "./editing/edit-reducer.js";

function coreMarkup(definition, selected) {
  return `
    <button type="button" class="game-card core ${selected ? "selected" : ""}" data-core-id="${escapeHtml(definition.id)}"
      aria-label="${escapeHtml(definition.label)}" aria-pressed="${selected}" title="${escapeHtml(definition.label)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="" loading="lazy">
    </button>
  `;
}

function bindCardButtons(root, onSelect, onAction) {
  root.querySelectorAll("[data-stack-id]").forEach(button => {
    if (button.dataset.skillSlot !== undefined) return;
    if (button.dataset.scope === "emote") {
      button.onclick = () => onAction({ type: "play-emote", stackId: button.dataset.stackId });
      return;
    }
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
  root.querySelectorAll("[data-open-shop]").forEach(button => {
    button.onclick = () => onAction({ type: "open-shop" });
  });
  root.querySelectorAll("[data-close-shop]").forEach(button => {
    button.onclick = () => onAction({ type: "shop-close" });
  });
  root.querySelectorAll("[data-buy-pack]").forEach(button => {
    button.onclick = () => onAction({ type: "buy-pack", packId: button.dataset.buyPack });
  });
  root.querySelectorAll("[data-auto-merge]").forEach(button => {
    button.onclick = () => onAction({ command: ".merge_all" });
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
  root.querySelectorAll("[data-task-id]").forEach(button => {
    button.onclick = () => onSelect({ kind: "task", id: button.dataset.taskId });
  });
  root.querySelectorAll("[data-memory-action]").forEach(button => {
    button.onclick = () => onAction({ type: "memory-action", action: button.dataset.memoryAction, memoryId: button.dataset.memoryId });
  });
  root.querySelectorAll("[data-prop-command]").forEach(button => {
    button.onclick = () => onAction({ command: button.dataset.propCommand });
  });
  root.querySelectorAll("[data-edit-add]").forEach(button => {
    button.onclick = () => onAction({ type: "edit-add", propId: button.dataset.editAdd });
  });
  root.querySelectorAll("[data-edit-action]").forEach(button => {
    button.onclick = () => onAction({
      type: "edit-action",
      action: button.dataset.editAction,
      delta: Number(button.dataset.editDelta || 0),
      factor: Number(button.dataset.editFactor || 1),
    });
  });
  root.querySelectorAll("[data-edit-snap]").forEach(input => {
    input.onchange = () => onAction({ type: "edit-snap", which: input.dataset.editSnap, value: input.checked });
  });
  root.querySelectorAll("[data-edit-palette]").forEach(input => {
    // Commit on `change` (picker dismissed) so re-rendering never closes it mid-pick.
    input.onchange = () => onAction({ type: "edit-palette", index: Number(input.dataset.editPalette), value: input.value });
  });
  root.querySelectorAll("[data-edit-style]").forEach(select => {
    select.onchange = () => onAction({ type: "edit-style", value: select.value });
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
  return "";
}

function detailsModal(state) {
  const roomCard = findRoomCard(state, state.views.details);
  const inventoryCard = findInventoryCard(state, state.views.details);
  const stack = roomCard || inventoryCard;
  if (!stack) return "";
  const definition = stack.definition;
  const backUrl = definition.imageUrl.startsWith("/assets/world/") ? CARD_BACK : "/assets/base/base-pack-back.webp";
  return `
    <section class="card-view" role="dialog" aria-modal="false" aria-label="Card Details: ${escapeHtml(definition.label)}">
      <button type="button" class="quiet card-view-close" data-close-details="1" aria-label="Close card details">Close</button>
      <div class="card-view-panels">
        <section class="card-view-panel card-view-panel-left" aria-label="Card preview">
          <canvas class="card-preview-canvas" data-card-front="${escapeHtml(definition.imageUrl)}" data-card-back="${escapeHtml(backUrl)}"
            data-card-interactive="true" aria-label="${escapeHtml(definition.label)} card. Drag to rotate."></canvas>
        </section>
        <div class="card-view-spine" aria-hidden="true"></div>
        <section class="card-view-panel card-view-panel-right" aria-label="Card information">
          <div class="card-view-info" tabindex="0" data-details-page="1">
            <h2>${escapeHtml(definition.label)}</h2>
            <p>${escapeHtml(longDescription(definition))}</p>
            <dl class="details-metrics">
              <div><dt>Quantity</dt><dd>${escapeHtml(stack.quantity)}</dd></div>
              <div><dt>Stack limit</dt><dd>${escapeHtml(definition.stackLimit || 1)}</dd></div>
              ${stack.scope ? `<div><dt>Scope</dt><dd>${escapeHtml(stack.scope)}</dd></div>` : ""}
              <div><dt>Pinned</dt><dd>${stack.pinned ? "Yes" : "No"}</dd></div>
              ${inventoryCard ? `<div><dt>Equipped</dt><dd>${stack.equipped ? "Yes" : "No"}</dd></div>` : ""}
            </dl>
            <p class="rarity-pill">${escapeHtml(rarityLabel(definition))}</p>
          </div>
        </section>
      </div>
    </section>
  `;
}

export function describeSelection(state) {
  if (!state.room) return { tag: "Tinyrooms", title: "Sign in", description: "Create an account or log in to enter the world.", imageUrl: "" };
  const selected = findSelectedEntity(state);
  const dialog = state.room.dialog;
  if (dialog && state.selection.kind === "peep" && selected?.id === dialog.peepId) {
    return { tag: "Conversation", title: dialog.peepLabel || selected.label, description: dialog.text, imageUrl: selected.stickerUrl };
  }
  if (!selected || state.selection.kind === "room") {
    return { tag: "Room", title: state.room.label, description: state.room.description || state.room.note || "Current room.", imageUrl: state.room.board.imageUrl };
  }
  if (state.selection.kind === "core") return { tag: "Core", title: selected.label, description: state.selection.id === "journal" ? "Your tasks and memories." : selected.description, imageUrl: selected.imageUrl };
  if (state.selection.kind === "task") {
    const done = selected.steps.filter(step => step.complete).length;
    return { tag: selected.scope === "shared" ? "Shared Task" : "Task", title: selected.title, description: selected.description || `${done} of ${selected.steps.length} steps complete.`, imageUrl: "" };
  }
  if (state.selection.kind === "room-card" || state.selection.kind === "inventory-card") return { tag: rarityLabel(selected.definition), title: selected.definition.label, description: selected.definition.description, imageUrl: selected.definition.imageUrl };
  if (state.selection.kind === "prop") return { tag: "Prop", title: selected.label, description: selected.description, imageUrl: "" };
  if (state.selection.kind === "peep") return { tag: selected.kind === "npc" ? "NPC" : "Peep", title: selected.label, description: selected.description || "A peep in this room.", imageUrl: selected.stickerUrl };
  return { tag: "Selection", title: "Tinyrooms", description: "", imageUrl: "" };
}

export function dialogActions(state) {
  const dialog = state.room?.dialog;
  if (!dialog) return [];
  return [
    ...dialog.choices.map(choice => ({
      label: choice.label,
      command: `.dialog ${choice.index}`,
      tone: choice.disabled ? "neutral" : "primary",
      disabled: choice.disabled,
    })),
    { label: "Exit Conversation", command: ".dialog_end", tone: "cancel" },
  ];
}

export function selectionActions(state) {
  if (!state.room) return [];
  const dialog = state.room.dialog;
  if (dialog && state.selection.kind === "peep" && state.selection.id === dialog.peepId) {
    return dialogActions(state);
  }
  if (state.views.main === "journal") {
    const actions = [];
    const task = state.selection.kind === "task" ? findTask(state, state.selection.id) : null;
    if (task) actions.push({ label: "Memories", local: { type: "journal-task-memories", taskId: task.id }, tone: "primary" });
    if (state.ui.journalTab === "Memories") actions.push({ label: "New Memory", local: { type: "new-memory" }, tone: "positive" });
    actions.push({ label: "Close", local: { type: "close-view" }, tone: "cancel" });
    return actions;
  }
  if (state.selection.kind === "room") {
    return [
      { label: "Open Room View", local: { type: "open-view", view: "room" }, tone: "primary" },
      ...(state.room.canEditRoom
        ? [{ label: "Edit Room", local: { type: "open-view", view: "edit-room" }, tone: "neutral" }]
        : []),
      ...state.room.quickActions.map(action => ({
        ...action,
        tone: action.command.startsWith(".go ") ? "positive" : "neutral",
      })),
    ];
  }
  if (state.selection.kind === "core") {
    const definition = state.user?.coreCards?.[state.selection.id];
    if (!definition) {
      return state.views.main === state.selection.id
        ? [{ label: "Close", local: { type: "close-view" }, tone: "cancel" }]
        : [];
    }
    return [
      { label: state.views.main === state.selection.id ? "Close" : `Open ${definition.label}`, local: { type: "open-view", view: state.selection.id }, tone: "primary" },
    ];
  }
  if (state.selection.kind === "prop") {
    const prop = findSelectedEntity(state);
    if (!prop) return [];
    return [
      { label: "Inspect", local: { type: "open-view", view: "prop-details", propId: prop.id }, tone: "primary" },
      ...prop.quickActions.map(action => ({ ...action, tone: "neutral" })),
    ];
  }
  if (state.selection.kind === "peep") {
    const peep = findSelectedEntity(state);
    if (!peep) return [];
    const actions = (peep.quickActions || []).map(action => ({ ...action, tone: "neutral" }));
    if (state.user && peep.id === state.user.id) {
      actions.unshift(
        { label: "Open Self", local: { type: "open-view", view: "self" }, tone: "primary" },
        { label: "Friends", local: { type: "open-view", view: "friends" }, tone: "neutral" },
        { label: "Skills", local: { type: "open-view", view: "skills" }, tone: "neutral", icon: "/assets/base/skills-icon.png" },
      );
      const pinned = (state.user.pinnedPeeps || []).includes(peep.id);
      actions.push({ label: pinned ? "Unpin" : "Pin", command: buildPinCommand(peep.id), tone: "neutral" });
      actions.push({ label: "Swap Sticker…", local: { type: "swap-sticker" }, tone: "positive" });
    } else if (peep.kind === "user") {
      actions.push({ label: "Add Friend", command: buildFriendCommand("add", peep.id), tone: "positive" });
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

export function defaultSelectionAction(state) {
  return selectionActions(state).find(action => action.default === true) || null;
}

function inventoryStackActions(stack) {
  const definition = stack.definition || {};
  const actions = [];
  const type = definition.type || "item";
  if (type === "emote") {
    actions.push({ label: "Play", command: buildEmoteCommand(stack.stackId), tone: "primary" });
  } else if (type === "skill") {
    actions.push({ label: "Slot…", local: { type: "open-view", view: "skills", stackId: stack.stackId }, tone: "primary" });
  } else if (type === "item" || type === "action") {
    if (stack.equipped) {
      if (!definition.passive && !definition.decorative) {
        actions.push({ label: "Use", command: buildUseCommand(stack.stackId), tone: "primary" });
        if ((definition.target || "") === "peep") {
          actions.push({ label: "Use on…", local: { type: "start-targeting", stackId: stack.stackId, label: definition.label }, tone: "positive" });
        }
      }
      actions.push({ label: "Unequip", command: buildUnequipCommand(stack.stackId), tone: "neutral" });
    } else if (!definition.passive && !definition.decorative) {
      actions.push({ label: "Equip", command: buildEquipCommand(stack.stackId), tone: "positive" });
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
  if (definition.sellPrice != null) {
    actions.push({
      label: `Sell 1 (${definition.sellPrice} Bops)`,
      local: { type: "sell", stackId: stack.stackId, quantity: 1, unit: definition.sellPrice, label: definition.label },
      tone: "positive",
    });
    if (stack.quantity > 1) {
      actions.push({
        label: "Sell…",
        local: { type: "sell", stackId: stack.stackId, max: stack.quantity, unit: definition.sellPrice, label: definition.label },
        tone: "positive",
      });
    }
  }
  return actions;
}

/** Render core cards, equipped/inventory previews, board-modal views, and card details. */
export function createCardsView({ handRoot, panelRoot, detailRoot, editorRoot, shopRoot, onSelect, onAction }) {
  const rendered = new WeakMap();
  function update(root, markup) {
    if (rendered.get(root) === markup) return false;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const identity = active && ["stackId", "coreId", "closeView", "closeDetails", "detailsPage", "editSearch"]
      .find(key => active.dataset[key] !== undefined);
    const value = identity ? active.dataset[identity] : null;
    const isTextInput = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");
    const caret = isTextInput ? { start: active.selectionStart, end: active.selectionEnd } : null;
    const scrollSelector = ".modal-scroll, .board-modal, .editor-workspace, .editor-env, .editor-propsets, .editor-heading-tags, .editor-library-grid, .shop-dock-body, .journal-page-inner, .card-view, .card-view-info, .card-hand-strip, .equipped-hand";
    const scrolls = [...root.querySelectorAll(scrollSelector)]
      .map(element => ({ top: element.scrollTop, left: element.scrollLeft }));
    root.innerHTML = markup;
    rendered.set(root, markup);
    root.querySelectorAll(scrollSelector).forEach((element, index) => {
      element.scrollTop = scrolls[index]?.top || 0;
      element.scrollLeft = scrolls[index]?.left || 0;
    });
    if (identity) {
      const restored = [...root.querySelectorAll("button, input, [data-details-page]")]
        .find(element => element.dataset[identity] === value);
      if (restored) {
        restored.focus({ preventScroll: true });
        if (caret && typeof restored.setSelectionRange === "function") {
          try { restored.setSelectionRange(caret.start, caret.end); } catch { /* ignore non-text inputs */ }
        }
      }
    }
    bindCardButtons(root, onSelect, onAction);
    return true;
  }
  return {
    render(state) {
      const coreCards = state.user?.coreCards || {};
      const coreOrder = state.user?.coreOrder?.filter(id => coreCards[id]) || Object.keys(coreCards);
      const equipped = (state.room?.inventory || []).filter(stack => stack.equipped);
      update(handRoot, `
        <div class="card-hand-section">
          <div class="card-hand-strip" role="group" aria-label="Core cards">
            ${coreOrder.map(id => coreMarkup(coreCards[id], state.views.main === id || state.selection.kind === "core" && state.selection.id === id)).join("")}
          </div>
          ${equipped.length ? `<div class="equipped-hand" role="group" aria-label="Equipped cards">
            ${equipped.map(stack => tileMarkup(stack.definition, stack, state.selection.kind === "inventory-card" && state.selection.id === stack.stackId, "inventory")).join("")}
          </div>` : ""}
        </div>
      `);
      update(panelRoot, boardModal(state));
      update(detailRoot, detailsModal(state));
      if (editorRoot) {
        update(editorRoot, state.editor ? editRoomView(state) : "");
        if (state.editor) bindEditorLibrary(editorRoot, availableLibrary(state.editor, state.user?.unlockedProps));
      }
      if (shopRoot) update(shopRoot, state.shop ? shopView(state) : "");
    },
  };
}
