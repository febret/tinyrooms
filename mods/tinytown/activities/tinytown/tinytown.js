const Tiny = window.TinyActivity;

const wallet = document.getElementById("wallet");
const connection = document.getElementById("connection");
const tabs = document.getElementById("tabs");
const explorePanel = document.getElementById("explore-panel");
const minePanel = document.getElementById("mine-panel");
const householdPanel = document.getElementById("household-panel");
const districtsRoot = document.getElementById("districts");
const templateGrid = document.getElementById("template-grid");
const neighbourGrid = document.getElementById("neighbour-grid");
const neighbourEmpty = document.getElementById("neighbour-empty");
const mineGrid = document.getElementById("mine-grid");
const mineSummary = document.getElementById("mine-summary");
const householdGrid = document.getElementById("household-grid");
const householdEmpty = document.getElementById("household-empty");
const householdHouse = document.getElementById("household-house");
const npcForm = document.getElementById("npc-form");
const npcName = document.getElementById("npc-name");
const npcSubmit = document.getElementById("npc-submit");
const npcCancel = document.getElementById("npc-cancel");
const avatarsRoot = document.getElementById("avatars");
const traitsRoot = document.getElementById("traits");
const traitCount = document.getElementById("trait-count");
const openTinytown = document.getElementById("open-tinytown");

const ui = {
  tab: "explore",
  district: "",
  pendingBuy: "",
  pendingRemove: "",
  editing: null,
  avatar: "",
  traits: [],
  busy: false,
  started: false,
  houseId: "",
};

const data = {
  list: null,
  household: null,
};

function escape(value) {
  return Tiny.escape(value ?? "");
}

function image(url) {
  return Tiny.image(url);
}

function quote(value) {
  if (value === "") return '""';
  if (/^[A-Za-z0-9_.-]+$/.test(value)) return value;
  return `"${String(value).replace(/(["\\])/g, "\\$1")}"`;
}

function money(value) {
  return Number(value || 0).toLocaleString();
}

function setConnection(text) {
  connection.textContent = text || "";
}

function renderWallet() {
  wallet.textContent = money(Tiny.state?.user?.bops ?? data.list?.wallet ?? 0);
}

function setTab(tab) {
  ui.tab = ["explore", "mine", "household"].includes(tab) ? tab : "explore";
  for (const button of tabs.querySelectorAll("[data-tab]")) {
    button.setAttribute("aria-selected", String(button.dataset.tab === ui.tab));
  }
  explorePanel.hidden = ui.tab !== "explore";
  minePanel.hidden = ui.tab !== "mine";
  householdPanel.hidden = ui.tab !== "household";
  if (ui.tab === "household") void ensureHousehold();
}

function houseHasCurrentRoom(house) {
  const current = data.list?.current_room_id || "";
  return Boolean(current && (house.rooms || []).some(room => room.room_id === current));
}

function districtOptions() {
  const list = data.list?.districts || [];
  return [{ id: "", label: "All districts" }, ...list];
}

function renderDistricts() {
  districtsRoot.innerHTML = districtOptions().map(district => `
    <button type="button" data-district="${escape(district.id)}"
      aria-pressed="${ui.district === district.id}">${escape(district.label)}</button>
  `).join("");
}

