import { CARD_BACK } from "./board.js";
import { cardFaceFields } from "./card-face.js";
import {
  buildEmoteCommand,
  buildEquipCommand,
  buildFriendCommand,
  buildUnequipCommand,
  buildTeachCommand,
  buildUseCommand,
} from "./commands.js";
import { findInventoryCard, findRoomCard, findSelectedEntity, findTask, isTargetableStack } from "./state.js";
import { escapeHtml } from "./presentation.js";
import { handIconMarkup, longDescription, rarityLabel } from "./views/view-helpers.js";
import { inventoryView } from "./views/inventory-view.js";
import { emoteMenuMarkup } from "./views/emote-menu.js";
import { propDetailsView } from "./views/prop-details-view.js";
import { journalView } from "./views/journal-view.js";
import { createEditorDock } from "./editing/editor-dock.js";

function coreMarkup(definition, selected) {
  return `
    <button type="button" class="game-card core ${selected ? "selected" : ""}" data-core-id="${escapeHtml(definition.id)}"
      aria-label="${escapeHtml(definition.label)}" aria-pressed="${selected}" title="${escapeHtml(definition.label)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="">
    </button>
  `;
}

function editButtonMarkup(room, isAdmin, selectedProp) {
  const pencil = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 20h4l10-10-4-4L4 16v4Z"></path><path d="m13 5 4 4"></path></svg>`;
  return [
    room?.canEditRoom
      ? `<button type="button" class="icon-button toolbar-edit" data-edit-room="1" aria-label="Edit Room" title="Edit Room">${pencil}</button>`
      : "",
    isAdmin && selectedProp?.propId
      ? `<button type="button" class="icon-button toolbar-edit" data-edit-prop="${escapeHtml(selectedProp.propId)}" aria-label="Edit Prop" title="Edit Prop">${pencil}</button>`
      : "",
  ].join("");
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
  root.querySelectorAll("[data-edit-room]").forEach(button => {
    button.onclick = () => onAction({ type: "open-view", view: "edit-room" });
  });
  root.querySelectorAll("[data-edit-prop]").forEach(button => {
    button.onclick = () => onAction({ type: "open-prop-editor", propId: button.dataset.editProp });
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
  root.querySelectorAll("[data-beacon-action]").forEach(button => {
    button.onclick = () => onAction({ type: "beacon-action", action: button.dataset.beaconAction, accountId: button.dataset.accountId });
  });
  root.querySelectorAll("[data-beacon-refresh]").forEach(button => {
    button.onclick = () => onAction({ type: "beacon-refresh" });
  });
  root.querySelectorAll("[data-claim-bops]").forEach(button => {
    button.onclick = () => onAction({ type: "claim-bops" });
  });
  root.querySelectorAll("[data-open-shop]").forEach(button => {
    button.onclick = () => onAction({ type: "open-shop", section: button.dataset.openShop || "cards" });
  });
  root.querySelectorAll("[data-auto-merge]").forEach(button => {
    button.onclick = () => onAction({ command: ".merge_all" });
  });
  root.querySelectorAll("[data-sell-mode]").forEach(button => {
    button.onclick = () => onAction({ type: "toggle-sell-mode" });
  });
  root.querySelectorAll("[data-level-up]").forEach(button => {
    button.onclick = () => onAction({ type: "level-up" });
  });
  root.querySelectorAll("[data-swap-sticker]").forEach(button => {
    button.onclick = () => onAction({ type: "swap-sticker" });
  });
  root.querySelectorAll("[data-emote-play]").forEach(button => {
    button.onclick = () => onAction({ type: "play-emote", stackId: button.dataset.emotePlay });
  });
  root.querySelectorAll("[data-journal-tab]").forEach(button => {
    button.onclick = () => onAction({ type: "journal-tab", tab: button.dataset.journalTab });
  });
  root.querySelectorAll("[data-inventory-tab]").forEach(button => {
    button.onclick = () => onAction({ type: "inventory-tab", tab: button.dataset.inventoryTab });
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
}

function boardModal(state) {
  const view = state.views.main;
  if (!view || !state.room) return "";
  if (view === "inventory") return inventoryView(state);
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
  const backUrl = definition.backUrl || CARD_BACK;
  const faceKey = JSON.stringify(cardFaceFields(definition));
  return `
    <section class="card-view" role="dialog" aria-modal="false" aria-label="Card Details: ${escapeHtml(definition.label)}">
      <button type="button" class="quiet card-view-close" data-close-details="1" aria-label="Close card details">Close</button>
      <div class="card-view-panels">
        <section class="card-view-panel card-view-panel-left" aria-label="Card preview">
          <canvas class="card-preview-canvas" data-card-face="${escapeHtml(faceKey)}" data-card-back="${escapeHtml(backUrl)}"
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
  if (state.selection.kind === "core") return { tag: "", title: selected.label, description: state.selection.id === "journal" ? "Your peep, skills, friends, tasks and memories." : selected.description, imageUrl: selected.imageUrl };
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
    if (task && state.ui.journalTab === "Tasks") actions.push({ label: "Memories", local: { type: "journal-task-memories", taskId: task.id }, tone: "primary" });
    if (state.ui.journalTab === "Memories") actions.push({ label: "New Memory", local: { type: "new-memory" }, tone: "positive" });
    return actions;
  }
  if (state.selection.kind === "room") {
    return state.room.quickActions.map(action => ({
      ...action,
      tone: action.command.startsWith(".go ") ? "positive" : "neutral",
    }));
  }
  if (state.selection.kind === "core") {
    const definition = state.user?.coreCards?.[state.selection.id];
    if (!definition || state.views.main === state.selection.id) return [];
    return [
      { label: `Open ${definition.label}`, local: { type: "open-view", view: state.selection.id }, tone: "primary" },
    ];
  }
  if (state.selection.kind === "prop") {
    const prop = findSelectedEntity(state);
    if (!prop) return [];
    return prop.quickActions.filter(action => !/^\.(?:look|inspect)(?:\s|$)/.test(action.command)).map(action => ({ ...action, tone: "neutral" }));
  }
  if (state.selection.kind === "peep") {
    const peep = findSelectedEntity(state);
    if (!peep) return [];
    const isSelf = state.user && peep.id === state.user.id;
    const actions = (peep.quickActions || [])
      .filter(action => !/^\.look(?:\s|$)/.test(action.command))
      .filter(action => !isSelf || !/^\.(?:pin|friend\s+add)(?:\s|$)/.test(action.command))
      .map(action => ({ ...action, tone: "neutral" }));
    if (isSelf) {
      actions.push({ label: "Swap Sticker…", local: { type: "swap-sticker" }, tone: "positive" });
    } else if (peep.kind === "user" && !actions.some(action => action.command === buildFriendCommand("add", peep.id))) {
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

      ...quickActions.filter(action => !/^\.(?:look|inspect)(?:\s|$)/.test(action.command)).flatMap(action => {
        if (action.command.startsWith(`.${intent} `)) {
          const disabled = (isRoom && stack.pinned) || stack.quantity < 1;
          const tone = isRoom ? "positive" : "negative";
          const direct = {
            label: isRoom ? "Pick up 1" : "Drop",
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
  if (type === "pack") {
    actions.push({ label: "Open", local: { type: "open-pack", stackId: stack.stackId }, tone: "primary" });
    return actions;
  }
  const tags = Array.isArray(definition.tags) ? definition.tags : [];
  if (type === "emote") {
    actions.push({ label: "Play", command: buildEmoteCommand(stack.stackId), tone: "primary" });
  } else if (tags.includes("topic")) {
    actions.push({ label: "Teach", command: buildTeachCommand(stack.stackId), tone: "primary" });
    if (stack.equipped) {
      actions.push({ label: "Unequip", command: buildUnequipCommand(stack.stackId), tone: "neutral" });
    } else if (!definition.passive && !definition.decorative) {
      actions.push({ label: "Equip", command: buildEquipCommand(stack.stackId), tone: "positive" });
    }
  } else if (type === "skill") {
    actions.push({ label: "Slot…", local: { type: "open-view", view: "skills", stackId: stack.stackId }, tone: "primary" });
  } else if (type === "item" || type === "action") {
    if (stack.equipped) {
      if (isTargetableStack(stack)) {
        actions.push({ label: "Use", local: { type: "start-targeting", stackId: stack.stackId }, tone: "primary" });
      } else if (definition.effect && !definition.passive && !definition.decorative && (definition.target || "") !== "prop") {
        actions.push({ label: "Use", command: buildUseCommand(stack.stackId), tone: "primary" });
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
  return actions;
}

/** Render core cards, equipped/inventory previews, board-modal views, and card details. */
export function createCardsView({ coreRoot, handRoot, menuRoot, panelRoot, detailRoot, editorRoot, onSelect, onAction }) {
  const editorDock = createEditorDock({ root: editorRoot, onAction });
  const renderEditor = (state, options) => editorDock.render(state, options);
  const rendered = new WeakMap();
  let lastEquippedSelection = null;
  function update(root, markup) {
    if (rendered.get(root) === markup) return false;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const identity = active && ["skillSlot", "journalTab", "inventoryTab", "journalMonth", "accountId", "memoryId", "stackId", "coreId", "closeView", "closeDetails", "detailsPage"]
      .find(key => active.dataset[key] !== undefined);
    const value = identity ? active.dataset[identity] : null;
    const friendAction = active?.dataset.friendAction;
    const isTextInput = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");
    const caret = isTextInput ? { start: active.selectionStart, end: active.selectionEnd } : null;
    const scrollSelector = ".modal-scroll, .board-modal, .journal-page-inner, .card-view, .card-view-info, .emote-menu-track, .equipped-hand";
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
        .find(element => element.dataset[identity] === value && (!friendAction || element.dataset.friendAction === friendAction));
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
    renderEditor,
    render(state) {
      const coreCards = state.user?.coreCards || {};
      // Emotes moved beside the chat bar, so the top toolbar carries the remaining
      // core controls (inventory and journal) in their authored order.
      const coreOrder = (state.user?.coreOrder?.filter(id => coreCards[id]) || Object.keys(coreCards))
        .filter(id => id !== "emotes");
      const selectedProp = state.selection.kind === "prop" ? findSelectedEntity(state) : null;
      const isAdmin = (state.user?.powers || []).includes("admin");
      const equipped = (state.room?.inventory || []).filter(stack => stack.equipped);
      update(coreRoot, coreOrder.map(id => coreMarkup(
        coreCards[id],
        state.views.main === id || (state.selection.kind === "core" && state.selection.id === id),
      ) + (id === "inventory" ? `<button type="button" id="room-picker-toggle" class="icon-button" aria-label="Look around" title="Look around" aria-haspopup="dialog" aria-controls="room-picker" aria-expanded="${Boolean(state.ui.roomPickerOpen)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="6"></circle><path d="m15 15 6 6"></path></svg></button>` : "")).join("") + editButtonMarkup(state.room, isAdmin, selectedProp));
      const handChanged = update(handRoot, equipped.length ? `<div class="equipped-hand" role="group" aria-label="Equipped cards" style="--equipped-count:${equipped.length}">
        ${equipped.map(stack => handIconMarkup(stack.definition, stack)).join("")}
      </div>` : "");
      const equippedSelection = state.selection.kind === "inventory-card" ? state.selection.id : null;
      if (handChanged || equippedSelection !== lastEquippedSelection) {
        handRoot.querySelectorAll(".equipped-hand [data-stack-id]").forEach(button => {
          const selected = equippedSelection === button.dataset.stackId;
          if (button.classList.contains("selected") !== selected) button.classList.toggle("selected", selected);
          if (button.getAttribute("aria-pressed") !== String(selected)) button.setAttribute("aria-pressed", String(selected));
        });
        lastEquippedSelection = equippedSelection;
      }
      if (menuRoot) {
        update(menuRoot, state.room ? emoteMenuMarkup(state) : "");
        const open = Boolean(state.room && state.ui.emoteMenuOpen);
        if (menuRoot.classList.contains("open") !== open) menuRoot.classList.toggle("open", open);
      }
      update(panelRoot, boardModal(state));
      update(detailRoot, detailsModal(state));
      renderEditor(state);
    },
  };
}
