import { api } from "./api.js";
import { clear, el } from "./dom.js";

const POWERS = ["admin", "realtor", "builder", "moderator", "game-master"];

export function createUserManager(container, ctx) {
  const state = { users: [], selectedId: null, detail: null, destination: null, adjusting: false };

  async function load(query = "") {
    const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
    state.users = (await api.get(`/api/mission-control/users${suffix}`)).users;
    render();
  }

  async function openDetail(accountId) {
    state.selectedId = accountId;
    const data = await api.get(`/api/mission-control/users/${accountId}`);
    state.detail = data.user;
    try {
      state.destination = await api.get(`/api/mission-control/users/${accountId}/destination`);
    } catch (error) {
      state.destination = { error: error.message };
    }
    render();
  }

  function render() {
    clear(container);
    container.append(state.selectedId ? renderDetail() : renderList());
  }

  function renderList() {
    const input = el("input", { class: "grow", placeholder: "Search username or id", "aria-label": "Search users" });
    const form = el("form", { class: "row", onsubmit: (event) => { event.preventDefault(); load(input.value.trim()).catch(showError); } }, [
      input,
      el("button", { type: "submit", text: "Search" }),
      el("button", { type: "button", onclick: () => { input.value = ""; load().catch(showError); }, text: "Clear" }),
    ]);
    return el("div", { class: "stack" }, [
      el("div", { class: "row spread" }, [
        el("h2", { text: "User Manager" }),
        el("button", { type: "button", onclick: () => resyncAll(), text: "Resync all instances" }),
      ]),
      el("div", { class: "card" }, [form]),
      el("div", { class: "card" }, [
        el("table", {}, [
          el("thead", {}, el("tr", {}, [
            el("th", { text: "Username" }), el("th", { text: "Level" }), el("th", { text: "Kudos" }),
            el("th", { text: "Bops" }), el("th", { text: "Sticker" }), el("th", { text: "Powers" }),
          ])),
          el("tbody", {}, state.users.map((user) =>
            el("tr", { class: "clickable", onclick: () => openDetail(user.id).catch(showError) }, [
              el("td", { text: user.username }),
              el("td", { text: String(user.level) }),
              el("td", { text: String(user.kudos) }),
              el("td", { text: String(user.bops) }),
              el("td", { text: user.sticker || "—" }),
              el("td", { text: user.powers.join(", ") || "—" }),
            ]),
          )),
        ]),
        state.users.length ? null : el("p", { class: "muted", text: "No accounts match." }),
      ]),
    ]);
  }

  function renderDetail() {
    const detail = state.detail;
    const account = detail.account;
    const form = el("form", { class: "grid cols-2", onsubmit: (event) => saveEdit(event, form, account) }, [
      field("Level", el("input", { name: "level", type: "number", value: account.level })),
      field("Kudos", el("input", { name: "kudos", type: "number", value: account.kudos })),
      field("Bops", el("input", { name: "bops", type: "number", value: account.bops })),
      field("Shared energy", el("input", { name: "shared_energy", type: "number", step: "0.1", value: account.shared_energy })),
      field("Sticker", el("input", { name: "sticker", value: account.sticker || "" })),
      field("Mute minutes (0 to unmute)", el("input", { name: "mute_minutes", type: "number", value: "0" })),
      el("div", { class: "stack" }, [
        el("span", { class: "muted", text: "Powers" }),
        el("div", { class: "row" }, POWERS.map((power) =>
          el("label", { class: "row" }, [
            el("input", { type: "checkbox", name: `power-${power}`, checked: (account.powers || []).includes(power) }),
            el("span", { text: power }),
          ]),
        )),
      ]),
      el("div", { class: "row" }, el("button", { class: "primary", type: "submit", text: "Save changes" })),
    ]);
    return el("div", { class: "stack" }, [
      el("div", { class: "row" }, [
        el("button", { type: "button", onclick: () => { state.selectedId = null; state.detail = null; state.destination = null; render(); }, text: "← Back" }),
        el("h2", { text: account.username_display }),
      ]),
      el("div", { class: "card" }, [el("h3", { text: "Edit" }), form]),
      renderCurrencies(),
      renderInventory(),
      renderDestination(),
      el("div", { class: "card" }, [
        el("h3", { text: "Related rows" }),
        relation("Sessions", detail.sessions.length),
        relation("Inventory stacks", detail.profile_card_stacks.length),
        relation("Reward ledger", detail.reward_ledger.length),
        relation("Pack purchases", detail.pack_purchases.length),
        relation("Task progress", detail.task_progress.length),
        relation("Memories", detail.memories.length),
        relation("Audit entries", detail.audit_log.length),
      ]),
    ]);
  }

  function renderCurrencies() {
    const account = state.detail.account;
    return el("div", { class: "card" }, [
      el("h3", { text: "Currencies" }),
      currencyRow("Kudos", "kudos", account.kudos),
      currencyRow("Bops", "bops", account.bops),
    ]);
  }

  function currencyRow(label, fieldName, value) {
    return el("div", { class: "row spread" }, [
      el("div", { class: "row" }, [
        el("span", { class: "muted", text: label }),
        el("span", { text: String(value) }),
      ]),
      el("div", { class: "row grid-actions" }, [-10, -1, 1, 10].map((delta) =>
        el("button", {
          type: "button",
          onclick: () => quickAdjust(fieldName, delta).catch(showError),
          "aria-label": `${delta > 0 ? "Add" : "Remove"} ${Math.abs(delta)} ${label.toLowerCase()}`,
          text: delta > 0 ? `+${delta}` : String(delta),
        }),
      )),
    ]);
  }

  async function quickAdjust(fieldName, delta) {
    if (state.adjusting) return;
    const account = state.detail.account;
    const next = Number(account[fieldName] || 0) + delta;
    if (next < 0) {
      ctx.setBanner(`${fieldName} cannot go below zero.`);
      return;
    }
    state.adjusting = true;
    try {
      await api.patch(`/api/mission-control/users/${account.id}`, { fields: { [fieldName]: next } });
      await openDetail(account.id);
    } catch (error) {
      ctx.setBanner(error.message);
    } finally {
      state.adjusting = false;
    }
  }

  function renderInventory() {
    const detail = state.detail;
    const stacks = Array.isArray(detail.profile_card_stacks) ? detail.profile_card_stacks : [];
    return el("div", { class: "card" }, [
      el("h3", { text: "Inventory" }),
      stacks.length
        ? el("table", {}, [
            el("thead", {}, el("tr", {}, [
              el("th", { text: "Card" }), el("th", { text: "World" }), el("th", { text: "Qty" }),
              el("th", { text: "Scope" }), el("th", { text: "Flags" }), el("th", { text: "Actions" }),
            ])),
            el("tbody", {}, stacks.map((stack) => stackRow(stack))),
          ])
        : el("p", { class: "muted", text: "No inventory stacks." }),
      renderAddStack(stacks),
    ]);
  }

  function stackRow(stack) {
    const flags = [stack.equipped ? "equipped" : null, stack.pinned ? "pinned" : null].filter(Boolean).join(" · ") || "—";
    const quantityInput = el("input", {
      type: "number",
      min: "1",
      value: String(stack.quantity),
      "aria-label": `Quantity for ${stack.card_def_id}`,
    });
    return el("tr", {}, [
      el("td", { text: stack.card_def_id }),
      el("td", { text: stack.world_id || "all worlds" }),
      el("td", {}, quantityInput),
      el("td", { text: stack.scope }),
      el("td", { class: "muted", text: flags }),
      el("td", {}, el("div", { class: "row grid-actions" }, [
        el("button", {
          type: "button",
          onclick: () => saveStack(stack, quantityInput).catch(showError),
          text: "Update",
        }),
        el("button", {
          type: "button",
          class: "danger",
          onclick: () => deleteStack(stack).catch(showError),
          text: "Delete",
        }),
      ])),
    ]);
  }

  function renderAddStack(stacks) {
    const knownIds = [...new Set(stacks.map((stack) => String(stack.card_def_id || "")))].filter(Boolean).sort();
    const cardInput = el("input", { placeholder: "card id", "aria-label": "Card id", list: "inventory-card-ids" });
    const quantityInput = el("input", { type: "number", min: "1", value: "1", "aria-label": "Quantity" });
    const worldInput = el("input", { placeholder: "world id (blank = all worlds)", "aria-label": "World id" });
    const scopeSelect = el("select", { "aria-label": "Scope" }, [
      el("option", { value: "global", text: "global" }),
      el("option", { value: "world", text: "world" }),
    ]);
    const suggestions = el("datalist", { id: "inventory-card-ids" }, knownIds.map((id) => el("option", { value: id })));
    return el("div", { class: "stack" }, [
      el("span", { class: "muted", text: "Add a stack" }),
      suggestions,
      el("div", { class: "grid cols-2" }, [
        field("Card id", cardInput),
        field("Quantity", quantityInput),
        field("World id (blank = all worlds)", worldInput),
        field("Scope", scopeSelect),
      ]),
      el("div", { class: "row" }, el("button", {
        type: "button",
        class: "primary",
        onclick: () => addStack(cardInput, quantityInput, worldInput, scopeSelect).catch(showError),
        text: "Add stack",
      })),
    ]);
  }

  async function saveStack(stack, quantityInput) {
    const quantity = Number(quantityInput.value);
    if (!Number.isInteger(quantity) || quantity < 1) {
      ctx.setBanner("Quantity must be a whole number of at least 1.");
      return;
    }
    try {
      await api.patch(
        `/api/mission-control/users/${state.selectedId}/inventory/${encodeURIComponent(stack.stack_id)}`,
        { quantity },
      );
      await openDetail(state.selectedId);
      ctx.setBanner("Inventory stack updated.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function deleteStack(stack) {
    if (!window.confirm(`Delete the "${stack.card_def_id}" stack?`)) return;
    try {
      await api.del(`/api/mission-control/users/${state.selectedId}/inventory/${encodeURIComponent(stack.stack_id)}`);
      await openDetail(state.selectedId);
      ctx.setBanner("Inventory stack deleted.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function addStack(cardInput, quantityInput, worldInput, scopeSelect) {
    const cardId = cardInput.value.trim();
    const quantity = Number(quantityInput.value || 1);
    if (!cardId) {
      ctx.setBanner("A card id is required.");
      return;
    }
    try {
      await api.post(`/api/mission-control/users/${state.selectedId}/inventory`, {
        card_def_id: cardId,
        quantity,
        world_id: worldInput.value.trim() || null,
        scope: scopeSelect.value,
      });
      await openDetail(state.selectedId);
      ctx.setBanner("Inventory stack added.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  function renderDestination() {
    const destination = state.destination;
    if (!destination) {
      return el("div", { class: "card" }, [el("h3", { text: "Saved destination" }), el("p", { class: "muted", text: "Loading…" })]);
    }
    if (destination.error) {
      return el("div", { class: "card" }, [
        el("h3", { text: "Saved destination" }),
        el("p", { class: "muted", text: destination.error }),
      ]);
    }
    const saved = destination.saved_instance_id || "—";
    const status = destination.status || (destination.retired ? "retired" : destination.saved_instance_id ? "not registered" : "none");
    const source = destination.saved_instance_id ? saved : "No saved instance";
    const rows = [
      destinationRow("World", destination.world_id || "—"),
      destinationRow("Instance", source),
      destinationRow("Status", status),
    ];
    const candidates = Array.isArray(destination.candidates) ? destination.candidates : [];
    const controls = candidates.length
      ? [
          el("select", { id: "repair-destination" }, candidates.map((candidate) =>
            el("option", {
              value: candidate.instance_id,
              selected: candidate.replacement,
              text: `${candidate.label || candidate.instance_id}${candidate.replacement ? " (replacement)" : ""}`,
            }),
          )),
          el("button", {
            type: "button",
            onclick: () => repairDestination(document.getElementById("repair-destination")).catch(showError),
            text: "Repair destination",
          }),
        ]
      : [el("p", { class: "muted", text: "No running same-world replacement is available." })];
    return el("div", { class: "card" }, [
      el("h3", { text: "Saved destination" }),
      ...rows,
      el("div", { class: "row" }, controls),
    ]);
  }

  function relation(label, value) {
    return destinationRow(label, String(value));
  }

  function destinationRow(label, value) {
    return el("div", { class: "row spread" }, [el("span", { class: "muted", text: label }), el("span", { text: value })]);
  }

  async function repairDestination(select) {
    if (!select || !select.value) return;
    try {
      await api.post(`/api/mission-control/users/${state.selectedId}/destination`, { instance_id: select.value });
      await openDetail(state.selectedId);
      ctx.setBanner("Player destination repaired.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  function field(label, control) {
    return el("label", { class: "stack" }, [el("span", { class: "muted", text: label }), control]);
  }

  async function saveEdit(event, form, account) {
    event.preventDefault();
    const data = new FormData(form);
    const fields = {
      level: Number(data.get("level")),
      kudos: Number(data.get("kudos")),
      bops: Number(data.get("bops")),
      shared_energy: Number(data.get("shared_energy")),
      sticker: data.get("sticker") || null,
      powers: POWERS.filter((power) => data.get(`power-${power}`)),
    };
    const minutes = Number(data.get("mute_minutes") || 0);
    fields.muted = minutes > 0;
    if (minutes > 0) fields.mute_minutes = minutes;
    try {
      await api.patch(`/api/mission-control/users/${account.id}`, { fields });
      await openDetail(account.id);
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function resyncAll() {
    try {
      const data = await api.post("/api/mission-control/resync", {});
      ctx.setBanner(`Resync requested for ${data.results.length} instance(s).`);
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  function showError(error) {
    ctx.setBanner(error.message);
  }

  return {
    activate: () => load().catch(showError),
    deactivate: () => {},
  };
}