function templateCard(template) {
  const bops = Number(Tiny.state?.user?.bops ?? data.list?.wallet ?? 0);
  const affordable = bops >= template.price;
  const pending = ui.pendingBuy === template.id;
  const ownedNote = template.owned ? `<span class="tt-status">You own ${template.owned}</span>` : "";
  const action = pending
    ? `<button type="button" class="confirm" data-buy-template="${escape(template.id)}">Confirm · ${money(template.price)} Bops</button>
       <button type="button" class="quiet" data-cancel-buy="1">Cancel</button>`
    : `<button type="button" class="primary" data-offer-template="${escape(template.id)}"${affordable ? "" : " disabled"}>
         ${affordable ? `Buy · ${money(template.price)} Bops` : `Need ${money(template.price)} Bops`}
       </button>`;
  return `<article class="tt-card" role="listitem" data-template-card="${escape(template.id)}">
    <div class="tt-art">
      <img src="${escape(image(template.preview_url))}" alt="${escape(template.label)} exterior" loading="lazy">
      <span class="tt-district-badge">${escape(template.district_label)}</span>
      <span class="tt-price-badge">${money(template.price)} Bops</span>
    </div>
    <div class="tt-card-body">
      <div class="tt-card-head">
        <h3>${escape(template.label)}</h3>
        <span class="tt-size">${escape(template.size)}</span>
      </div>
      <div class="tt-meta">
        <span>${template.room_count} rooms</span>
        <span>Private copy</span>
        ${ownedNote}
      </div>
      <p>${escape(template.description)}</p>
      <div class="tt-card-actions">${action}</div>
    </div>
  </article>`;
}

function houseCard(house, { neighbour = false } = {}) {
  const inside = houseHasCurrentRoom(house);
  const access = house.locked && !house.is_owner;
  const visit = neighbour
    ? `<button type="button" class="primary" data-visit-house="${escape(house.id)}"${access ? " disabled" : ""}>
         ${access ? "Locked" : "Visit"}
       </button>`
    : `<button type="button" class="primary" data-enter-house="${escape(house.id)}"${inside ? " disabled" : ""}>
         ${inside ? "You are inside" : "Enter"}
       </button>`;
  const ownerActions = house.is_owner
    ? `<button type="button" class="quiet" data-lock-house="${escape(house.id)}" data-locked="${house.locked ? "1" : "0"}">
         ${house.locked ? "Unlock" : "Lock"}
       </button>
       ${inside ? `<button type="button" data-art-house="${escape(house.id)}">Art Market</button>` : ""}`
    : "";
  return `<article class="tt-card" role="listitem">
    <div class="tt-art">
      <img src="${escape(image(house.preview_url))}" alt="${escape(house.label)}" loading="lazy">
      <span class="tt-district-badge">${escape(house.district_label)}</span>
      <span class="tt-price-badge">${escape(house.owner_username)}</span>
    </div>
    <div class="tt-card-body">
      <div class="tt-card-head">
        <h3>${escape(house.label)}</h3>
        <span class="tt-size">${escape(house.size)}</span>
      </div>
      <div class="tt-meta">
        <span>${house.room_count} rooms</span>
        ${house.locked ? "<span>Front door locked</span>" : "<span>Open to visitors</span>"}
        ${house.is_owner ? "<span>Your home</span>" : ""}
      </div>
      <p>${escape(house.description)}</p>
      <div class="tt-card-actions">${visit}${ownerActions}</div>
    </div>
  </article>`;
}

function renderExplore() {
  renderDistricts();
  const templates = data.list?.templates || [];
  const filtered = ui.district ? templates.filter(template => template.district === ui.district) : templates;
  templateGrid.innerHTML = filtered.map(templateCard).join("") ||
    '<p class="empty">No homes in this district yet.</p>';
  const neighbours = (data.list?.houses || []).filter(house => !house.is_owner);
  neighbourGrid.innerHTML = neighbours.map(house => houseCard(house, { neighbour: true })).join("");
  neighbourEmpty.hidden = neighbours.length > 0;
}

function renderMine() {
  const homes = data.list?.mine || [];
  mineSummary.textContent = homes.length
    ? `${homes.length} of ${data.list.max_houses} keys in your pocket.`
    : "No homes yet. The Explore tab has a few ideas.";
  mineGrid.innerHTML = homes.map(house => houseCard(house)).join("");
  if (!homes.length) {
    mineGrid.innerHTML = '<p class="empty">Your future hallway is out there somewhere.</p>';
  }
}

function statBar(label, key, value, className) {
  const amount = Math.max(0, Math.min(100, Number(value) || 0));
  return `<div class="tt-bar" title="${label}: ${Math.round(amount)}">
    <span>${label}</span>
    <span class="tt-bar-track"><span class="tt-bar-fill ${className}" style="width:${amount}%"></span></span>
    <span>${Math.round(amount)}</span>
  </div>`;
}

