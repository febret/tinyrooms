import { api } from "./api.js";
import { clear, el } from "./dom.js";

export function createVibesManager(container, ctx) {
  const state = { rows: [], stores: [], warnings: [], query: "" };

  async function load(query = "") {
    state.query = query;
    const suffix = query ? `?q=${encodeURIComponent(query)}` : "";
    const data = await api.get(`/api/mission-control/vibes${suffix}`);
    state.rows = data.rows || [];
    state.stores = data.stores || [];
    state.warnings = data.warnings || [];
    render();
  }

  function render() {
    clear(container);
    const input = el("input", {
      class: "grow",
      placeholder: "Search store, world, or peep",
      "aria-label": "Search vibes",
      value: state.query,
    });
    const form = el("form", {
      class: "row",
      onsubmit: (event) => { event.preventDefault(); load(input.value.trim()).catch(showError); },
    }, [
      input,
      el("button", { type: "submit", text: "Search" }),
      el("button", { type: "button", onclick: () => { input.value = ""; load().catch(showError); }, text: "Clear" }),
    ]);
    const cards = [
      el("div", { class: "card" }, [form]),
      el("div", { class: "card" }, [
        state.rows.length
          ? el("table", {}, [
              el("thead", {}, el("tr", {}, [
                el("th", { text: "Store" }), el("th", { text: "World" }),
                el("th", { text: "Source" }), el("th", { text: "Target" }),
                el("th", { text: "Value" }), el("th", { text: "Updated" }),
                el("th", { text: "Actions" }),
              ])),
              el("tbody", {}, state.rows.map((row) => vibeRow(row))),
            ])
          : el("p", { class: "muted", text: "No vibe rows match." }),
      ]),
      renderAdd(),
    ];
    if (state.warnings.length) {
      cards.splice(1, 0, el("div", { class: "card" }, state.warnings.map((warning) =>
        el("p", { class: "muted", text: warning }),
      )));
    }
    container.append(
      el("div", { class: "stack" }, [
        el("div", { class: "row spread" }, [
          el("h2", { text: "Vibes Manager" }),
          el("button", { type: "button", onclick: () => load(state.query).catch(showError), text: "Refresh" }),
        ]),
        ...cards,
      ]),
    );
  }

  function peerCell(label, id) {
    return el("td", {}, [
      el("div", { text: label }),
      el("div", { class: "muted", text: id }),
    ]);
  }

  function vibeRow(row) {
    const valueInput = el("input", {
      type: "number",
      min: "-100",
      max: "100",
      value: String(row.value),
      "aria-label": `Value for ${row.source_peep_id} toward ${row.target_peep_id}`,
    });
    return el("tr", {}, [
      el("td", { text: row.store_label }),
      el("td", { text: row.world_id }),
      peerCell(row.source_label, row.source_peep_id),
      peerCell(row.target_label, row.target_peep_id),
      el("td", {}, valueInput),
      el("td", { class: "muted", text: row.updated_at }),
      el("td", {}, el("div", { class: "row grid-actions" }, [
        el("button", {
          type: "button",
          onclick: () => saveRow(row, valueInput).catch(showError),
          text: "Save",
        }),
        el("button", {
          type: "button",
          class: "danger",
          onclick: () => deleteRow(row).catch(showError),
          text: "Delete",
        }),
      ])),
    ]);
  }

  function renderAdd() {
    const available = state.stores.filter((store) => store.available !== false);
    const storeSelect = el("select", { "aria-label": "Store" }, available.map((store) =>
      el("option", { value: store.id, text: store.label }),
    ));
    const worldInput = el("input", { placeholder: "world id", "aria-label": "World id" });
    const sourceInput = el("input", { placeholder: "source peep id", "aria-label": "Source peep id" });
    const targetInput = el("input", { placeholder: "target peep id", "aria-label": "Target peep id" });
    const valueInput = el("input", { type: "number", min: "-100", max: "100", value: "0", "aria-label": "Value" });
    return el("div", { class: "card" }, [
      el("h3", { text: "Add or change a row" }),
      el("div", { class: "grid cols-2" }, [
        field("Store", storeSelect),
        field("World id", worldInput),
        field("Source peep id", sourceInput),
        field("Target peep id", targetInput),
        field("Value (-100 to 100)", valueInput),
      ]),
      el("div", { class: "row" }, el("button", {
        type: "button",
        class: "primary",
        onclick: () => addRow(storeSelect, worldInput, sourceInput, targetInput, valueInput).catch(showError),
        text: "Save row",
      })),
    ]);
  }

  function field(label, control) {
    return el("label", { class: "stack" }, [el("span", { class: "muted", text: label }), control]);
  }

  async function saveRow(row, valueInput) {
    try {
      await api.patch("/api/mission-control/vibes", {
        store: row.store,
        world_id: row.world_id,
        source_peep_id: row.source_peep_id,
        target_peep_id: row.target_peep_id,
        value: Number(valueInput.value),
      });
      await load(state.query);
      ctx.setBanner("Vibe updated.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function deleteRow(row) {
    if (!window.confirm(`Delete the vibe from "${row.source_peep_id}" to "${row.target_peep_id}"?`)) return;
    const params = new URLSearchParams({
      store: row.store,
      world_id: row.world_id,
      source_peep_id: row.source_peep_id,
      target_peep_id: row.target_peep_id,
    });
    try {
      await api.del(`/api/mission-control/vibes?${params}`);
      await load(state.query);
      ctx.setBanner("Vibe deleted.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function addRow(storeSelect, worldInput, sourceInput, targetInput, valueInput) {
    if (!storeSelect.value) {
      ctx.setBanner("Choose a store first.");
      return;
    }
    try {
      await api.patch("/api/mission-control/vibes", {
        store: storeSelect.value,
        world_id: worldInput.value.trim(),
        source_peep_id: sourceInput.value.trim(),
        target_peep_id: targetInput.value.trim(),
        value: Number(valueInput.value),
      });
      await load(state.query);
      ctx.setBanner("Vibe saved.");
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
