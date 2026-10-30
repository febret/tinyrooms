const base = window.__TR_BASE__ || "";
const form = document.getElementById("auth-form");
const status = document.getElementById("status");
const error = document.getElementById("error");
const actions = document.getElementById("player-actions");
const submit = document.getElementById("submit");
const toggle = document.getElementById("toggle");
const password = document.getElementById("password");
const passphrase = document.getElementById("passphrase");
const repairPanel = document.getElementById("destination-repair");
const repairMessage = document.getElementById("repair-message");
const repairSelect = document.getElementById("repair-instance");
const repairSubmit = document.getElementById("repair-submit");
let creating = false;
let csrf = "";
let busy = false;

function showError(message) {
  error.textContent = message;
  error.hidden = false;
}

function setBusy(value) {
  busy = value;
  for (const button of document.querySelectorAll("button")) button.disabled = value;
  form.setAttribute("aria-busy", String(value));
}

async function api(path, body) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 12000);
  try {
    const response = await fetch(`${base}/api/entry/${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: body === undefined ? {} : { "Content-Type": "application/json", "X-CSRF-Token": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
      const failure = new Error(data.message || "The request failed. Please retry.");
      failure.code = data.code;
      failure.data = data;
      throw failure;
    }
    return data;
  } catch (failure) {
    if (failure.name === "AbortError") throw new Error("Player entry timed out. Please retry.");
    throw failure;
  } finally {
    clearTimeout(timer);
  }
}

function signedIn(session) {
  csrf = session.csrf_token;
  form.hidden = true;
  actions.hidden = false;
  status.textContent = session.username ? `Welcome back, ${session.username}.` : "You are logged in.";
}

function hideRepair() {
  repairPanel.hidden = true;
  repairPanel.dataset.worldId = "";
  repairSelect.replaceChildren();
}

function showRepair(data) {
  const candidates = Array.isArray(data.candidates) ? data.candidates : [];
  repairSelect.replaceChildren(...candidates.map(candidate => {
    const suffix = candidate.replacement ? " (replacement)" : "";
    return new Option(`${candidate.label || candidate.instance_id}${suffix}`, candidate.instance_id);
  }));
  const replacement = candidates.find(candidate => candidate.replacement);
  if (replacement) repairSelect.value = replacement.instance_id;
  const world = data.world_id || "your saved world";
  repairMessage.textContent = candidates.length === 1
    ? `Your saved instance is unavailable. Continue in ${candidates[0].label || candidates[0].instance_id}?`
    : `Your saved instance is unavailable. Choose a running instance of ${world} to continue.`;
  repairPanel.dataset.worldId = data.world_id || "";
  repairPanel.hidden = false;
  status.textContent = "Your saved destination needs attention.";
}

async function connect() {
  error.hidden = true;
  hideRepair();
  status.textContent = "Finding your saved world…";
  let destination;
  try {
    destination = await api("resolve");
  } catch (failure) {
    const recoverable = new Set([
      "entry_instance_missing",
      "entry_instance_ambiguous",
      "entry_instance_not_running",
      "entry_instance_not_registered",
      "entry_instance_unreachable",
    ]).has(failure.code);
    if (recoverable && failure.data?.can_repair) {
      showRepair(failure.data);
      return;
    }
    throw failure;
  }
  const target = new URL(destination.client_url);
  if (target.protocol !== "https:" || target.hostname !== location.hostname || target.username || target.password || target.search || target.hash) {
    throw new Error("Your world must use HTTPS and the same hostname as player entry.");
  }
  const ready = new URL(`${target.pathname.replace(/\/$/, "")}/api/entry/ready`, target);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 8000);
  status.textContent = "Checking the connection to your world…";
  try {
    const response = await fetch(ready, { mode: "cors", credentials: "omit", cache: "no-store", signal: controller.signal });
    if (!response.ok) throw new Error("Your world is not ready to accept players. Please retry.");
    const identity = await response.json();
    if (identity.instance_id !== destination.instance_id || identity.world_id !== destination.world_id) {
      throw new Error("The world returned a different identity. Ask an operator to check the instance.");
    }
  } catch (failure) {
    if (failure.name === "AbortError") throw new Error("The connection to your world timed out. Check the server and network, then retry.");
    if (failure instanceof TypeError) throw new Error("Your browser could not reach the world. Check the server and network, then retry.");
    throw failure;
  } finally {
    clearTimeout(timer);
  }
  status.textContent = "Entering your world…";
  location.assign(target.href);
}

async function run(task) {
  if (busy) return;
  setBusy(true);
  error.hidden = true;
  try {
    await task();
  } catch (failure) {
    status.textContent = "Connection paused.";
    showError(failure.message || "Unable to connect. Please retry.");
  } finally {
    setBusy(false);
  }
}

toggle.addEventListener("click", () => {
  creating = !creating;
  document.getElementById("invitation").hidden = !creating;
  passphrase.required = creating;
  password.autocomplete = creating ? "new-password" : "current-password";
  submit.textContent = creating ? "Create account and play" : "Log in and play";
  toggle.textContent = creating ? "Use an existing account" : "Create an account";
  error.hidden = true;
});

form.addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const body = { username: form.elements.username.value, password: password.value };
    if (creating) body.passphrase = passphrase.value;
    const session = await api(creating ? "create" : "login", body);
    password.value = "";
    passphrase.value = "";
    signedIn(session);
    await connect();
  });
});

repairSubmit.addEventListener("click", () => run(async () => {
  const instanceId = repairSelect.value;
  if (!instanceId) throw new Error("Choose a world instance to continue.");
  status.textContent = "Saving your destination…";
  await api("repair", {
    instance_id: instanceId,
    world_id: repairPanel.dataset.worldId || undefined,
  });
  hideRepair();
  await connect();
}));

document.getElementById("retry").addEventListener("click", () => run(connect));
document.getElementById("logout").addEventListener("click", () => run(async () => {
  await api("logout", {});
  csrf = "";
  hideRepair();
  actions.hidden = true;
  form.hidden = false;
  status.textContent = "You are logged out.";
  document.getElementById("username").focus();
}));

function startShowcase() {
  const canvas = document.getElementById("entry-canvas");
  if (!canvas) return;
  const reducedMotion = Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  setTimeout(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(`${base}/api/entry/showcase`, {
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data.ok || !Array.isArray(data.props) || !data.props.length) return;
      const { initEntryShowcase } = await import("./entry-scene.js");
      initEntryShowcase({ canvas, props: data.props, reducedMotion });
    } catch {
      // The CSS backdrop is the fallback; decorative media must not affect login.
    } finally {
      clearTimeout(timer);
    }
  }, 60);
}

run(async () => {
  form.hidden = false;
  const session = await api("session");
  if (session.logged_in) {
    signedIn(session);
    await connect();
    return;
  }
  status.textContent = "Log in or create an account to play.";
  startShowcase();
});

const installButton = document.getElementById("install-app");
const standalone = Boolean(window.matchMedia?.("(display-mode: standalone)").matches) || window.navigator.standalone === true;
let installPrompt = null;
if (installButton && !standalone) {
  window.addEventListener("beforeinstallprompt", event => {
    event.preventDefault();
    installPrompt = event;
    installButton.hidden = false;
  });
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    installButton.hidden = true;
  });
  if (window.matchMedia("(display-mode: browser)").matches) {
    installButton.hidden = false;
    installButton.textContent = "Add to Home Screen";
  }
  installButton.addEventListener("click", async () => {
    if (!installPrompt) {
      status.textContent = "In Safari, tap Share, then Add to Home Screen.";
      return;
    }
    installPrompt.prompt();
    try {
      await installPrompt.userChoice;
    } finally {
      installPrompt = null;
      installButton.hidden = true;
    }
  });
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register(`${base}/sw.js`, { scope: `${base}/` }).catch(() => {
    // Installation still works from the browser menu when registration is blocked.
  });
}
