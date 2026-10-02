import { api } from "./api.js";
import { clear, el, formatBytes, formatSpan } from "./dom.js";

const REFRESH_MS = 5000;

export function createServerInfo(container, ctx) {
  const state = { info: null, storage: null, autoRefresh: true, timer: null };

  async function load(forceStorage = false) {
    const storagePath = forceStorage
      ? "/api/mission-control/server/storage?refresh=1"
      : "/api/mission-control/server/storage";
    const [info, storage] = await Promise.all([
      api.get("/api/mission-control/server"),
      api.get(storagePath),
    ]);
    state.info = info;
    state.storage = storage;
    render();
  }

  async function refreshMetrics() {
    state.info = await api.get("/api/mission-control/server");
    render();
  }

  function schedule() {
    if (state.timer) window.clearInterval(state.timer);
    state.timer = window.setInterval(() => {
      if (!state.autoRefresh || !state.info) return;
      refreshMetrics().catch(() => {});
    }, REFRESH_MS);
  }

  function render() {
    clear(container);
    const info = state.info;
    if (!info) {
      container.append(el("div", { class: "card", text: "Loading…" }));
      return;
    }
    container.append(
      el("div", { class: "row spread" }, [
        el("h2", { text: "Server Info" }),
        el("div", { class: "row" }, [
          el("label", { class: "row" }, [
            el("input", { type: "checkbox", checked: state.autoRefresh, onchange: (event) => { state.autoRefresh = event.target.checked; } }),
            el("span", { class: "muted", text: "Auto-refresh" }),
          ]),
          el("button", { type: "button", onclick: () => load(true).catch(showError), text: "Refresh" }),
        ]),
      ]),
      el("div", { class: "grid cols-2" }, [
        renderHost(info.host),
        renderCpu(info.cpu),
        renderMemory(info.memory),
        renderProcess(info.process),
        renderDisk(info.disk),
        renderConfig(info.config),
      ]),
      renderStorage(state.storage),
    );
  }

  function card(title, children) {
    return el("div", { class: "card" }, [el("h3", { text: title }), ...children]);
  }

  function kv(label, value) {
    return el("div", { class: "kv" }, [
      el("span", { class: "muted", text: label }),
      el("span", { text: value }),
    ]);
  }

  function meter(percent, label) {
    const value = percent === null || percent === undefined ? null : Math.max(0, Math.min(100, percent));
    const level = value === null ? "" : value >= 90 ? " error" : value >= 70 ? " warn" : "";
    const children = [];
    if (label !== undefined) {
      children.push(el("div", { class: "row spread" }, [
        el("span", { class: "muted", text: label }),
        el("span", { text: value === null ? "—" : `${value}%` }),
      ]));
    }
    children.push(el("div", { class: "meter" }, el("div", { class: `meter-fill${level}`, style: `width:${value ?? 0}%` })));
    return el("div", { class: "stack" }, children);
  }

  function renderHost(host) {
    const load = host.load_average ? host.load_average.map((value) => value.toFixed(2)).join(" / ") : "—";
    return card("Host", [
      kv("Hostname", host.hostname || "—"),
      kv("System", `${host.system || "—"} ${host.release || ""}`.trim()),
      kv("Machine", host.machine || "—"),
      kv("CPU model", host.cpu_model || "—"),
      kv("Logical CPUs", host.cpu_count === null || host.cpu_count === undefined ? "—" : String(host.cpu_count)),
      kv("Load average", load),
      kv("Host uptime", formatSpan(host.uptime_seconds)),
      kv("Python", host.python || "—"),
    ]);
  }

  function renderCpu(cpu) {
    const children = [
      meter(cpu.system_percent, "System"),
      meter(cpu.process_percent, "Mission control process"),
    ];
    if (cpu.system_percent === null) {
      children.push(el("p", { class: "muted", text: "System CPU is only sampled on Linux hosts." }));
    }
    return card("CPU", children);
  }

  function renderMemory(memory) {
    if (!memory) {
      return card("Memory", [el("p", { class: "muted", text: "Memory details are only available on Linux hosts." })]);
    }
    return card("Memory", [
      meter(memory.percent, "Used"),
      kv("Total", formatBytes(memory.total)),
      kv("Used", formatBytes(memory.used)),
      kv("Available", formatBytes(memory.available)),
      kv("Swap", memory.swap_total ? `${formatBytes(memory.swap_used)} / ${formatBytes(memory.swap_total)}` : "—"),
    ]);
  }

  function renderProcess(process) {
    return card("Mission control process", [
      kv("PID", String(process.pid)),
      kv("Uptime", formatSpan(process.uptime_seconds)),
      kv("Resident memory", formatBytes(process.rss)),
      kv("Virtual memory", formatBytes(process.vms)),
      kv("Threads", String(process.threads)),
    ]);
  }

  function renderDisk(disk) {
    if (!disk) {
      return card("Disk", [el("p", { class: "muted", text: "Disk usage unavailable." })]);
    }
    return card("Disk", [
      meter(disk.percent, "Filesystem used"),
      kv("Path", disk.path),
      kv("Total", formatBytes(disk.total)),
      kv("Used", formatBytes(disk.used)),
      kv("Free", formatBytes(disk.free)),
    ]);
  }

  function pathRow(label, value) {
    return el("div", { class: "kv" }, [
      el("span", { class: "muted", text: label }),
      el("span", { class: "path", text: value }),
    ]);
  }

  function renderConfig(config) {
    const schema = config.schema ? `profile ${config.schema.profile} / world ${config.schema.world}` : "—";
    return card("Configuration", [
      kv("Version", config.version),
      kv("Protocol", String(config.protocol)),
      kv("Schema", schema),
      kv("Listen", `${config.host}:${config.port}${config.base_path || ""}`),
      kv("Actor", config.actor),
      kv("Features", (config.features || []).join(", ") || "—"),
      kv("nginx", config.nginx_managed ? "managed" : "not configured"),
      kv("Keepalive", config.keepalive_configured ? "configured" : "not configured"),
      pathRow("Install root", config.install_root),
      pathRow("Content root", config.content_root),
      pathRow("Versions", config.versions_path),
      pathRow("Releases", config.releases_path),
      pathRow("Users", config.users_path),
    ]);
  }

  function renderStorage(storage) {
    if (!storage) {
      return card("Install storage", [el("p", { class: "muted", text: "Loading…" })]);
    }
    const rows = storage.entries.map((entry) => el("tr", {}, [
      el("td", {}, [
        el("span", { text: entry.name }),
        entry.symlink ? el("span", { class: "badge", text: "symlink" }) : "",
      ]),
      el("td", { text: formatBytes(entry.size) }),
      el("td", {}, meter(entry.percent)),
    ]));
    const summary = `${storage.path} · ${formatBytes(storage.total)} total`
      + (storage.partial ? " · some entries were unreadable" : "")
      + (storage.cached_at ? ` · scanned ${storage.cached_at}` : "");
    return el("div", { class: "card package-group" }, [
      el("div", { class: "row spread" }, [
        el("h3", { text: "Install storage" }),
        el("button", { type: "button", onclick: () => load(true).catch(showError), text: "Rescan" }),
      ]),
      el("p", { class: "muted", text: summary }),
      storage.entries.length
        ? el("table", {}, [
            el("thead", {}, el("tr", {}, [
              el("th", { text: "Directory" }),
              el("th", { text: "Size" }),
              el("th", { text: "Share" }),
            ])),
            el("tbody", {}, rows),
          ])
        : el("p", { class: "muted", text: "No entries." }),
    ]);
  }

  function showError(error) {
    ctx.setBanner(error.message);
  }

  return {
    activate: () => { load().then(schedule).catch(showError); },
    deactivate: () => { if (state.timer) window.clearInterval(state.timer); },
  };
}
