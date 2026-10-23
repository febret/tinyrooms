const hooksRoot = document.querySelector("#key-hooks");
const detailRoot = document.querySelector("#key-detail");
const openHousesRoot = document.querySelector("#open-houses");
const countEl = document.querySelector("#keyring-count");
const connection = document.querySelector("#connection");

const COPY = {
  emptyTitle: "An empty hook",
  emptyBody: "No keys yet. The property pages of Tiny Mag hold twenty front doors; buy one and its key will hang here.",
  openMagazine: "Open Tiny Mag",
  yourKeys: "Your keys",
  roommates: "At home",
  noRoommates: "The rooms are quiet. The classified desk in Tiny Mag can introduce someone.",
  openHousesEmpty: "No neighbours have opened their doors yet.",
  stepInside: "Step inside",
  stepAgain: "Step in again",
  here: "You are here",
  lock: "Lock the front door",
  unlock: "Unlock the front door",
  locked: "Front door locked",
  unlocked: "Welcoming visitors",
  visit: "Call in",
  doorLocked: "Door locked",
};

const state = {
  host: null,
  list: null,
  household: null,
  selected: "",
  busy: false,
  initialised: false,
  roomId: "",
};

const escape = value => TinyActivity.escape(value);
const image = value => TinyActivity.image(value);
const money = value => Number(value || 0).toLocaleString("en-US");