function renderHousehold() {
  const payload = data.household;
  const houses = data.list?.mine || [];
  householdHouse.innerHTML = houses.map(house => `
    <option value="${escape(house.id)}"${payload?.house_id === house.id ? " selected" : ""}>${escape(house.label)}</option>
  `).join("");
  householdHouse.disabled = !houses.length;
  const canAdd = Boolean(payload?.house_id) && (payload?.npcs || []).length < (payload?.max_npcs || 4);
  npcForm.querySelectorAll("input,button").forEach(element => {
    if (element.id !== "npc-cancel") element.disabled = !payload?.house_id;
  });
  npcSubmit.disabled = !canAdd || ui.busy;
  if (!houses.length) {
    householdEmpty.hidden = false;
    householdEmpty.textContent = "Buy a home first, then you can start filling it with peeps.";
    householdGrid.innerHTML = "";
    return;
  }
  const npcs = payload?.npcs || [];
  householdEmpty.hidden = npcs.length > 0;
  householdEmpty.textContent = "No household peeps yet. Add one below.";
  householdGrid.innerHTML = npcs.map(npc => `
    <article class="tt-npc" role="listitem">
      <img src="${escape(image(npc.avatar_url))}" alt="${escape(npc.name)}">
      <div>
        <h3>${escape(npc.name)}</h3>
        <p>${escape(npc.traits.map(trait => trait.label).join(" · "))} · ${escape(npc.room_label)}</p>
        <div class="tt-bars">
          ${statBar("Energy", "energy", npc.stats.energy, "")}
          ${statBar("Health", "health", npc.stats.health, "health")}
          ${statBar("Clean", "cleanliness", npc.stats.cleanliness, "clean")}
        </div>
        <p class="tt-status">Currently ${escape(npc.action_label)}${npc.target ? ` · ${escape(npc.target)}` : ""}</p>
      </div>
      <div class="tt-npc-actions">
        <button type="button" class="quiet" data-edit-npc="${escape(npc.id)}">Edit</button>
        <button type="button" class="quiet" data-remove-npc="${escape(npc.id)}">${ui.pendingRemove === npc.id ? "Confirm remove" : "Move out"}</button>
      </div>
    </article>
  `).join("");
}

function renderAvatars() {
  const avatars = data.household?.avatars || [];
  if (!ui.avatar && avatars.length) ui.avatar = avatars[0].id;
  avatarsRoot.innerHTML = avatars.map(avatar => `
    <button type="button" data-avatar="${escape(avatar.id)}" aria-pressed="${ui.avatar === avatar.id}" title="${escape(avatar.label)}">
      <img src="${escape(image(avatar.image_url))}" alt="${escape(avatar.label)}">
    </button>
  `).join("");
}

function renderTraits() {
  const traits = data.household?.traits || [];
  traitCount.textContent = `${ui.traits.length} / 2`;
  traitsRoot.innerHTML = traits.map(trait => `
    <button type="button" data-trait="${escape(trait.id)}" aria-pressed="${ui.traits.includes(trait.id)}" title="${escape(trait.description)}">
      ${escape(trait.label)}
    </button>
  `).join("");
}

function updateFormState() {
  const editing = ui.editing;
  npcSubmit.textContent = editing ? "Save peep" : "Move in";
  npcCancel.hidden = !editing;
  renderAvatars();
  renderTraits();
  const max = data.household?.max_npcs || 4;
  const count = (data.household?.npcs || []).length;
  npcSubmit.disabled = !data.household?.house_id || ui.traits.length !== 2 || !npcName.value.trim() || ui.busy || (!editing && count >= max);
  if (!editing && count >= max) npcSubmit.textContent = "Household full";
}

function renderAll() {
  renderWallet();
  renderExplore();
  renderMine();
  if (ui.tab === "household") renderHousehold();
}

