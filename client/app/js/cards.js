import {
  buildEmoteCommand,
  buildEquipCommand,
  buildFriendCommand,
  buildUnequipCommand,
  buildTeachCommand,
  buildUseCommand,
} from "./commands.js";
import { findInventoryCard, findRoomCard, findSelectedEntity, findTask, hasSlottedSkill, isTargetableStack } from "./state.js";
import { escapeHtml } from "./presentation.js";
import { handIconMarkup, rarityLabel } from "./views/view-helpers.js";
import { inventoryView } from "./views/inventory-view.js";
import { emoteMenuMarkup } from "./views/emote-menu.js";
import { propDetailsView } from "./views/prop-details-view.js";
import { journalView } from "./views/journal-view.js";
import { phoneView } from "./views/phone-view.js";
import { createEditorDock } from "./editing/editor-dock.js";
import { animateToolbarButtons, captureToolbarButtons } from "./toolbar-animation.js";

function coreMarkup(definition, selected) {
  return `
    <button type="button" class="game-card core ${selected ? "selected" : ""}" data-core-id="${escapeHtml(definition.id)}"
      aria-label="${escapeHtml(definition.label)}" aria-pressed="${selected}" title="${escapeHtml(definition.label)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="">
    </button>
  `;
}

function multiverseButtonMarkup() {
  return `<button type="button" id="multiverse-toggle" class="icon-button toolbar-edit" data-open-multiverse="1" aria-label="Open the Multiverse" title="Open the Multiverse"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M12 3a9 9 0 1 0 8.2 5.3c-1.5 2.7-4.3 4.6-7.6 4.6a5.9 5.9 0 0 1-5.9-5.9c0-2.2 1.2-4.1 3-5.1"></path><path d="M12 7a5 5 0 1 0 4.2 7.7c-1.1 1.4-2.8 2.3-4.7 2.3a3.9 3.9 0 0 1-3.9-3.9c0-1.5.8-2.8 2-3.5"></path><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"></circle></svg></button>`;
}

function tinymagButtonMarkup() {
  return `<button type="button" id="tinymag-toggle" class="icon-button toolbar-edit" data-open-tinymag="1" aria-label="Open Tiny Mag" title="Open Tiny Mag"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v16H6.5A2.5 2.5 0 0 0 4 21.5z"></path><path d="M4 18.5A2.5 2.5 0 0 1 6.5 16H20"></path><path d="M9 7h6M9 10h5"></path></svg></button>`;
}

function keyringButtonMarkup() {
  return `<button type="button" id="keyring-toggle" class="icon-button toolbar-edit" data-open-keyring="1" aria-label="Open the Keyring" title="Open the Keyring"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="8" r="4"></circle><path d="m11.2 11.2 7.3 7.3"></path><path d="m16.4 13.4 2-2"></path><path d="m18.6 15.6 2-2"></path></svg></button>`;
}

