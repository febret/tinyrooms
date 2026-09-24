import { api } from "./api.js";
import { clear, el, formatAge, formatUptime, statusBadge } from "./dom.js";

const REFRESH_MS = 5000;

export function createServerManager(container, ctx) {
  const state = {
    servers: [],
    summary: {},
    selectedId: null,
    detail: null,
    logs: [],
    autoRefresh: true,
    timer: null,
  };

  async function refreshList() {
    const data = await api.get("/api/mission-control/servers");
    state.servers = data.servers;
    state.summary = data.summary;
    if (state.selectedId) {
      await refreshDetail();
    } else {
      render();
    }
  }

  async function refreshDetail() {
    const data = await api.get(`/api/mission-control/servers/${state.selectedId}`);
    state.detail = data.server;
    try {
      const logs = await api.get(`/api/mission-control/servers/${state.selectedId}/logs?limit=200`);
      state.logs = logs.lines || [];
    } catch (error) {
      state.logs = [`(logs unavailable: ${error.message})`];
    }
    render();
  }

  function schedule() {
    if (state.timer) window.clearInterval(state.timer);
    state.timer = window.setInterval(() => {
      if (!state.autoRefresh || !state.selectedId) return;
      refreshDetail().catch(() => {});
    }, REFRESH_MS);
  }

  function render() {
    clear(container);
    container.append(state.selectedId ? renderDrilldown() : renderList());
  }

  function renderList() {
    const rows = state.servers.map((server) =>
      el("tr", { class: "clickable", onclick: () => select(server.instance_id) }, [
        el("td", {}, server.name),
        el("td", {}, server.endpoint),
        el("td", {}, statusBadge(server.status)),
        el("td", {}, server.world.label || server.world.id || "—"),
        el("td", {}, server.source),
        el("td", {}, formatUptime(server.uptime_seconds)),
        el("td", {}, String(server.users_online)),
        el("td", {}, formatAge(server.last_heartbeat_seconds)),
      ]),
    );
    return el("div", { class: "stack" }, [
      el("div", { class: "row spread" }, [
        el("h2", { text: "Server Manager" }),
        el("div", { class: "row" }, [
          el("span", { class: "muted", text: `${state.summary.running || 0} running · ${state.summary.total || 0} known` }),
          el("button", { type: "button", onclick: () => refreshList().catch(showError), text: "Refresh" }),
        ]),
      ]),
      el("div", { class: "card" }, [
        el("h3", { text: "Instances" }),
        state.servers.length
          ? el("table", {}, [
              el("thead", {}, el("tr", {}, [
                el("th", { text: "Name" }), el("th", { text: "Endpoint" }), el("th", { text: "Status" }),
                el("th", { text: "World" }), el("th", { text: "Source" }), el("th", { text: "Uptime" }),
                el("th", { text: "Users" }), el("th", { text: "Heartbeat" }),
              ])),
              el("tbody", {}, rows),
            ])
          : el("p", { class: "muted", text: "No instances registered yet." }),
      ]),
      renderStartForm(),
    ]);
  }

  function renderStartForm() {
    const worldSelect = el("select", { id: "start-world", name: "world" }, [
      el("option", { value: "", text: "Select a world…" }),
      ...ctx.worlds().map((world) => el("option", { value: world.id, text: `${world.label || world.id}` })),
    ]);
    const form = el("form", { class: "grid cols-2", onsubmit: (event) => submitStart(event, form) }, [
      field("World definition", worldSelect),
      field("Worldstate DB (optional)", el("input", { name: "worldstate_db", placeholder: "existing .sqlite3" })),
      field("Users path (optional)", el("input", { name: "users_path", placeholder: "default" })),
      field("Name (optional)", el("input", { name: "name" })),
      field("Host", el("input", { name: "host", value: "127.0.0.1" })),
      field("Port (optional)", el("input", { name: "port", type: "number", placeholder: "auto" })),
      field("Features (optional)", el("input", { name: "features", placeholder: "dev_sample_activity" })),
      field("Admins (optional)", el("input", { name: "admins", placeholder: "siteadmin" })),
      field("Mods (optional)", el("input", { name: "mods", placeholder: "*" })),
      el("div", { class: "row" }, el("button", { class: "primary", type: "submit", text: "Start instance" })),
    ]);
    return el("div", { class: "card" }, [el("h3", { text: "Start a new instance" }), form]);
  }

  function field(label, control) {
    return el("label", { class: "stack" }, [el("span", { class: "muted", text: label }), control]);
  }

  async function submitStart(event, form) {
    event.preventDefault();
    const data = new FormData(form);
    const payload = {};
    for (const [key, value] of data.entries()) {
      if (value !== "") payload[key] = key === "port" ? Number(value) : value;
    }
    if (!payload.world) {
      ctx.setBanner("Choose a world definition first.");
      return;
    }
    try {
      await api.post("/api/mission-control/servers", payload);
      form.reset();
      await refreshList();
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  function select(instanceId) {
    state.selectedId = instanceId;
    state.detail = null;
    state.logs = [];
    refreshDetail().catch(showError);
    schedule();
  }

  function renderDrilldown() {
    const detail = state.detail;
    if (!detail) return el("div", { class: "card", text: "Loading…" });
    const stats = detail.stats || {};
    return el("div", { class: "stack" }, [
      el("div", { class: "row spread" }, [
        el("div", { class: "row" }, [
          el("button", { type: "button", onclick: () => { state.selectedId = null; if (state.timer) window.clearInterval(state.timer); render(); }, text: "← Back" }),
          el("h2", { text: detail.name }),
          statusBadge(detail.status),
        ]),
        el("div", { class: "row" }, [
          el("button", { type: "button", onclick: () => lifecycle("stop"), text: "Stop" }),
          el("button", { type: "button", onclick: () => lifecycle("restart"), text: "Restart" }),
          el("button", { type: "button", onclick: () => resync(), text: "Resync" }),
        ]),
      ]),
      el("div", { class: "card grid cols-2" }, [
        info("Endpoint", detail.endpoint),
        info("Source", detail.source),
        info("World", detail.world.label || detail.world.id || "—"),
        info("Version", detail.version || "—"),
        info("Uptime", formatUptime(detail.uptime_seconds)),
        info("Users online", String(detail.users_online)),
        info("Rooms", stats.rooms !== undefined ? String(stats.rooms) : "—"),
        info("Profile revision", stats.counters ? String(stats.counters.revision) : "—"),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "row spread" }, [
          el("h3", { text: "Log" }),
          el("div", { class: "row" }, [
            el("label", { class: "row" }, [
              el("input", { type: "checkbox", checked: state.autoRefresh, onchange: (event) => { state.autoRefresh = event.target.checked; } }),
              el("span", { class: "muted", text: "Auto-refresh" }),
            ]),
            el("button", { type: "button", onclick: () => refreshDetail().catch(showError), text: "Refresh" }),
          ]),
        ]),
        el("pre", { class: "log-panel", text: state.logs.length ? state.logs.join("\n") : "(no log lines)" }),
      ]),
      renderConsole(),
    ]);
  }

  function info(label, value) {
    return el("div", {}, [el("div", { class: "muted", text: label }), el("div", { text: value })]);
  }

  function renderConsole() {
    const input = el("input", { class: "grow", placeholder: "\\status", "aria-label": "Admin command" });
    const output = el("pre", { class: "console-output", text: "" });
    const send = async () => {
      const command = input.value.trim();
      if (!command) return;
      try {
        const data = await api.post(`/api/mission-control/servers/${state.selectedId}/command`, { command });
        output.textContent = JSON.stringify(data, null, 2);
      } catch (error) {
        output.textContent = error.message;
      }
    };
    return el("div", { class: "card" }, [
      el("h3", { text: "Admin console" }),
      el("div", { class: "row" }, [
        input,
        el("button", { class: "primary", type: "button", onclick: send, text: "Send" }),
      ]),
      output,
    ]);
  }

  async function lifecycle(action) {
    try {
      await api.post(`/api/mission-control/servers/${state.selectedId}/${action}`, {});
      await refreshDetail();
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function resync() {
    try {
      const data = await api.post(`/api/mission-control/servers/${state.selectedId}/resync`, {});
      ctx.setBanner(`Resync: ${JSON.stringify(data.result || data)}`);
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  function showError(error) {
    ctx.setBanner(error.message);
  }

  return {
    activate: () => refreshList().catch(showError),
    deactivate: () => { if (state.timer) window.clearInterval(state.timer); },
  };
}