async function refreshList() {
  const response = await Tiny.command(".tinytown list");
  data.list = response.payload || null;
  const houses = data.list?.mine || [];
  if (houses.length && !houses.some(house => house.id === ui.houseId)) {
    ui.houseId = houses[0].id;
  }
  setConnection("");
  renderAll();
}

async function refreshHousehold(houseId) {
  const command = houseId ? `.tinytown household ${quote(houseId)}` : ".tinytown household";
  const response = await Tiny.command(command);
  data.household = response.payload || null;
  if (data.household?.house_id) ui.houseId = data.household.house_id;
  if (!ui.avatar && data.household?.avatars?.length) ui.avatar = data.household.avatars[0].id;
  renderHousehold();
  updateFormState();
}

async function ensureHousehold() {
  if (!data.list) return;
  try {
    const houses = data.list.mine || [];
    if (!houses.length) {
      renderHousehold();
      return;
    }
    const houseId = ui.houseId || data.household?.house_id || houses[0].id;
    await refreshHousehold(houseId);
  } catch (error) {
    showError(error);
  }
}

function showError(error) {
  Tiny.toast(error instanceof Error ? error.message : String(error), true);
}

async function afterMutation() {
  await refreshList();
  if (ui.tab === "household") await ensureHousehold();
}

async function buyTemplate(templateId) {
  if (ui.busy) return;
  ui.busy = true;
  try {
    const response = await Tiny.command(`.tinytown buy ${quote(templateId)}`);
    ui.pendingBuy = "";
    ui.busy = false;
    Tiny.celebrate();
    Tiny.toast(response.message || "Keys received.");
    await afterMutation();
    setTab("mine");
  } catch (error) {
    ui.busy = false;
    showError(error);
  }
}

async function enterHouse(houseId, verb = "enter") {
  try {
    const response = await Tiny.command(`.tinytown ${verb} ${quote(houseId)}`);
    Tiny.toast(response.message || "You step inside.");
    await afterMutation();
    if (ui.tab === "household") await ensureHousehold();
  } catch (error) {
    showError(error);
  }
}