function editButtonMarkup(room, isAdmin, selectedProp, canReviewCutscenes) {
  const pencil = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M4 20h4l10-10-4-4L4 16v4Z"></path><path d="m13 5 4 4"></path></svg>`;
  const clapper = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 8.5 4.5 4h15L18 8.5"></path><path d="m7 4 2.5 4.5M12 4l2.5 4.5M17 4l2.5 4.5"></path><rect x="3" y="8.5" width="18" height="12" rx="2"></rect><path d="M10 12.5v5M14 12.5v5"></path></svg>`;
  return [
    room?.canEditRoom
      ? `<button type="button" class="icon-button toolbar-edit" data-edit-room="1" aria-label="Edit Room" title="Edit Room">${pencil}</button>`
      : "",
    isAdmin && selectedProp?.propId
      ? `<button type="button" class="icon-button toolbar-edit" data-edit-prop="${escapeHtml(selectedProp.propId)}" aria-label="Edit Prop" title="Edit Prop">${pencil}</button>`
      : "",
    canReviewCutscenes
      ? `<button type="button" class="icon-button toolbar-edit" data-open-cutscene-catalog="1" aria-label="Open Cutscene Catalog" title="Open Cutscene Catalog">${clapper}</button>`
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
  root.querySelectorAll("[data-open-multiverse]").forEach(button => {
    button.onclick = () => onAction({ command: ".play multiverse" });
  });
  root.querySelectorAll("[data-open-tinymag]").forEach(button => {
    button.onclick = () => onAction({ command: ".tinytown open" });
  });
  root.querySelectorAll("[data-open-keyring]").forEach(button => {
    button.onclick = () => onAction({ command: ".tinytown keyring" });
  });
  root.querySelectorAll("[data-edit-room]").forEach(button => {
    button.onclick = () => onAction({ type: "open-view", view: "edit-room" });
  });
  root.querySelectorAll("[data-edit-prop]").forEach(button => {
    button.onclick = () => onAction({ type: "open-prop-editor", propId: button.dataset.editProp });
  });
  root.querySelectorAll("[data-open-cutscene-catalog]").forEach(button => {
    button.onclick = () => onAction({ type: "open-cutscene-catalog" });
  });
  root.querySelectorAll("[data-close-view]").forEach(button => {
    button.onclick = () => onAction({ type: "close-view" });
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
  root.querySelectorAll("[data-phone-app]").forEach(button => {
    button.onclick = () => onAction({ type: "phone-app", app: button.dataset.phoneApp });
  });
  root.querySelectorAll("[data-phone-home]").forEach(button => {
    button.onclick = () => onAction({ type: "phone-home" });
  });
  root.querySelectorAll("[data-phone-music-action]").forEach(button => {
    button.onclick = () => onAction({
      type: "phone-music",
      action: button.dataset.phoneMusicAction,
      mode: button.dataset.mode,
      path: button.dataset.phoneMusicPath,
      song: button.dataset.song,
      label: button.dataset.label,
    });
  });
  root.querySelectorAll("form[data-phone-music-search]").forEach(form => {
    form.onsubmit = event => {
      event.preventDefault();
      const query = String(new FormData(form).get("query") || "").trim();
      if (query) onAction({ type: "phone-music", action: "search", query });
    };
  });
}

function boardModal(state) {
  const view = state.views.main;
  if (!view || !state.room) return "";
  if (view === "inventory") return inventoryView(state);
  if (view === "prop-details") return propDetailsView(state);
  if (view === "journal") return journalView(state);
  if (view === "phone") return phoneView(state);
  return "";
}

export function describeSelection(state) {
  if (!state.room) return { tag: "Tinyrooms", title: "Sign in", description: "Create an account or log in to enter the world.", imageUrl: "" };
  const selected = findSelectedEntity(state);
  if (!selected || state.selection.kind === "room") {
    const gameStatus = typeof state.room.board?.state?.status === "string" ? state.room.board.state.status : "";
    const description = [gameStatus, state.room.description || state.room.note || "Current room."].filter(Boolean).join("\n\n");
    return { tag: "Room", title: state.room.label, description, imageUrl: state.room.board.imageUrl };
  }
  if (state.selection.kind === "core") return { tag: "", title: selected.label, description: state.selection.id === "journal" ? "Your peep, skills, friends, tasks and memories." : selected.description, imageUrl: selected.imageUrl };
  if (state.selection.kind === "task") {
    const done = selected.steps.filter(step => step.complete).length;
    return { tag: selected.scope === "shared" ? "Shared Task" : "Task", title: selected.title, description: selected.description || `${done} of ${selected.steps.length} steps complete.`, imageUrl: "" };
  }
  if (state.selection.kind === "room-card" || state.selection.kind === "inventory-card") return { tag: rarityLabel(selected.definition), title: selected.definition.label, description: selected.definition.description, imageUrl: selected.definition.imageUrl };
  if (state.selection.kind === "prop") return { tag: "Prop", title: selected.label, description: selected.description, imageUrl: "" };
  if (state.selection.kind === "peep") {
    const parts = [selected.description || "A peep in this room."];
    const toward = selected.vibes?.toward?.label;
    const from = selected.vibes?.from?.label;
    if (toward || from) {
      parts.push(`Vibes — You: ${toward || "Neutral 😐"}${from ? ` · Them: ${from}` : ""}`);
    }
    return { tag: selected.kind === "npc" ? "NPC" : "Peep", title: selected.label, description: parts.join(" "), imageUrl: selected.stickerUrl };
  }
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
    const dropDisabled = !isRoom && state.room?.board?.type === "diorama";
    const cardSound = stack.definition?.sounds?.select || "";
    const quickActions = stack.quickActions || [];
    const actions = [

      ...quickActions.filter(action => !/^\.(?:look|inspect)(?:\s|$)/.test(action.command)).flatMap(action => {
        if (action.command.startsWith(`.${intent} `)) {
          if (dropDisabled) return [];
          const disabled = (isRoom && stack.pinned) || stack.quantity < 1;
          const tone = isRoom ? "positive" : "negative";
          const direct = {
            label: isRoom ? "Pick up 1" : "Drop",
            ...(isRoom
              ? { command: action.command }
              : { local: { type: "start-drop", stackId: stack.stackId, quantity: 1 } }),
            tone,
            disabled,
            ...(cardSound ? { sound: cardSound } : {}),
          };
          if (stack.quantity > 1) {
            return [direct, {
              label: isRoom ? "Pick up…" : "Drop…",
              local: { type: "quantity", stackId: stack.stackId, max: stack.quantity, intent },
              tone,
              disabled,
              ...(cardSound ? { sound: cardSound } : {}),
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
  const useSound = definition.sounds?.use || "";
  const selectSound = definition.sounds?.select || useSound;
  const soundOption = useSound ? { sound: useSound } : {};
  const selectOption = selectSound ? { sound: selectSound } : {};
  if (type === "pack") {
    actions.push({ label: "Open", local: { type: "open-pack", stackId: stack.stackId }, tone: "primary", ...soundOption });
    return actions;
  }
  const tags = Array.isArray(definition.tags) ? definition.tags : [];
  if (type === "emote") {
    actions.push({ label: "Play", command: buildEmoteCommand(stack.stackId), tone: "primary", ...soundOption });
  } else if (tags.includes("topic")) {
    actions.push({ label: "Teach", command: buildTeachCommand(stack.stackId), tone: "primary", ...soundOption });
    if (stack.equipped) {
      actions.push({ label: "Unequip", command: buildUnequipCommand(stack.stackId), tone: "neutral", ...selectOption });
    } else if (!definition.passive && !definition.decorative) {
      actions.push({ label: "Equip", command: buildEquipCommand(stack.stackId), tone: "positive", ...selectOption });
    }
  } else if (type === "skill") {
    actions.push({ label: "Slot…", local: { type: "open-view", view: "skills", stackId: stack.stackId }, tone: "primary", ...selectOption });
  } else if (type === "item" || type === "action") {
    if (!definition.passive && !definition.decorative) {
      if (isTargetableStack(stack)) {
        actions.push({ label: "Use", local: { type: "start-targeting", stackId: stack.stackId }, tone: "primary", ...soundOption });
      } else if (definition.effect && (definition.target || "") !== "prop") {
        actions.push({ label: "Use", command: buildUseCommand(stack.stackId), tone: "primary", ...soundOption });
      }
    }
    if (stack.equipped) {
      actions.push({ label: "Unequip", command: buildUnequipCommand(stack.stackId), tone: "neutral", ...selectOption });
    } else if (!definition.passive && !definition.decorative) {
      actions.push({ label: "Equip", command: buildEquipCommand(stack.stackId), tone: "positive", ...selectOption });
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

/** Render core cards, equipped/inventory previews, board-modal views, and the editor dock. */
export function createCardsView({ coreRoot, handRoot, menuRoot, panelRoot, editorRoot, onSelect, onAction }) {
  const editorDock = createEditorDock({ root: editorRoot, onAction });
  const renderEditor = (state, options) => editorDock.render(state, options);
  const rendered = new WeakMap();
  let lastEquippedSelection = null;
  let toolbarReady = false;
  function update(root, markup) {
    if (rendered.get(root) === markup) return false;
    const animateToolbar = root === coreRoot && toolbarReady;
    const previousToolbar = animateToolbar ? captureToolbarButtons(root) : null;
    const active = root.contains(document.activeElement) ? document.activeElement : null;
    const identity = active && ["skillSlot", "journalTab", "inventoryTab", "journalMonth", "accountId", "memoryId", "stackId", "coreId", "openMultiverse", "closeView"]
      .find(key => active.dataset[key] !== undefined);
    const value = identity ? active.dataset[identity] : null;
    const friendAction = active?.dataset.friendAction;
    const isTextInput = active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA");
    const caret = isTextInput ? { start: active.selectionStart, end: active.selectionEnd } : null;
    const scrollSelector = ".modal-scroll, .board-modal, .journal-page-inner, .emote-menu-track, .equipped-hand";
    const scrolls = [...root.querySelectorAll(scrollSelector)]
      .map(element => ({ top: element.scrollTop, left: element.scrollLeft }));
    root.innerHTML = markup;
    rendered.set(root, markup);
    root.querySelectorAll(scrollSelector).forEach((element, index) => {
      element.scrollTop = scrolls[index]?.top || 0;
      element.scrollLeft = scrolls[index]?.left || 0;
    });
    if (identity) {
      const restored = [...root.querySelectorAll("button, input")]
        .find(element => element.dataset[identity] === value && (!friendAction || element.dataset.friendAction === friendAction));
      if (restored) {
        restored.focus({ preventScroll: true });
        if (caret && typeof restored.setSelectionRange === "function") {
          try { restored.setSelectionRange(caret.start, caret.end); } catch { /* ignore non-text inputs */ }
        }
      }
    }
    bindCardButtons(root, onSelect, onAction);
    if (previousToolbar) animateToolbarButtons(root, previousToolbar);
    if (root === coreRoot && root.childElementCount > 0) toolbarReady = true;
    return true;
  }
  return {
    renderEditor,
    render(state) {
      const coreCards = state.user?.coreCards || {};
      // Emotes moved beside the chat bar, so the top toolbar carries the remaining
      // core controls (inventory, phone, and journal) in their authored order.
      const coreOrder = (state.user?.coreOrder?.filter(id => coreCards[id]) || Object.keys(coreCards))
        .filter(id => id !== "emotes");
      const selectedProp = state.selection.kind === "prop" ? findSelectedEntity(state) : null;
      const isAdmin = (state.user?.powers || []).includes("admin");
      const canReviewCutscenes = (state.user?.powers || []).some(power => power === "admin" || power === "game-master");
      const showMultiverse = isAdmin || hasSlottedSkill(state, "multiverse-map");
      const showTinymag = state.user?.worldId === "tinytown";
      const equipped = (state.room?.inventory || []).filter(stack => stack.equipped);
      const roomPicker = `<button type="button" id="room-picker-toggle" class="icon-button" aria-label="Look around" title="Look around" aria-haspopup="dialog" aria-controls="room-picker" aria-expanded="${Boolean(state.ui.roomPickerOpen)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><circle cx="10" cy="10" r="6"></circle><path d="m15 15 6 6"></path></svg></button>`;
      update(coreRoot, coreOrder.map(id => coreMarkup(
        coreCards[id],
        state.views.main === id || (state.selection.kind === "core" && state.selection.id === id),
      ) + (id === "inventory" ? `${showMultiverse ? multiverseButtonMarkup() : ""}${roomPicker}` : "")).join(""      ) + (showTinymag ? `${tinymagButtonMarkup()}${keyringButtonMarkup()}` : "") + editButtonMarkup(state.room, isAdmin, selectedProp, canReviewCutscenes));
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
      renderEditor(state);
    },
  };
}
