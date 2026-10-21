import { api } from "./api.js";
import { clear, el } from "./dom.js";

const POWERS = ["admin", "realtor", "builder", "moderator", "game-master"];

export function createUserManager(container, ctx) {
  const state = { users: [], selectedId: null, detail: null };

  async function load(query = "") {
    const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
    state.users = (await api.get(`/api/mission-control/users${suffix}`)).users;
    render();
  }

  async function openDetail(accountId) {
    state.selectedId = accountId;
    const data = await api.get(`/api/mission-control/users/${accountId}`);
    state.detail = data.user;
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
        el("button", { type: "button", onclick: () => { state.selectedId = null; state.detail = null; render(); }, text: "← Back" }),
        el("h2", { text: account.username_display }),
      ]),
      el("div", { class: "card" }, [el("h3", { text: "Edit" }), form]),
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

  function relation(label, count) {
    return el("div", { class: "row spread" }, [el("span", { class: "muted", text: label }), el("span", { text: String(count) })]);
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
