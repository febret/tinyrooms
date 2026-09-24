import { api } from "./api.js";
import { clear, el } from "./dom.js";
import { createServerManager } from "./server-manager.js";
import { createPackageManager } from "./package-manager.js";
import { createUserManager } from "./user-manager.js";

const loginScreen = document.getElementById("login-screen");
const appShell = document.getElementById("app-shell");
const banner = document.getElementById("banner");
const versionLabel = document.getElementById("version-label");
const operatorLabel = document.getElementById("operator-label");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const logoutButton = document.getElementById("logout-button");

let bannerTimer = null;
let cachedWorlds = [];

function setBanner(message) {
  banner.textContent = message || "";
  banner.hidden = !message;
  if (bannerTimer) window.clearTimeout(bannerTimer);
  if (message) bannerTimer = window.setTimeout(() => { banner.hidden = true; }, 8000);
}

const ctx = {
  setBanner,
  worlds: () => cachedWorlds,
};

async function loadWorlds() {
  try {
    const data = await api.get("/api/mission-control/packages");
    cachedWorlds = data.packages.worlds.filter((world) => world.enabled && world.validation.status !== "error");
  } catch (error) {
    cachedWorlds = [];
  }
}

const views = {
  servers: createServerManager(document.getElementById("panel-servers"), ctx),
  packages: createPackageManager(document.getElementById("panel-packages"), ctx),
  users: createUserManager(document.getElementById("panel-users"), ctx),
  audit: { activate: renderAudit, deactivate: () => {} },
};

let activeTab = "servers";

function showTab(name) {
  if (views[activeTab] && activeTab !== name) views[activeTab].deactivate();
  activeTab = name;
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  document.querySelectorAll(".panel").forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
  if (views[name]) Promise.resolve(views[name].activate()).catch((error) => setBanner(error.message));
}

async function renderAudit() {
  const panel = document.getElementById("panel-audit");
  clear(panel);
  try {
    const data = await api.get("/api/mission-control/audit");
    panel.append(
      el("h2", { text: "Audit" }),
      el("div", { class: "card" }, [
        data.entries.length
          ? el("table", {}, [
              el("thead", {}, el("tr", {}, [el("th", { text: "Time" }), el("th", { text: "Actor" }), el("th", { text: "Action" }), el("th", { text: "Target" }), el("th", { text: "Result" })])),
              el("tbody", {}, data.entries.map((entry) =>
                el("tr", {}, [
                  el("td", { text: entry.at }),
                  el("td", { text: entry.actor }),
                  el("td", { text: entry.action }),
                  el("td", { text: entry.target || "—" }),
                  el("td", { text: entry.result }),
                ]),
              )),
            ])
          : el("p", { class: "muted", text: "No audit entries yet." }),
      ]),
    );
  } catch (error) {
    setBanner(error.message);
  }
}

function showLogin() {
  loginScreen.hidden = false;
  appShell.hidden = true;
}

async function showShell(session) {
  loginScreen.hidden = true;
  appShell.hidden = false;
  operatorLabel.textContent = session.operator || "operator";
  versionLabel.textContent = session.version ? `v${session.version}` : "";
  await loadWorlds();
  showTab("servers");
}

async function boot() {
  try {
    const session = await api.get("/api/mission-control/session");
    if (!session.logged_in) {
      showLogin();
      return;
    }
    await showShell(session);
  } catch (error) {
    showLogin();
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const passphrase = document.getElementById("passphrase").value;
  try {
    await api.post("/api/mission-control/auth/login", { passphrase });
    document.getElementById("passphrase").value = "";
    await boot();
  } catch (error) {
    loginError.textContent = error.message;
  }
});

logoutButton.addEventListener("click", async () => {
  try {
    await api.post("/api/mission-control/auth/logout", {});
  } catch (error) {
    // ignore and return to login regardless
  }
  showLogin();
});

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => showTab(tab.dataset.tab)));

boot();
