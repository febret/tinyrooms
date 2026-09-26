import { COMMANDS } from "./commands.js";
import { escapeHtml, updateMarkup } from "./presentation.js";

const MAX_ITEMS = 9;

const KIND_LABELS = {
  peep: "Peep",
  card: "Card",
  prop: "Prop",
  way: "Way",
  memory: "Memory",
};

const KIND_SUMMARIES = {
  peep: "A peep in this room.",
  card: "A card in this room or your inventory.",
  prop: "A prop in this room.",
  way: "An exit from this room.",
  memory: "A memory from your journal.",
};

/** Return the whitespace-delimited token that contains the caret. */
export function activeToken(text, caret) {
  const value = String(text ?? "");
  const end = Math.max(0, Math.min(Number(caret ?? value.length), value.length));
  let start = end;
  while (start > 0 && !/\s/.test(value[start - 1])) start -= 1;
  return { start, end, token: value.slice(start, end) };
}

function normalizeCommand(command) {
  const rawName = String(command?.name || "").trim();
  const [name] = rawName.split(/\s+/);
  const usage = String(command?.usage || "").trim() || rawName;
  return {
    name,
    usage,
    summary: String(command?.summary || ""),
    power: command?.power ? String(command.power) : null,
  };
}

/** Build command-name completions from the catalog for the typed prefix. */
export function commandCompletions(catalog, powers, prefix) {
  const query = String(prefix || "").replace(/^\./, "").toLowerCase();
  const allowed = powers instanceof Set ? powers : new Set(powers || []);
  const seen = new Set();
  const items = [];
  for (const raw of catalog || []) {
    const command = normalizeCommand(raw);
    if (!command.name.startsWith(".")) continue;
    if (command.power && !allowed.has(command.power)) continue;
    if (!command.name.slice(1).toLowerCase().startsWith(query)) continue;
    if (seen.has(command.name)) continue;
    seen.add(command.name);
    items.push({
      kind: "command",
      insert: `${command.name} `,
      label: command.name,
      detail: command.usage === command.name ? "" : command.usage,
      summary: command.summary,
    });
  }
  return items.slice(0, MAX_ITEMS);
}

