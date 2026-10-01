import { api } from "./api.js";
import { clear, el } from "./dom.js";

export function createPackageManager(container, ctx) {
  let packages = null;

  async function load() {
    packages = (await api.get("/api/mission-control/packages")).packages;
    render();
  }

  function render() {
    clear(container);
    container.append(
      el("div", { class: "row spread" }, [
        el("h2", { text: "Package Manager" }),
        el("button", { type: "button", onclick: () => load().catch(showError), text: "Refresh" }),
      ]),
      renderVersions(),
      renderGroup("World definitions (shared)", "world", packages.worlds),
      renderGroup("Cardsets (shared)", "cardset", packages.cardsets),
      renderGroup("Propsets (shared)", "propset", packages.propsets),
    );
  }

  function renderVersions() {
    const versions = packages.server_versions;
    return el("div", { class: "card package-group" }, [
      el("h3", { text: "Server versions" }),
      versions.length
        ? el("table", {}, [
            el("thead", {}, el("tr", {}, [
              el("th", { text: "Id" }),
              el("th", { text: "Build" }),
              el("th", { text: "Protocol" }),
              el("th", { text: "Commit" }),
              el("th", { text: "Instances" }),
              el("th", { text: "Path" }),
              el("th", { text: "Actions" }),
            ])),
            el("tbody", {}, versions.map((version) => renderVersion(version))),
          ])
        : el("p", { class: "muted", text: "None installed." }),
    ]);
  }

  function instanceLabel(version) {
    const running = version.instance_count ?? 0;
    const registered = version.registered_count ?? running;
    if (registered > running) return `${running} running / ${registered} registered`;
    return `${running} running`;
  }

  function renderVersion(version) {
    const button = version.deletable
      ? el("button", { class: "danger", type: "button", onclick: () => removeVersion(version), text: "Delete" })
      : el("button", { class: "danger", type: "button", disabled: true, title: version.delete_reason || "In use", text: "Delete" });
    return el("tr", {}, [
      el("td", {}, [
        el("span", { text: version.id }),
        version.running ? el("span", { class: "badge ok", text: "running" }) : "",
      ]),
      el("td", { text: version.build || "—" }),
      el("td", { text: String(version.protocol ?? "—") }),
      el("td", { text: version.commit || "—" }),
      el("td", { text: instanceLabel(version) }),
      el("td", { class: "muted", text: version.path }),
      el("td", {}, el("div", { class: "row" }, button)),
    ]);
  }

  function renderGroup(title, kind, items) {
    return el("div", { class: "card package-group" }, [
      el("h3", { text: title }),
      items.length
        ? el("table", {}, [
            el("thead", {}, el("tr", {}, [
              el("th", { text: "Id" }),
              el("th", { text: "Version" }),
              el("th", { text: "Validation" }),
              el("th", { text: "Path" }),
            ])),
            el("tbody", {}, items.map((item) => renderItem(kind, item))),
          ])
        : el("p", { class: "muted", text: "None installed." }),
    ]);
  }

  function renderItem(kind, item) {
    const validation = item.validation.status;
    return el("tr", {}, [
      el("td", { text: item.id }),
      el("td", { text: item.version || "—" }),
      el("td", {}, el("span", { class: `badge ${validation}`, title: item.validation.messages.join("\n"), text: validation })),
      el("td", { class: "muted", text: item.path }),
    ]);
  }

  async function removeVersion(version) {
    if (!window.confirm(`Delete server version ${version.id}? This removes the installed directory and release artifact.`)) return;
    try {
      await api.del(`/api/mission-control/versions/${encodeURIComponent(version.id)}`);
      await load();
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
