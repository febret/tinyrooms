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
import { idCardView } from "./views/id-card-view.js";
import { inventoryView } from "./views/inventory-view.js";
import { emoteMenuMarkup } from "./views/emote-menu.js";
import { propDetailsView } from "./views/prop-details-view.js";
import { journalView } from "./views/journal-view.js";
import { phoneView } from "./views/phone-view.js";
import { createEditorDock } from "./editing/editor-dock.js";
import { animateToolbarButtons, captureToolbarButtons } from "./toolbar-animation.js";
import { uiIconMarkup } from "./ui-icons.js";

function coreMarkup(definition, selected) {
  return `
    <button type="button" class="game-card core ${selected ? "selected" : ""}" data-core-id="${escapeHtml(definition.id)}"
      aria-label="${escapeHtml(definition.label)}" aria-pressed="${selected}" title="${escapeHtml(definition.label)}">
      <img src="${escapeHtml(definition.imageUrl)}" alt="">
    </button>
  `;
}

function multiverseButtonMarkup() {
  return `<button type="button" id="multiverse-toggle" class="icon-button toolbar-edit" data-open-multiverse="1" aria-label="Open the Multiverse" title="Open the Multiverse">${uiIconMarkup("multiverse")}</button>`;
}

function bopsBalanceLabel(bops) {
  const value = Math.max(0, Math.floor(Number(bops) || 0));
  if (value >= 1000000) return `${(value / 1000000).toFixed(1).replace(/\.0$/, "")}M`;
  if (value >= 10000) return `${(value / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(value);
}

function bopsButtonMarkup(bops) {
  const balance = Math.max(0, Math.floor(Number(bops) || 0));
  return `<button type="button" id="bops-toggle" class="icon-button toolbar-edit" data-open-shop="cards" aria-label="Open the Shop, ${balance} Bops" title="Open the Shop (${balance} Bops)"><span class="bops-face" aria-hidden="true">${uiIconMarkup("bops")}<span class="bops-number">${bopsBalanceLabel(bops)}</span></span></button>`;
}

function tinymagButtonMarkup() {
  return `<button type="button" id="tinymag-toggle" class="icon-button toolbar-edit" data-open-tinymag="1" aria-label="Open Tiny Mag" title="Open Tiny Mag">${uiIconMarkup("tinymag")}</button>`;
}

function keyringButtonMarkup() {
  return `<button type="button" id="keyring-toggle" class="icon-button toolbar-edit" data-open-keyring="1" aria-label="Open the Keyring" title="Open the Keyring">${uiIconMarkup("keyring")}</button>`;
}

function editButtonMarkup(room, isAdmin, selectedProp, canReviewCutscenes) {
  return [
    room?.canEditRoom
      ? `<button type="button" class="icon-button toolbar-edit" data-edit-room="1" aria-label="Edit Room" title="Edit Room">${uiIconMarkup("edit")}</button>`
      : "",
    isAdmin && selectedProp?.propId
      ? `<button type="button" class="icon-button toolbar-edit" data-edit-prop="${escapeHtml(selectedProp.propId)}" aria-label="Edit Prop" title="Edit Prop">${uiIconMarkup("edit")}</button>`
      : "",
    canReviewCutscenes
      ? `<button type="button" class="icon-button toolbar-edit" data-open-cutscene-catalog="1" aria-label="Open Cutscene Catalog" title="Open Cutscene Catalog">${uiIconMarkup("clapper")}</button>`
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
  root.querySelectorAll("[data-compact-mode]").forEach(button => {
    button.onclick = () => onAction({ type: "toggle-inventory-compact" });
  });
  root.querySelectorAll("[data-level-up]").forEach(button => {
    button.onclick = () => onAction({ type: "level-up" });
  });
  root.querySelectorAll("[data-swap-sticker]").forEach(button => {
    button.onclick = () => onAction({ type: "swap-sticker" });
  });
  root.querySelectorAll("[data-title-slot]").forEach(select => {
    select.onchange = () => onAction({ command: `.title_set ${select.dataset.titleSlot} ${select.value || "none"}` });
  });
  root.querySelectorAll("[data-titles-toggle]").forEach(button => {
    button.onclick = () => onAction({ type: "toggle-titles" });
  });
  root.querySelectorAll("[data-title-crew-save]").forEach(button => {
    button.onclick = () => {
      const scope = button.closest("[data-title-crew]") || root;
      const input = scope.querySelector("[data-title-crew-input]");
      const value = input ? input.value.trim() : "";
      onAction({ command: value ? `.title_crew ${value}` : ".title_crew none" });
    };
  });
  root.querySelectorAll("[data-emote-play]").forEach(button => {
    button.onclick = () => onAction({ type: "play-emote", stackId: button.dataset.emotePlay });
  });
  root.querySelectorAll("[data-journal-tab]").forEach(button => {
    button.onclick = () => onAction({ type: "journal-tab", tab: button.dataset.journalTab });
  });
  root.querySelectorAll("[data-id-flip]").forEach(button => {
    button.onclick = () => onAction({ type: "id-flip" });
  });
  // A sticker URL can 404 (e.g. a custom render that was never persisted).
  // Degrade to the placeholder instead of leaving a broken-image icon, since
  // the decal overlay is a data URL and would otherwise paint on its own.
  root.querySelectorAll("[data-id-photo]").forEach(img => {
    const degrade = () => {
      const frame = img.closest(".id-photo");
      frame?.querySelectorAll("img").forEach(node => node.remove());
      if (frame && !frame.querySelector(".id-photo-placeholder")) {
        const fallback = document.createElement("span");
        fallback.className = "id-photo-placeholder";
        fallback.setAttribute("aria-hidden", "true");
        fallback.textContent = "✦";
        frame.prepend(fallback);
      }
    };
    img.onerror = degrade;
    if (img.complete && img.naturalWidth === 0) degrade();
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
  root.querySelectorAll("[data-phone-key]").forEach(button => {
    button.onclick = () => onAction({ type: "phone-key", key: button.dataset.phoneKey });
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
  if (view === "id") return idCardView(state);
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
  if (state.selection.kind === "core") {
    if (state.selection.id === "id") return { tag: "", title: "ID Card", description: "Your identity and skills.", imageUrl: "" };
    return { tag: "", title: selected.label, description: state.selection.id === "journal" ? "Your tasks and memories." : selected.description, imageUrl: selected.imageUrl };
  }
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
    const identity = active && ["skillSlot", "journalTab", "inventoryTab", "idFlip", "journalMonth", "accountId", "memoryId", "stackId", "coreId", "openMultiverse", "closeView", "compactMode", "titlesToggle", "titleSlot", "titleCrewInput", "titleCrewSave"]
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
      const roomPicker = `<button type="button" id="room-picker-toggle" class="icon-button" aria-label="Look around" title="Look around" aria-haspopup="dialog" aria-controls="room-picker" aria-expanded="${Boolean(state.ui.roomPickerOpen)}">${uiIconMarkup("room-picker")}</button>`;
      update(coreRoot, coreOrder.map(id => coreMarkup(
        coreCards[id],
        state.views.main === id || (state.selection.kind === "core" && state.selection.id === id),
      ) + (id === "inventory" ? `${bopsButtonMarkup(state.user?.bops)}${showMultiverse ? multiverseButtonMarkup() : ""}${roomPicker}` : "")).join(""      ) + (showTinymag ? `${tinymagButtonMarkup()}${keyringButtonMarkup()}` : "") + editButtonMarkup(state.room, isAdmin, selectedProp, canReviewCutscenes));
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
