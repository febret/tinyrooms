const Tiny = window.TinyActivity;
const worldsElement = document.querySelector("#worlds");
const emptyElement = document.querySelector("#multiverse-empty");
const summaryElement = document.querySelector("#multiverse-summary");
const countElement = document.querySelector("#multiverse-count");
const errorElement = document.querySelector("#multiverse-error");
const connectionElement = document.querySelector("#connection");
const refreshButton = document.querySelector("#multiverse-refresh");

const REFRESH_MS = 15_000;
const MAX_FRIEND_STICKERS = 8;

let worlds = [];
let loading = false;
let started = false;
let refreshTimer = null;
let errorMessage = "";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setSummary(value) {
  summaryElement.textContent = value;
}

function setError(message) {
  errorMessage = String(message || "");
  errorElement.textContent = errorMessage;
  errorElement.hidden = !errorMessage;
}

function showError(error) {
  const message = error instanceof Error ? error.message : String(error || "The Multiverse could not be reached.");
  setError(message);
  Tiny?.toast?.(message, true);
}

function placeholderUrl() {
  return Tiny?.image?.("/activities/multiverse/world-placeholder.svg") || "world-placeholder.svg";
}

function safeImageUrl(value, fallback) {
  if (!value) return fallback;
  try {
    const parsed = new URL(String(value), window.location.href);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") return parsed.href;
  } catch {
    // Fall through to the placeholder.
  }
  return fallback;
}

function countLabel(count) {
  if (count <= 0) return "No one here yet";
  if (count === 1) return "1 peep here";
  return `${count} peeps here`;
}

function friendSticker(friend) {
  const chip = element("span", "friend-sticker");
  const username = String(friend.username || "Friend");
  chip.title = `${username} is online here`;
  chip.setAttribute("aria-label", `${username} is online here`);
  const source = Tiny?.image?.(friend.sticker_url) || "";
  if (!source) {
    chip.classList.add("fallback");
    chip.textContent = username.slice(0, 1).toUpperCase();
    return chip;
  }
  const image = document.createElement("img");
  image.src = source;
  image.alt = "";
  image.loading = "lazy";
  image.addEventListener("error", () => {
    image.remove();
    chip.classList.add("fallback");
    chip.textContent = username.slice(0, 1).toUpperCase();
  }, { once: true });
  chip.append(image);
  return chip;
}

function createPortal(world) {
  const label = String(world.label || world.id || "A world");
  const current = Boolean(world.current);
  const online = Math.max(0, Number(world.users_online || 0));
  const friends = Array.isArray(world.friends) ? world.friends : [];
  const button = document.createElement("button");
  button.type = "button";
  button.className = "world-portal";
  button.dataset.worldId = String(world.id || "");
  button.setAttribute(
    "aria-label",
    current ? `${label}. You are here.` : `Travel to ${label}. ${countLabel(online)}.`,
  );
  if (current) {
    button.disabled = true;
    button.classList.add("current");
  }

  const aura = element("span", "portal-aura");
  aura.setAttribute("aria-hidden", "true");

  const frame = element("span", "portal-frame");
  const imageWrap = element("span", "portal-image-wrap");
  const image = document.createElement("img");
  image.className = "portal-image";
  image.alt = "";
  image.loading = "lazy";
  image.src = safeImageUrl(world.image_url, placeholderUrl());
  image.addEventListener("error", () => {
    image.src = placeholderUrl();
  }, { once: true });
  const sheen = element("span", "portal-sheen");
  sheen.setAttribute("aria-hidden", "true");
  imageWrap.append(image, sheen);

  const copy = element("span", "portal-copy");
  const name = element("span", "portal-name", label);
  const description = element(
    "span",
    "portal-description",
    String(world.description || "A shimmering world waits on the other side."),
  );
  const meta = element("span", "portal-meta");
  meta.append(element("span", "portal-count", countLabel(online)));
  if (current) meta.append(element("span", "portal-current", "You are here"));
  else meta.append(element("span", "portal-open", "Step through"));

  const friendRow = element("span", "portal-friends");
  if (friends.length) {
    for (const friend of friends.slice(0, MAX_FRIEND_STICKERS)) friendRow.append(friendSticker(friend));
    if (friends.length > MAX_FRIEND_STICKERS) {
      friendRow.append(element("span", "friend-sticker fallback", `+${friends.length - MAX_FRIEND_STICKERS}`));
    }
    friendRow.append(element("span", "portal-friendly-label", friends.length === 1 ? "friend online" : "friends online"));
  }

  copy.append(name, description, meta, friendRow);
  frame.append(imageWrap, copy);
  button.append(aura, frame);
  if (!current) button.addEventListener("click", () => void travel(world, button));
  return button;
}

function render() {
  worldsElement.replaceChildren(...worlds.map(createPortal));
  const hasWorlds = worlds.length > 0;
  emptyElement.hidden = hasWorlds || Boolean(errorMessage);
  setSummary(hasWorlds ? `${worlds.length} ${worlds.length === 1 ? "world is" : "worlds are"} within reach.` : "No portals are open right now.");
  countElement.textContent = hasWorlds
    ? `${worlds.reduce((total, world) => total + Math.max(0, Number(world.users_online || 0)), 0)} peeps across the Multiverse`
    : "";
}

async function travel(world, button) {
  if (button.classList.contains("traveling")) return;
  button.classList.add("traveling");
  button.disabled = true;
  setSummary(`Stepping toward ${String(world.label || world.id)}…`);
  Tiny?.sound?.("tap");
  try {
    const result = await Tiny.command(`.multiverse_travel ${String(world.id || "")}`);
    if (!result?.payload?.travel) {
      throw new Error(result?.message || "That portal did not open.");
    }
  } catch (error) {
    button.classList.remove("traveling");
    button.disabled = false;
    setSummary(`${worlds.length} ${worlds.length === 1 ? "world is" : "worlds are"} within reach.`);
    showError(error);
  }
}

function scheduleRefresh() {
  window.clearTimeout(refreshTimer);
  refreshTimer = window.setTimeout(() => {
    if (document.hidden) {
      scheduleRefresh();
      return;
    }
    void load({ quiet: true });
  }, REFRESH_MS);
}

async function load({ quiet = false } = {}) {
  if (loading) return;
  loading = true;
  refreshButton.classList.add("loading");
  if (!quiet) {
    setError("");
    setSummary("Reading the map…");
  }
  try {
    const result = await Tiny.command(".multiverse_worlds");
    const nextWorlds = result?.payload?.worlds;
    if (!Array.isArray(nextWorlds)) throw new Error(result?.message || "The Multiverse could not read the map.");
    worlds = nextWorlds.filter(world => world && world.id);
    setError("");
    render();
  } catch (error) {
    showError(error);
    if (!worlds.length) {
      emptyElement.hidden = true;
      setSummary("The map is out of reach.");
    }
  } finally {
    loading = false;
    refreshButton.classList.remove("loading");
    scheduleRefresh();
  }
}

function begin(state) {
  connectionElement.textContent = "";
  if (started) return;
  started = true;
  void load();
}

refreshButton.addEventListener("click", () => {
  Tiny?.sound?.("tap");
  void load();
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && started) void load({ quiet: true });
});

window.addEventListener("beforeunload", () => window.clearTimeout(refreshTimer));

if (!Tiny) {
  showError("The Multiverse could not connect to Tinyrooms.");
} else {
  Tiny.subscribe(begin);
}