function setConnection(message = "") {
  connection.textContent = message;
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function walletValue() {
  return Number(state.host?.user?.bops ?? state.list?.wallet ?? 0);
}

function keyTier(price) {
  const value = Number(price || 0);
  if (value <= 300) return { id: "iron", label: "Simple starter" };
  if (value <= 800) return { id: "brass", label: "Polished brass" };
  if (value <= 1600) return { id: "silver", label: "Sterling silver" };
  if (value <= 4000) return { id: "gilt", label: "Gilt bronze" };
  return { id: "estate", label: "Jeweled estate" };
}

function selectedHouse() {
  return (state.list?.mine || []).find(house => house.id === state.selected) || null;
}

function selectDefaultHouse() {
  const mine = state.list?.mine || [];
  const current = String(state.list?.current_house_id || "");
  state.selected = mine.some(house => house.id === current) ? current : (mine[0]?.id || "");
}

function isInside(house) {
  return String(state.list?.current_room_id || "").startsWith(`home:${house.id}:`);
}

function keyButton(house) {
  const tier = keyTier(house.price);
  const selected = house.id === state.selected;
  return `
    <button type="button" class="key-hook tier-${tier.id}${selected ? " selected" : ""}" data-action="select" data-id="${escape(house.id)}" aria-pressed="${selected}">
      <span class="key-peg" aria-hidden="true"></span>
      <span class="key-art">
        <img src="${image(house.key_url)}" alt="" loading="lazy" onerror="this.classList.add('missing')">
        <span class="key-fallback" aria-hidden="true"></span>
      </span>
      <span class="key-tag">
        <b>${escape(house.label)}</b>
        <small>${escape(house.district_label)} · ${house.locked ? COPY.locked : COPY.unlocked}</small>
      </span>
    </button>
  `;
}

function residentCard(npc) {
  const place = [npc.room_label, npc.action_label].filter(Boolean).join(" · ");
  return `
    <li class="resident">
      <img src="${image(npc.avatar_url)}" alt="" loading="lazy">
      <div>
        <b>${escape(npc.name)}</b>
        <small>${escape(place)}</small>
      </div>
    </li>
  `;
}

function renderDetail() {
  const house = selectedHouse();
  if (!house) {
    detailRoot.innerHTML = `
      <div class="detail-empty">
        <h2>${COPY.emptyTitle}</h2>
        <p>${COPY.emptyBody}</p>
        <button type="button" class="brass-btn" data-action="open-magazine">${COPY.openMagazine}</button>
      </div>
    `;
    return;
  }
  const tier = keyTier(house.price);
  const inside = isInside(house);
  const residents = (state.household?.house_id === house.id ? state.household.npcs : []) || [];
  detailRoot.innerHTML = `
    <div class="detail-key tier-${tier.id}">
      <img src="${image(house.key_url)}" alt="" onerror="this.classList.add('missing')">
    </div>
    <p class="detail-eyebrow">${escape(house.district_label)} · ${tier.label} key</p>
    <h2 class="detail-title">${escape(house.label)}</h2>
    <p class="detail-meta">${escape(house.size)} · ${house.room_count} rooms · ${money(house.price)} Bops · ${house.resident_count ?? 0} of ${house.max_residents ?? 4} residents</p>
    <p class="detail-lock ${house.locked ? "is-locked" : ""}">${house.locked ? COPY.locked : COPY.unlocked}</p>
    <div class="detail-actions">
      <button type="button" class="brass-btn" data-action="enter" data-id="${escape(house.id)}" ${inside ? "disabled" : ""}>
        ${inside ? COPY.here : COPY.stepInside}
      </button>
      <button type="button" class="brass-btn quiet" data-action="lock" data-id="${escape(house.id)}" data-locked="${house.locked ? "1" : "0"}">
        ${house.locked ? COPY.unlock : COPY.lock}
      </button>
    </div>
    <h3 class="detail-subtitle">${COPY.roommates}</h3>
    ${residents.length
      ? `<ul class="resident-list">${residents.map(residentCard).join("")}</ul>`
      : `<p class="detail-note">${COPY.noRoommates}</p>`}
  `;
}

function renderOpenHouses() {
  const neighbours = (state.list?.houses || []).filter(house => !house.is_owner);
  if (!neighbours.length) {
    openHousesRoot.innerHTML = `<p class="open-empty">${COPY.openHousesEmpty}</p>`;
    return;
  }
  openHousesRoot.innerHTML = neighbours.map(house => `
    <article class="open-house">
      <img src="${image(house.preview_url)}" alt="" loading="lazy">
      <div>
        <p class="open-eyebrow">${escape(house.district_label)}</p>
        <b>${escape(house.label)}</b>
        <small>${escape(house.owner_username)}'s place · ${house.room_count} rooms</small>
        <div class="detail-actions">
          <button type="button" class="brass-btn quiet" data-action="visit" data-id="${escape(house.id)}" ${house.locked ? "disabled" : ""}>
            ${house.locked ? COPY.doorLocked : COPY.visit}
          </button>
        </div>
      </div>
    </article>
  `).join("");
}

function render() {
  const mine = [...(state.list?.mine || [])].sort((a, b) => Number(a.price || 0) - Number(b.price || 0));
  countEl.textContent = mine.length
    ? `${mine.length} of ${state.list?.max_houses || 4} doors · ${money(walletValue())} Bops`
    : `${money(walletValue())} Bops`;
  hooksRoot.innerHTML = mine.length
    ? mine.map(keyButton).join("")
    : `<p class="open-empty">${COPY.emptyBody}</p>`;
  renderDetail();
  renderOpenHouses();
}

async function loadList(force = false) {
  if (state.list && !force) return state.list;
  setConnection("Checking the hooks...");
  const result = await TinyActivity.command(".tinytown list");
  state.list = result.payload || state.list;
  setConnection("");
  return state.list;
}

async function loadHousehold(force = false) {
  if (!state.selected) {
    state.household = null;
    return null;
  }
  if (state.household && !force && state.household.house_id === state.selected) return state.household;
  const result = await TinyActivity.command(`.tinytown household ${state.selected}`);
  state.household = result.payload || state.household;
  return state.household;
}

async function refresh() {
  await loadList(true);
  if (!selectedHouse()) selectDefaultHouse();
  await loadHousehold(true);
  render();
}

async function runCommand(text) {
  if (state.busy) return;
  state.busy = true;
  setConnection("Turning the key...");
  try {
    const result = await TinyActivity.command(text);
    state.busy = false;
    setConnection("");
    await refresh();
    TinyActivity.toast(result.message || "Done.");
  } catch (error) {
    state.busy = false;
    setConnection("");
    render();
    TinyActivity.toast(errorMessage(error), true);
  }
}

document.addEventListener("click", event => {
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const id = action.dataset.id || "";
  TinyActivity.sound("select");
  switch (action.dataset.action) {
    case "select":
      state.selected = id;
      state.household = null;
      void loadHousehold().then(render).catch(error => TinyActivity.toast(errorMessage(error), true));
      render();
      break;
    case "enter": void runCommand(`.tinytown enter ${id}`); break;
    case "lock": void runCommand(`.tinytown lock ${id} ${action.dataset.locked === "1" ? "off" : "on"}`); break;
    case "visit": void runCommand(`.tinytown visit ${id}`); break;
    case "open-magazine": void runCommand(".tinytown open"); break;
    default: break;
  }
});

TinyActivity.subscribe(hostState => {
  state.host = hostState;
  const roomId = String(state.host?.room?.id || "");
  const roomChanged = state.roomId !== roomId;
  state.roomId = roomId;
  if (!state.initialised) {
    state.initialised = true;
    void (async () => {
      await loadList(true);
      selectDefaultHouse();
      await loadHousehold(true);
      render();
    })().catch(error => {
      setConnection("");
      TinyActivity.toast(errorMessage(error), true);
      render();
    });
    return;
  }
  if (roomChanged) {
    state.list = null;
    state.household = null;
    void refresh().catch(error => TinyActivity.toast(errorMessage(error), true));
  }
});

render();
if (!TinyActivity.state) setConnection("Opening the keyring...");
window.setTimeout(() => {
  if (!state.host) setConnection("This keyring works best inside Tinyrooms.");
}, 3000);
