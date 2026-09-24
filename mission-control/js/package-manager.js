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
      renderUpload(),
      renderVersions(),
      renderGroup("World definitions", "world", packages.worlds),
      renderGroup("Cardsets", "cardset", packages.cardsets),
      renderGroup("Propsets", "propset", packages.propsets),
    );
  }

  function renderUpload() {
    const kind = el("select", {}, [
      el("option", { value: "world", text: "World" }),
      el("option", { value: "cardset", text: "Cardset" }),
      el("option", { value: "propset", text: "Propset" }),
    ]);
    const file = el("input", { type: "file", accept: ".zip", "aria-label": "Package zip" });
    const form = el("form", { class: "row", onsubmit: (event) => upload(event, kind, file) }, [
      kind,
      file,
      el("button", { class: "primary", type: "submit", text: "Upload & install" }),
    ]);
    return el("div", { class: "card" }, [el("h3", { text: "Install a package" }), form]);
  }

  function renderVersions() {
    return el("div", { class: "card" }, [
      el("h3", { text: "Server versions" }),
      el("table", {}, [
        el("thead", {}, el("tr", {}, [el("th", { text: "Id" }), el("th", { text: "Build" }), el("th", { text: "Protocol" }), el("th", { text: "Commit" }), el("th", { text: "Path" })])),
        el("tbody", {}, packages.server_versions.map((version) =>
          el("tr", {}, [
            el("td", { text: version.id }),
            el("td", { text: version.build || "—" }),
            el("td", { text: String(version.protocol ?? "—") }),
            el("td", { text: version.commit || "—" }),
            el("td", { class: "muted", text: version.path }),
          ]),
        )),
      ]),
    ]);
  }

  function renderGroup(title, kind, items) {
    return el("div", { class: "card package-group" }, [
      el("h3", { text: title }),
      items.length
        ? el("table", {}, [
            el("thead", {}, el("tr", {}, [el("th", { text: "Id" }), el("th", { text: "Version" }), el("th", { text: "Validation" }), el("th", { text: "Enabled" }), el("th", { text: "Actions" })])),
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
      el("td", { text: item.enabled ? "yes" : "no" }),
      el("td", {}, el("div", { class: "row" }, [
        el("button", { type: "button", onclick: () => toggle(kind, item.id, !item.enabled), text: item.enabled ? "Disable" : "Enable" }),
        el("button", { class: "danger", type: "button", onclick: () => remove(kind, item.id), text: "Delete" }),
      ])),
    ]);
  }

  async function upload(event, kindSelect, fileInput) {
    event.preventDefault();
    const file = fileInput.files[0];
    if (!file) {
      ctx.setBanner("Choose a zip file first.");
      return;
    }
    try {
      await api.upload(`/api/mission-control/packages?kind=${kindSelect.value}`, file);
      fileInput.value = "";
      await load();
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function toggle(kind, id, enabled) {
    try {
      await api.post(`/api/mission-control/packages/${kind}/${id}/enable`, { enabled });
      await load();
    } catch (error) {
      ctx.setBanner(error.message);
    }
  }

  async function remove(kind, id) {
    if (!window.confirm(`Delete ${kind}/${id}? This removes the installed directory.`)) return;
    try {
      await api.del(`/api/mission-control/packages/${kind}/${id}`);
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