function startEdit(npc) {
  ui.editing = npc.id;
  ui.houseId = data.household?.house_id || ui.houseId;
  npcName.value = npc.name;
  ui.avatar = npc.avatar;
  ui.traits = npc.traits.map(trait => trait.id).slice(0, 2);
  updateFormState();
  npcName.focus({ preventScroll: true });
  document.querySelector(".tt-npc-form")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function cancelEdit() {
  ui.editing = null;
  npcName.value = "";
  ui.traits = [];
  ui.avatar = data.household?.avatars?.[0]?.id || "";
  updateFormState();
}

async function submitNpc(event) {
  event.preventDefault();
  if (ui.busy) return;
  const name = npcName.value.trim();
  if (!name || ui.traits.length !== 2 || !ui.avatar) {
    Tiny.toast("Pick a name, a look, and two traits.", true);
    return;
  }
  const houseId = data.household?.house_id || ui.houseId;
  if (!houseId) return;
  ui.busy = true;
  updateFormState();
  try {
    const command = ui.editing
      ? `.tinytown npc edit ${quote(ui.editing)} ${quote(name)} ${quote(ui.avatar)} ${quote(ui.traits[0])} ${quote(ui.traits[1])}`
      : `.tinytown npc add ${quote(houseId)} ${quote(name)} ${quote(ui.avatar)} ${quote(ui.traits[0])} ${quote(ui.traits[1])}`;
    const response = await Tiny.command(command);
    ui.busy = false;
    ui.editing = null;
    npcName.value = "";
    ui.traits = [];
    data.household = response.payload || data.household;
    await refreshList();
    await refreshHousehold(data.household?.house_id || houseId);
    Tiny.toast(response.message || "Household updated.");
  } catch (error) {
    ui.busy = false;
    updateFormState();
    showError(error);
  }
}

async function removeNpc(npcId) {
  if (ui.pendingRemove !== npcId) {
    ui.pendingRemove = npcId;
    renderHousehold();
    return;
  }
  ui.pendingRemove = "";
  try {
    const response = await Tiny.command(`.tinytown npc remove ${quote(npcId)}`);
    data.household = response.payload || data.household;
    await refreshList();
    await ensureHousehold();
    Tiny.toast(response.message || "Peep moved out.");
  } catch (error) {
    showError(error);
  }
}

tabs.addEventListener("click", event => {
  const button = event.target.closest("[data-tab]");
  if (button) setTab(button.dataset.tab);
});

districtsRoot.addEventListener("click", event => {
  const button = event.target.closest("[data-district]");
  if (!button) return;
  ui.district = button.dataset.district;
  ui.pendingBuy = "";
  renderExplore();
});

templateGrid.addEventListener("click", event => {
  const offer = event.target.closest("[data-offer-template]");
  if (offer) {
    ui.pendingBuy = offer.dataset.offerTemplate;
    renderExplore();
    return;
  }
  const buy = event.target.closest("[data-buy-template]");
  if (buy) void buyTemplate(buy.dataset.buyTemplate);
  if (event.target.closest("[data-cancel-buy]")) {
    ui.pendingBuy = "";
    renderExplore();
  }
});

neighbourGrid.addEventListener("click", event => {
  const visit = event.target.closest("[data-visit-house]");
  if (visit) void enterHouse(visit.dataset.visitHouse, "visit");
});

mineGrid.addEventListener("click", async event => {
  const enter = event.target.closest("[data-enter-house]");
  if (enter) {
    void enterHouse(enter.dataset.enterHouse);
    return;
  }
  const lock = event.target.closest("[data-lock-house]");
  if (lock) {
    try {
      const next = lock.dataset.locked === "1" ? "off" : "on";
      const response = await Tiny.command(`.tinytown lock ${quote(lock.dataset.lockHouse)} ${next}`);
      Tiny.toast(response.message || "Door updated.");
      await refreshList();
    } catch (error) {
      showError(error);
    }
    return;
  }
  const art = event.target.closest("[data-art-house]");
  if (art) {
    try {
      await Tiny.command(".tinytown artstore");
    } catch (error) {
      showError(error);
    }
  }
});

householdGrid.addEventListener("click", event => {
  const edit = event.target.closest("[data-edit-npc]");
  if (edit) {
    const npc = (data.household?.npcs || []).find(item => item.id === edit.dataset.editNpc);
    if (npc) startEdit(npc);
    return;
  }
  const remove = event.target.closest("[data-remove-npc]");
  if (remove) void removeNpc(remove.dataset.removeNpc);
});

householdHouse.addEventListener("change", async () => {
  ui.houseId = householdHouse.value;
  ui.pendingRemove = "";
  try {
    await refreshHousehold(ui.houseId);
  } catch (error) {
    showError(error);
  }
});

avatarsRoot.addEventListener("click", event => {
  const button = event.target.closest("[data-avatar]");
  if (!button) return;
  ui.avatar = button.dataset.avatar;
  renderAvatars();
});

traitsRoot.addEventListener("click", event => {
  const button = event.target.closest("[data-trait]");
  if (!button) return;
  const trait = button.dataset.trait;
  if (ui.traits.includes(trait)) {
    ui.traits = ui.traits.filter(item => item !== trait);
  } else {
    if (ui.traits.length >= 2) ui.traits.shift();
    ui.traits.push(trait);
  }
  renderTraits();
  updateFormState();
});

npcName.addEventListener("input", updateFormState);
npcForm.addEventListener("submit", submitNpc);
npcCancel.addEventListener("click", cancelEdit);
openTinytown.addEventListener("click", () => setTab("explore"));

Tiny.subscribe(hostState => {
  renderWallet();
  if (!ui.started) {
    ui.started = true;
    refreshList().catch(showError);
    return;
  }
  const current = data.list?.current_room_id || "";
  if (hostState?.room?.id && current && hostState.room.id !== current) {
    data.list.current_room_id = hostState.room.id;
    renderExplore();
    renderMine();
  }
});

window.setTimeout(() => {
  if (!ui.started) setConnection("Waiting for Tinyrooms…");
}, 600);