function truncate(text, length) {
  const value = String(text || "");
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function candidateKind(state, kind) {
  const room = state.room || {};
  if (kind === "peep") {
    return [
      ...(room.occupants || []).map(occupant => ({
        token: `@peep:${occupant.id}`,
        value: occupant.id,
        label: occupant.username,
        summary: occupant.description || "Peep in this room",
      })),
      ...(room.npcs || []).map(npc => ({
        token: `@peep:${npc.id}`,
        value: npc.id,
        label: npc.label,
        summary: npc.description || "Peep in this room",
      })),
    ];
  }
  if (kind === "card") {
    return [
      ...(room.roomCards || []).map(card => ({
        token: `@card:${card.stackId}`,
        value: card.stackId,
        label: card.definition?.label || card.stackId,
        summary: "Card in this room",
      })),
      ...(room.inventory || []).map(card => ({
        token: `@card:${card.stackId}`,
        value: card.stackId,
        label: card.definition?.label || card.stackId,
        summary: "Card in your inventory",
      })),
    ];
  }
  if (kind === "prop") {
    return (room.props || []).map(prop => ({
      token: `@prop:${prop.id}`,
      value: prop.id,
      label: prop.label,
      summary: prop.description || "Prop in this room",
    }));
  }
  if (kind === "way") {
    return (room.exits || []).map(exit => ({
      token: `@way:${exit.id}`,
      value: exit.id,
      label: exit.label || exit.id,
      summary: exit.targetRoomId ? `To ${exit.targetRoomId}` : "Exit from this room",
    }));
  }
  if (kind === "memory") {
    return (state.user?.journal?.memories || []).map(memory => ({
      token: `@memory:${memory.memoryId}`,
      value: memory.memoryId,
      label: memory.text ? truncate(memory.text, 40) : memory.memoryId,
      summary: memory.author ? `By ${memory.author}` : "Memory from your journal",
    }));
  }
  return [];
}

function peepMentions(state) {
  const room = state.room || {};
  return [
    ...(room.occupants || []).map(occupant => ({
      token: `@${occupant.username}`,
      value: occupant.username,
      label: occupant.label,
      summary: "Mention peep",
    })),
    ...(room.npcs || []).map(npc => ({
      token: `@${npc.id}`,
      value: npc.id,
      label: npc.label,
      summary: "Mention peep",
    })),
  ];
}

function matchesValue(candidate, query) {
  const needle = query.toLowerCase();
  return candidate.value.toLowerCase().startsWith(needle) || candidate.label.toLowerCase().startsWith(needle);
}

function dedupe(items) {
  const seen = new Set();
  const result = [];
  for (const item of items) {
    if (seen.has(item.insert)) continue;
    seen.add(item.insert);
    result.push(item);
  }
  return result;
}

/** Build identifier completions for an `@` token. */
export function identifierCompletions(state, token) {
  const body = String(token || "").slice(1);
  const colon = body.indexOf(":");
  const kindQuery = (colon >= 0 ? body.slice(0, colon) : body).toLowerCase();
  const valueQuery = colon >= 0 ? body.slice(colon + 1) : "";
  const kinds = Object.keys(KIND_LABELS);

  if (colon < 0) {
    const items = kinds
      .filter(kind => kind.startsWith(kindQuery))
      .map(kind => ({
        kind: "kind",
        insert: `@${kind}:`,
        label: `@${kind}:`,
        detail: KIND_LABELS[kind],
        summary: KIND_SUMMARIES[kind],
      }));
    for (const mention of peepMentions(state)) {
      if (!kindQuery || mention.value.toLowerCase().startsWith(kindQuery) || mention.label.toLowerCase().startsWith(kindQuery)) {
        items.push({
          kind: "mention",
          insert: `${mention.token} `,
          label: mention.token,
          detail: mention.label === mention.value ? "" : mention.label,
          summary: mention.summary,
        });
      }
    }
    return dedupe(items).slice(0, MAX_ITEMS);
  }

  const resolved = kinds.find(kind => kind === kindQuery);
  if (!resolved) return [];
  const items = candidateKind(state, resolved)
    .filter(candidate => !valueQuery || matchesValue(candidate, valueQuery))
    .map(candidate => ({
      kind: "value",
      insert: `${candidate.token} `,
      label: candidate.label,
      detail: candidate.value,
      summary: candidate.summary,
    }));
  return dedupe(items).slice(0, MAX_ITEMS);
}

function completionFor(state, value, caret) {
  const token = activeToken(value, caret);
  const powers = new Set(state.user?.powers || []);
  const catalog = state.commandCatalog?.length ? state.commandCatalog : COMMANDS;
  if (token.start === 0 && token.token.startsWith(".")) {
    return { items: commandCompletions(catalog, powers, token.token.slice(1)), range: token };
  }
  if (token.token.startsWith("@")) {
    return { items: identifierCompletions(state, token.token), range: token };
  }
  return { items: [], range: token };
}

/** Attach the `.`/`@` completion popup to the chat input. */
export function createChatAutocomplete({ form, input, store, requestCatalog }) {
  const list = form.querySelector("#chat-completions");
  const controller = { items: [], active: -1, open: false, range: null, requested: false };

  function optionId(index) {
    return `chat-completion-${index}`;
  }

  function close() {
    controller.open = false;
    controller.active = -1;
    controller.items = [];
    controller.range = null;
    list.hidden = true;
    updateMarkup(list, "");
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
  }

  function render() {
    controller.open = true;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    if (controller.active >= 0) input.setAttribute("aria-activedescendant", optionId(controller.active));
    else input.removeAttribute("aria-activedescendant");
    const changed = updateMarkup(list, controller.items.map((item, index) => {
      const active = index === controller.active ? " active" : "";
      const detail = item.detail ? `<code>${escapeHtml(item.detail)}</code>` : "";
      const summary = item.summary ? `<span>${escapeHtml(item.summary)}</span>` : "";
      return `<button type="button" class="chat-completion${active}" id="${optionId(index)}" role="option" aria-selected="${index === controller.active}" data-index="${index}"><strong>${escapeHtml(item.label)}</strong>${detail}${summary}</button>`;
    }).join(""));
    if (!changed) return;
    list.querySelectorAll(".chat-completion").forEach(button => {
      button.onpointerdown = event => {
        event.preventDefault();
        accept(Number(button.dataset.index));
      };
    });
  }

  function refresh() {
    const { items, range } = completionFor(store.getState(), input.value, input.selectionStart ?? input.value.length);
    controller.items = items;
    controller.range = range;
    if (!items.length) {
      close();
      return;
    }
    if (controller.active >= items.length) controller.active = items.length - 1;
    render();
  }

  function accept(index) {
    const item = controller.items[index];
    if (!item || !controller.range) return;
    const value = input.value;
    const before = value.slice(0, controller.range.start);
    const after = value.slice(controller.range.end);
    input.value = `${before}${item.insert}${after}`;
    const caret = before.length + item.insert.length;
    input.setSelectionRange(caret, caret);
    input.focus();
    controller.active = -1;
    if (item.insert.endsWith(":")) {
      refresh();
    } else {
      close();
    }
  }

  function ensureCatalog() {
    if (controller.requested) return;
    const state = store.getState();
    if (!state.loggedIn || !state.transport?.connected || state.commandCatalog?.length) return;
    controller.requested = true;
    Promise.resolve(requestCatalog?.()).catch(() => { controller.requested = false; });
  }

  input.addEventListener("input", () => {
    controller.active = -1;
    refresh();
    ensureCatalog();
  });

  input.addEventListener("keydown", event => {
    if (event.key === "Enter" || event.key === "Tab") {
      if (controller.open && controller.active >= 0) {
        event.preventDefault();
        accept(controller.active);
      }
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!controller.items.length) return;
      event.preventDefault();
      const size = controller.items.length;
      if (event.key === "ArrowDown") controller.active = controller.active < 0 ? 0 : (controller.active + 1) % size;
      else controller.active = controller.active < 0 ? size - 1 : (controller.active - 1 + size) % size;
      render();
      return;
    }
    if (event.key === "Escape" && controller.open) {
      event.preventDefault();
      event.stopPropagation();
      close();
    }
  });

  input.addEventListener("blur", () => close());

  store.subscribe(() => {
    if (controller.open) refresh();
  });

  return { refresh, close };
}
