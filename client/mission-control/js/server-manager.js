import { api } from "./api.js";
import { clear, el, formatAge, formatUptime, statusBadge } from "./dom.js";

const REFRESH_MS = 5000;

export function createServerManager(container, ctx) {
  const state = {
    servers: [],
    summary: {},
    selectedId: null,
    detail: null,
    replacementId: "",
    logs: [],
    autoRefresh: true,
    timer: null,
    nginxManaged: true,
    nginxReason: "",
  };

  async function loadNginxStatus() {
    try {
      const info = await api.get("/api/mission-control/server");
      const managed = Boolean(info.config && info.config.same_origin_worlds && info.config.world_map_configured);
      state.nginxManaged = managed;
      state.nginxReason = managed ? "" : "Nginx world-map management is not configured.";
    } catch {
      state.nginxManaged = true;
      state.nginxReason = "";
    }
  }

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
    let data;
    try {
      data = await api.get(`/api/mission-control/servers/${state.selectedId}`);
    } catch (error) {
      if (error.status === 404) {
        state.selectedId = null;
        state.detail = null;
        if (state.timer) window.clearInterval(state.timer);
        await refreshList();
        return;
      }
      throw error;
    }
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
        el("td", {}, [server.name, server.is_default ? el("span", { class: "badge", text: "Default" }) : ""]),
        el("td", {}, clientLink(server)),
        el("td", {}, statusBadge(server.status)),
        el("td", {}, server.world.label || server.world.id || "—"),
        versionControl(server),
        el("td", {}, server.source),
        el("td", {}, formatUptime(server.uptime_seconds)),
        el("td", {}, String(server.users_online)),
        el("td", {}, formatAge(server.last_heartbeat_seconds)),
        el("td", {}, gridActions(server)),
      ]),
    );
    return el("div", { class: "stack" }, [
      el("div", { class: "row spread" }, [
        el("h2", { text: "Server Manager" }),
        el("div", { class: "row" }, [
          el("span", { class: "muted", text: `${state.summary.running || 0} running · ${state.summary.total || 0} known` }),
          el("button", { type: "button", onclick: () => reboot(), text: "Reboot" }),
          el("button", {
            type: "button",
            disabled: !state.nginxManaged,
            title: state.nginxReason || "Regenerate the nginx world map and reload nginx",
            onclick: () => refreshNginx().catch(showError),
            text: "Refresh nginx",
          }),
          el("button", { type: "button", onclick: () => refreshList().catch(showError), text: "Refresh" }),
        ]),
      ]),
      el("div", { class: "card" }, [
        el("h3", { text: "Instances" }),
        state.servers.length
          ? el("table", {}, [
              el("thead", {}, el("tr", {}, [
                 el("th", { text: "Name" }), el("th", { text: "Client URL" }), el("th", { text: "Status" }),
                el("th", { text: "World" }), el("th", { text: "Version" }), el("th", { text: "Source" }),
                el("th", { text: "Uptime" }), el("th", { text: "Users" }), el("th", { text: "Heartbeat" }),
                el("th", { text: "Actions" }),
              ])),
              el("tbody", {}, rows),
            ])
          : el("p", { class: "muted", text: "No instances registered yet." }),
      ]),
      renderStartForm(),
    ]);
  }

  function renderStartForm() {
    const versionSelect = el("select", { id: "start-version", name: "version" },
      ctx.versions().map((version) => el("option", {
        value: version.id,
        text: version.running ? `${version.label} (${version.build || "unknown"})` : version.id,
      })),
    );
    const worldSelect = el("select", { id: "start-world", name: "world" }, [
      el("option", { value: "", text: "Loading worlds…" }),
    ]);
    const refreshWorlds = async () => {
      let worlds = [];
      try {
        worlds = await ctx.worlds(versionSelect.value);
      } catch (error) {
        ctx.setBanner(error.message);
      }
      worldSelect.replaceChildren(el("option", { value: "", text: "Select a world…" }));
      for (const world of worlds) {
        worldSelect.append(el("option", { value: world.id, text: `${world.label || world.id} (${world.source})` }));
      }
    };
    versionSelect.addEventListener("change", () => { refreshWorlds().catch(showError); });
    refreshWorlds().catch(showError);
    const form = el("form", { class: "grid cols-2", onsubmit: (event) => submitStart(event, form) }, [
      field("Server version", versionSelect),
      field("World definition", worldSelect),
      field("Worldstate DB (optional)", el("input", { name: "worldstate_db", placeholder: "existing .sqlite3" })),
      field("Users path (optional)", el("input", { name: "users_path", placeholder: "default" })),
      field("Name (optional)", el("input", { name: "name" })),
      field("Host (optional)", el("input", { name: "host", placeholder: "configured default" })),
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
      ctx.setBanner("Instance started.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  function select(instanceId) {
    state.selectedId = instanceId;
    state.detail = null;
    state.replacementId = "";
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
          detail.is_default ? el("span", { class: "badge", text: "Default" }) : "",
        ]),
        el("div", { class: "row" }, [
          el("button", { type: "button", disabled: detail.is_default || !detail.client_url, onclick: () => makeDefault(), text: "Make default" }),
          el("button", { type: "button", onclick: () => lifecycle("stop"), text: "Stop" }),
          el("button", { type: "button", onclick: () => lifecycle("restart"), text: "Restart" }),
          el("button", { type: "button", onclick: () => renameInstance(), text: "Rename" }),
          el("button", { type: "button", onclick: () => resync(), text: "Resync" }),
          replacementSelect(detail),
          el("button", { type: "button", onclick: () => deleteInstance(), text: "Delete" }),
        ]),
      ]),
      el("div", { class: "card grid cols-2" }, [
        el("div", {}, [el("div", { class: "muted", text: "Client URL" }), clientLink(detail)]),
        info("Endpoint", detail.endpoint),
        info("Source", detail.source),
        info("World", detail.world.label || detail.world.id || "—"),
        info("Version", detail.version_id || detail.version || "—"),
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

  function clientLink(server) {
    return server.client_url
      ? el("a", { href: server.client_url, target: "_blank", rel: "noopener noreferrer", onclick: (event) => event.stopPropagation(), text: server.client_url })
      : el("span", { class: "muted", text: "—" });
  }

  function versionControl(server) {
    const current = server.version_id || "";
    const label = server.version || current || "—";
    if (server.source !== "spawned") return el("td", {}, label);
    const versions = ctx.versions();
    const select = el("select", {
      "aria-label": `Version for ${server.name}`,
      onclick: (event) => event.stopPropagation(),
      onchange: (event) => {
        const value = event.target.value;
        if (!value) return;
        changeVersion(server, value).catch(showError);
      },
    }, [
      el("option", { value: "", text: `Current: ${label}` }),
      ...versions.filter((version) => version.id !== current).map((version) =>
        el("option", { value: version.id, text: `Switch: ${version.label || version.id}` }),
      ),
    ]);
    return el("td", {}, el("div", { class: "stack" }, [
      el("span", { text: label }),
      select,
    ]));
  }

  function gridActions(server) {
    return el("div", { class: "row grid-actions" }, [
      el("button", {
        type: "button",
        disabled: server.source !== "spawned" || server.status !== "stopped",
        onclick: (event) => { event.stopPropagation(); startServer(server).catch(showError); },
        text: "Start",
      }),
      el("button", {
        type: "button",
        onclick: (event) => { event.stopPropagation(); restartServer(server).catch(showError); },
        text: "Restart",
      }),
      el("button", {
        type: "button",
        disabled: server.status !== "running",
        onclick: (event) => { event.stopPropagation(); resyncServer(server).catch(showError); },
        text: "Resync",
      }),
      el("button", {
        type: "button",
        class: "danger",
        onclick: (event) => { event.stopPropagation(); deleteServer(server).catch(showError); },
        text: "Delete",
      }),
    ]);
  }

  async function startServer(server) {
    await api.post(`/api/mission-control/servers/${server.instance_id}/start`, {});
    await refreshList();
    ctx.setBanner(`Starting ${server.name}.`);
  }

  async function restartServer(server) {
    await api.post(`/api/mission-control/servers/${server.instance_id}/restart`, {});
    await refreshList();
    ctx.setBanner(`Restarting ${server.name}.`);
  }

  async function resyncServer(server) {
    const data = await api.post(`/api/mission-control/servers/${server.instance_id}/resync`, {});
    if (data && data.ok === false) throw new Error(data.message || "Resync failed.");
    ctx.setBanner(`Resync requested for ${server.name}.`);
  }

  async function changeVersion(server, version) {
    await api.post(`/api/mission-control/servers/${server.instance_id}/version`, { version });
    await refreshList();
    ctx.setBanner(`Changing ${server.name} to ${version}.`);
  }

  async function deleteServer(server) {
    let references = 0;
    try {
      const data = await api.get(`/api/mission-control/servers/${server.instance_id}/destination-references`);
      references = Number(data.count || 0);
    } catch {
      references = 0;
    }
    const impact = references ? `\n\n${references} player(s) have this instance saved as their destination.` : "";
    if (!window.confirm(`Delete "${server.name}"?${impact}`)) return;
    await api.del(`/api/mission-control/servers/${server.instance_id}`);
    if (state.selectedId === server.instance_id) {
      state.selectedId = null;
      state.detail = null;
      state.replacementId = "";
      if (state.timer) window.clearInterval(state.timer);
    }
    await refreshList();
    ctx.setBanner("Instance deleted.");
  }

  function replacementSelect(detail) {
    const alternatives = state.servers.filter((server) =>
      server.instance_id !== detail.instance_id
      && server.status === "running"
      && server.world.id === detail.world.id,
    );
    if (!alternatives.length) return "";
    const select = el("select", {
      id: "delete-replacement",
      "aria-label": "Replacement for affected players",
      onchange: (event) => { state.replacementId = event.target.value; },
    }, [
      el("option", { value: "", text: "No replacement" }),
      ...alternatives.map((server) => el("option", {
        value: server.instance_id,
        selected: server.instance_id === state.replacementId,
        text: `Reassign to ${server.name}`,
      })),
    ]);
    select.value = state.replacementId;
    return select;
  }

  async function makeDefault() {
    try {
      await api.post(`/api/mission-control/instances/${state.selectedId}/default`, {});
      await refreshList();
      ctx.setBanner("Default instance updated.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
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
      const data = await api.post(`/api/mission-control/servers/${state.selectedId}/${action}`, {});
      if (data && data.server && data.server.instance_id) {
        state.selectedId = data.server.instance_id;
      }
      await refreshList();
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function renameInstance() {
    const detail = state.detail;
    if (!detail) return;
    const proposed = window.prompt("New instance name", detail.name);
    if (proposed === null) return;
    const name = proposed.trim();
    if (!name) {
      ctx.setBanner("A new name is required.");
      return;
    }
    try {
      const data = await api.post(`/api/mission-control/servers/${state.selectedId}/rename`, { name });
      if (data.server && data.server.instance_id) state.selectedId = data.server.instance_id;
      await refreshList();
      ctx.setBanner("Instance renamed.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function deleteInstance() {
    const detail = state.detail;
    if (!detail) return;
    let references = 0;
    try {
      const data = await api.get(`/api/mission-control/servers/${state.selectedId}/destination-references`);
      references = Number(data.count || 0);
    } catch {
      references = 0;
    }
    const replacement = state.replacementId
      ? state.servers.find((server) => server.instance_id === state.replacementId)
      : null;
    const impact = references
      ? `\n\n${references} player(s) have this instance saved as their destination.`
      : "";
    const reassign = replacement
      ? `\n\nReassign those players to "${replacement.name}".`
      : "\n\nThey will be offered another running instance of this world.";
    if (!window.confirm(`Delete "${detail.name}"?${impact}${references ? reassign : ""}`)) return;
    try {
      const query = new URLSearchParams();
      if (replacement) {
        query.set("successor_instance_id", replacement.instance_id);
        query.set("reassign_players", "true");
      }
      const suffix = query.toString() ? `?${query}` : "";
      const data = await api.del(`/api/mission-control/servers/${state.selectedId}${suffix}`);
      state.selectedId = null;
      state.detail = null;
      state.replacementId = "";
      if (state.timer) window.clearInterval(state.timer);
      await refreshList();
      ctx.setBanner(replacement ? `Instance deleted; ${data.reassigned || 0} player(s) reassigned.` : "Instance deleted.");
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function reboot() {
    if (!window.confirm("Reboot mission control? Spawned servers stop now and resume after it restarts.")) return;
    try {
      const data = await api.post("/api/mission-control/reboot", {});
      const count = Array.isArray(data.resuming) ? data.resuming.length : 0;
      ctx.setBanner(`Rebooting mission control… ${count} instance(s) will resume.`);
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function refreshNginx() {
    const data = await api.post("/api/mission-control/nginx/refresh", {});
    const routed = Number(data.routed || 0);
    ctx.setBanner(data.changed
      ? `Nginx routes refreshed for ${routed} instance(s).`
      : `Nginx routes already up to date for ${routed} instance(s).`);
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
    activate: () => loadNginxStatus().then(refreshList).catch(showError),
    deactivate: () => { if (state.timer) window.clearInterval(state.timer); },
  };
}
