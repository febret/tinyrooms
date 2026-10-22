import { renderWhiteboardCanvas } from "../../app/js/surface-canvas.js";

const PAGES = [
  { id: "cover", label: "Cover", short: "Cover" },
  { id: "contents", label: "Contents", short: "In This Issue" },
  { id: "homes", label: "Homes for Sale", short: "Property" },
  { id: "keys", label: "My Keys", short: "My Homes" },
  { id: "roommates", label: "Roommate Classifieds", short: "Roommates" },
  { id: "gallery", label: "The Gallery", short: "Art" },
  { id: "floors", label: "Floor Finishes", short: "Floors" },
  { id: "community", label: "Reader Gallery", short: "Community" },
  { id: "submit", label: "Submit Your Work", short: "Sell Art" },
];
const PAGE_IDS = new Map(PAGES.map((page, index) => [page.id, index]));
const ART_PAGES = new Set(["gallery", "floors", "community", "submit"]);

const leftPage = document.querySelector("#page-left");
const rightPage = document.querySelector("#page-right");
const book = document.querySelector("#book");
const rail = document.querySelector("#rail");
const folio = document.querySelector("#folio");
const wallet = document.querySelector("#wallet");
const connection = document.querySelector("#connection");
const turnLeaf = document.querySelector("#turn-leaf");
const prevButton = document.querySelector("#prev");
const nextButton = document.querySelector("#next");

const state = {
  page: 0,
  host: null,
  list: null,
  roommates: null,
  market: null,
  district: "",
  pendingBuy: "",
  selectedHouse: "",
  selectedSell: "",
  busy: false,
  initialised: false,
  roomId: "",
  previews: new Map(),
  previewSequence: 0,
};

const escape = value => TinyActivity.escape(value);
const image = value => TinyActivity.image(value);
const money = value => Number(value || 0).toLocaleString("en-US");
const percent = value => `${Math.max(0, Math.min(100, Number(value || 0)))}%`;

function currentPage() {
  return PAGES[state.page] || PAGES[0];
}

function isArtPage() {
  return ART_PAGES.has(currentPage().id);
}

function setConnection(message = "") {
  connection.textContent = message;
}

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function registerPreview(surface) {
  const key = `surface-${++state.previewSequence}`;
  state.previews.set(key, surface);
  return key;
}

function canvas(surface, extraClass = "") {
  const key = registerPreview(surface);
  return `<canvas class="${extraClass}" data-surface-key="${key}" aria-hidden="true"></canvas>`;
}

function paintPreviews() {
  for (const element of document.querySelectorAll("canvas[data-surface-key]")) {
    const surface = state.previews.get(element.dataset.surfaceKey);
    if (!surface) continue;
    const context = element.getContext("2d");
    if (!context) continue;
    renderWhiteboardCanvas(context, surface.content || surface);
  }
}

function walletValue() {
  return Number(state.host?.user?.bops ?? state.list?.wallet ?? state.market?.wallet ?? 0);
}

function currentRoomId() {
  return String(state.host?.room?.id || "");
}

function currentHouseId() {
  const room = state.host?.room;
  if (!room) return "";
  return String(state.list?.current_house_id || "");
}

function isInsideOwnedHome() {
  return Boolean(state.list?.current_is_owned && currentRoomId());
}

function houseById(id) {
  return (state.list?.houses || []).find(house => house.id === id) || null;
}

function templateById(id) {
  return (state.list?.templates || []).find(template => template.id === id) || null;
}

function traitLabels(entry) {
  return (entry.traits || []).map(trait => `<span class="trait">${escape(trait.label)}</span>`).join("");
}

function statsBars(stats) {
  const rows = [
    ["Energy", stats?.energy],
    ["Health", stats?.health],
    ["Clean", stats?.cleanliness],
  ];
  return `<div class="mini-bars">${rows.map(([label, value]) => (
    `<span class="mini-label">${label} ${Math.round(Number(value || 0))}</span>`
    + `<span class="mini-bar"><i style="width:${percent(value)}"></i></span>`
  )).join("")}</div>`;
}

function mastheadLeft() {
  return `
    <p class="kicker">Issue No. 01 · A tinyrooms publication</p>
    <h1 class="masthead"><small>THE POCKET TOWN REVIEW</small>TINY<br>MAG</h1>
    <p class="dek dropcap">A whole town, printed on good paper. Turn the pages for keys, neighbours, classifieds, and the sort of art that looks better with a price tag.</p>
    <span class="cover-sticker">Inside: five strangers who might become housemates</span>
    <div class="fact-strip">
      <div><b>${(state.list?.templates || []).length || 20}</b><span>front doors</span></div>
      <div><b>${(state.list?.districts || []).length || 4}</b><span>districts</span></div>
      <div><b>${money(walletValue())}</b><span>Bops</span></div>
    </div>
  `;
}

function coverRight() {
  const feature = state.list?.templates?.[0];
  const art = state.market?.art?.[0];
  return `
    <p class="kicker">The house-hunting, roommate-finding, art-buying issue</p>
    <h2 class="cover-title">Move in.<br><em>Hang out.</em><br>Meet someone.</h2>
    <p class="dek">Everything you need to turn a pocket-sized town into somewhere that feels like yours.</p>
    <figure class="tape-photo">
      ${feature ? `<img src="${image(feature.preview_url)}" alt="">` : ""}
      <figcaption>${feature ? escape(feature.label) : "A very small front door"} · ${feature ? money(feature.price) : "from 100"} Bops</figcaption>
    </figure>
    <ul class="cover-lines">
      <li><strong>Property</strong><span>Twenty tiny homes. Four districts. One welcome grant.</span></li>
      <li><strong>Classifieds</strong><span>Five possible roommates, hand-picked by the universe.</span></li>
      <li><strong>The Gallery</strong><span>${art ? escape(art.label) : "New prints"} and work by your neighbours.</span></li>
    </ul>
  `;
}

function contentsLeft() {
  return `
    <p class="eyebrow">In this issue</p>
    <h2 class="page-title">Turn<br>the page.</h2>
    <p class="dek dropcap">The magazine is arranged like a good afternoon: first the keys, then the company, then something beautiful for the wall.</p>
    <div class="note">Use the arrows, the page dots, or any entry on the right-hand page. Every turn has a sound because paper should be heard.</div>
    <span class="section-stamp">Tiny rooms · Big lives</span>
  `;
}

function contentsRight() {
  return `
    <p class="eyebrow">Contents</p>
    <h2 class="page-title">The issue</h2>
    <ul class="contents-list">
      ${PAGES.slice(1).map((page, index) => `
        <li data-page="${escape(page.id)}">
          <span class="num">${String(index + 2).padStart(2, "0")}</span>
          <b>${escape(page.label)}</b>
          <span class="hint">${page.id === "roommates" ? "five candidates" : page.id === "submit" ? "sell your art" : "read on"}</span>
        </li>
      `).join("")}
    </ul>
    <p class="note">Everything is printed on one continuous sheet of Bops. Wallet balance: <strong>${money(walletValue())}</strong>.</p>
  `;
}

function districtChips() {
  return `
    <div class="toolbar" role="group" aria-label="Filter by district">
      <button type="button" class="chip" data-district="" aria-pressed="${state.district === ""}">All districts</button>
      ${(state.list?.districts || []).map(district => `
        <button type="button" class="chip" data-district="${escape(district.id)}" aria-pressed="${state.district === district.id}">
          ${escape(district.label)}
        </button>
      `).join("")}
    </div>
  `;
}

function homesLeft() {
  return `
    <p class="eyebrow">The property pages</p>
    <h2 class="page-title">A door<br>of your own.</h2>
    <p class="dek dropcap">Every home is a private copy, with its own rooms, walls, and questionable amount of character. Pick a district, then pick a front door.</p>
    ${districtChips()}
    <div class="note">First-time residents short on Bops receive a one-time welcome grant. House keys are yours to keep; there is no resale desk in this town.</div>
    <span class="section-stamp">Keys available: ${Math.max(0, (state.list?.max_houses || 4) - (state.list?.mine?.length || 0))}</span>
  `;
}

function templateCard(template) {
  const pending = state.pendingBuy === template.id;
  const canAfford = walletValue() >= Number(template.price || 0);
  return `
    <article class="estate-card">
      <img src="${image(template.preview_url)}" alt="">
      <div class="estate-copy">
        <p class="eyebrow">${escape(template.district_label)} · ${escape(template.size)}</p>
        <h3>${escape(template.label)}</h3>
        <p>${escape(template.description)}</p>
        <div class="price-line">
          <span class="price">${money(template.price)} Bops</span>
          <span class="badge">${template.room_count} rooms</span>
          ${template.owned ? `<span class="badge good">Owned ×${template.owned}</span>` : ""}
        </div>
        <div class="actions">
          ${pending
            ? `<button type="button" class="mag-btn" data-action="confirm-buy" data-id="${escape(template.id)}">Confirm · ${money(template.price)} Bops</button>
               <button type="button" class="mag-btn quiet" data-action="cancel-buy">Cancel</button>`
            : `<button type="button" class="mag-btn" data-action="buy" data-id="${escape(template.id)}" ${canAfford ? "" : "disabled"}>
                 ${canAfford ? `Buy · ${money(template.price)} Bops` : "Need more Bops"}
               </button>`}
        </div>
      </div>
    </article>
  `;
}

function homesRight() {
  const templates = (state.list?.templates || []).filter(template => !state.district || template.district === state.district);
  const neighbours = (state.list?.houses || []).filter(house => !house.is_owner);
  return `
    <p class="kicker">For sale in TinyTown</p>
    <h2 class="page-title">Property</h2>
    <div class="list-grid">
      ${templates.length ? templates.map(templateCard).join("") : `<div class="empty">No doors in this district this week.</div>`}
    </div>
    <hr class="rule">
    <p class="eyebrow">Open houses</p>
    <div class="list-grid">
      ${neighbours.length ? neighbours.map(house => `
        <article class="estate-card">
          <img src="${image(house.preview_url)}" alt="">
          <div class="estate-copy">
            <p class="eyebrow">${escape(house.district_label)}</p>
            <h3>${escape(house.label)}</h3>
            <p>${escape(house.owner_username)}'s place · ${house.room_count} rooms</p>
            <div class="actions">
              <button type="button" class="mag-btn quiet" data-action="visit-house" data-id="${escape(house.id)}" ${house.locked ? "disabled" : ""}>
                ${house.locked ? "Door locked" : "Visit"}
              </button>
            </div>
          </div>
        </article>
      `).join("") : `<div class="empty">No neighbours have opened their doors yet.</div>`}
    </div>
  `;
}

function keysLeft() {
  const mine = state.list?.mine || [];
  return `
    <p class="eyebrow">The keyring</p>
    <h2 class="page-title">My<br>homes.</h2>
    <p class="dek dropcap">Lock the front door, step inside, or visit a neighbour. The little marker in the margin shows where you are right now.</p>
    <div class="fact-strip">
      <div><b>${mine.length}</b><span>keys</span></div>
      <div><b>${mine.reduce((total, house) => total + house.room_count, 0)}</b><span>rooms</span></div>
      <div><b>${money(walletValue())}</b><span>Bops</span></div>
    </div>
    <div class="note">The magazine stays open while you move between homes. The art desk updates when you step inside one of your own.</div>
  `;
}

function houseKey(house, { owned = false } = {}) {
  const inside = (state.list?.current_room_id || "").startsWith(`home:${house.id}:`);
  return `
    <article class="house-key">
      <img src="${image(house.preview_url)}" alt="">
      <div>
        <p class="eyebrow">${escape(house.district_label)} · ${escape(house.size)}</p>
        <h3>${escape(house.label)}</h3>
        <p>${owned ? escape(house.owner_username) : `Hosted by ${escape(house.owner_username)}`} · ${house.room_count} rooms</p>
        <div class="price-line">
          ${inside ? `<span class="badge dark inside">You are inside</span>` : ""}
          ${house.locked ? `<span class="badge">Front door locked</span>` : `<span class="badge good">Welcome</span>`}
        </div>
        <div class="actions">
          <button type="button" class="mag-btn" data-action="${owned ? "enter-house" : "visit-house"}" data-id="${escape(house.id)}" ${(!owned && house.locked) ? "disabled" : ""}>
            ${inside ? "Step in again" : owned ? "Enter" : house.locked ? "Locked" : "Visit"}
          </button>
          ${owned ? `<button type="button" class="mag-btn quiet" data-action="lock-house" data-id="${escape(house.id)}" data-locked="${house.locked ? "1" : "0"}">${house.locked ? "Unlock" : "Lock"}</button>` : ""}
        </div>
      </div>
    </article>
  `;
}

function keysRight() {
  const mine = state.list?.mine || [];
  const neighbours = (state.list?.houses || []).filter(house => !house.is_owner);
  return `
    <p class="kicker">Your doors</p>
    <h2 class="page-title">The keyring</h2>
    <div class="list-grid">
      ${mine.length ? mine.map(house => houseKey(house, { owned: true })).join("") : `<div class="empty">No keys yet. The property pages are two turns back.</div>`}
    </div>
    <hr class="rule">
    <p class="eyebrow">Neighbours' open houses</p>
    <div class="list-grid">
      ${neighbours.length ? neighbours.map(house => houseKey(house)).join("") : `<div class="empty">The street is quiet. Perhaps someone new will move in.</div>`}
    </div>
  `;
}

function roommateLeft() {
  const data = state.roommates;
  const houses = data?.houses || state.list?.mine || [];
  return `
    <p class="eyebrow">The classifieds</p>
    <h2 class="page-title">Roommate<br>wanted.</h2>
    <p class="dek dropcap">Five strangers have answered the advert. They have names, habits, and strong opinions about the correct place for a kettle. Choose carefully.</p>
    ${houses.length ? `
      <div class="toolbar" role="group" aria-label="Choose a home">
        ${houses.map(house => `
          <button type="button" class="chip" data-house="${escape(house.id)}" aria-pressed="${(state.selectedHouse || data?.house_id) === house.id}">
            ${escape(house.label)}
          </button>
        `).join("")}
      </div>
    ` : ""}
    <div class="note">A home holds up to ${data?.max_npcs || 4} residents. Each advert is a real household peep with the traits and starting stats printed here; no hidden paperwork.</div>
    <span class="section-stamp">No calls after midnight</span>
  `;
}

function roommateAd(candidate, full) {
  return `
    <article class="roommate-ad">
      <img class="roommate-portrait" src="${image(candidate.avatar_url)}" alt="">
      <div>
        <p class="eyebrow">Advert · ${escape(candidate.traits?.[0]?.label || "Townsfolk")}</p>
        <h3>${escape(candidate.name)}</h3>
        <p class="headline">“${escape(candidate.headline)}”</p>
        <div class="trait-row">${traitLabels(candidate)}</div>
        ${statsBars(candidate.stats)}
        <div class="actions">
          <button type="button" class="mag-btn" data-action="adopt" data-id="${escape(candidate.id)}" ${full ? "disabled" : ""}>
            ${full ? "Household full" : "Invite to move in"}
          </button>
        </div>
      </div>
    </article>
  `;
}

function roommateRight() {
  const data = state.roommates;
  if (!data) return `<p class="empty">The classified desk is checking its files...</p>`;
  const npcs = data.npcs || [];
  const full = npcs.length >= (data.max_npcs || 4);
  return `
    <p class="kicker">This week's applicants</p>
    <h2 class="page-title">The waiting room</h2>
    <div class="roommate-board">
      ${(data.candidates || []).length
        ? data.candidates.map(candidate => roommateAd(candidate, full)).join("")
        : `<div class="empty">No adverts this week. Adopt a resident to refresh the desk.</div>`}
    </div>
    <hr class="rule">
    <p class="eyebrow">Already home</p>
    <div class="list-grid">
      ${npcs.length ? npcs.map(npc => `
        <article class="roommate-ad">
          <img class="roommate-portrait" src="${image(npc.avatar_url)}" alt="">
          <div>
            <p class="eyebrow">${escape(npc.room_label)} · ${escape(npc.action_label)}</p>
            <h3>${escape(npc.name)}</h3>
            <div class="trait-row">${traitLabels(npc)}</div>
            ${statsBars(npc.stats)}
            <div class="actions">
              <button type="button" class="mag-btn quiet" data-action="remove-npc" data-id="${escape(npc.id)}">Move out</button>
            </div>
          </div>
        </article>
      `).join("") : `<div class="empty">The rooms are quiet. Pick an applicant above.</div>`}
    </div>
  `;
}

function galleryLeft() {
  const market = state.market;
  return `
    <p class="eyebrow">The gallery</p>
    <h2 class="page-title">Something<br>for the wall.</h2>
    <p class="dek dropcap">Limited prints, generous frames, and a small brass plaque that says you have taste. Art arrives as a real whiteboard, already signed and locked.</p>
    ${market?.can_hang
      ? `<div class="note">Hanging in <strong>${escape(market.room?.house || "your home")} · ${escape(market.room?.label || "")}</strong>. ${market.whiteboards} of ${market.max_whiteboards} wall spaces used.</div>`
      : `<div class="note">Browse from anywhere. Step inside one of your homes to hang a piece.</div>`}
    <span class="section-stamp">${market?.unlocked_art?.length || 0} prints collected</span>
  `;
}

function artCard(piece) {
  const owned = (state.market?.unlocked_art || []).includes(piece.id);
  const canHang = Boolean(state.market?.can_hang);
  const full = Number(state.market?.whiteboards || 0) >= Number(state.market?.max_whiteboards || 4);
  return `
    <article class="art-card">
      <div class="art-frame">${canvas(piece.surface)}</div>
      <div class="art-meta">
        <p class="eyebrow">${escape((piece.tags || []).slice(0, 2).join(" · "))}</p>
        <h3>${escape(piece.label)}</h3>
        <p>${escape(piece.description)}</p>
        <div class="price-line">
          <span class="price">${owned ? "Collected" : `${money(piece.price)} Bops`}</span>
          ${full ? `<span class="badge">Walls full</span>` : ""}
        </div>
        <div class="actions">
          <button type="button" class="mag-btn" data-action="hang-art" data-id="${escape(piece.id)}" ${(!canHang || full) ? "disabled" : ""}>
            ${!canHang ? "Step inside a home" : full ? "Make space" : owned ? "Hang another" : "Buy & hang"}
          </button>
        </div>
      </div>
    </article>
  `;
}

function galleryRight() {
  const market = state.market;
  if (!market) return `<p class="empty">The gallery is opening its shutters...</p>`;
  return `
    <p class="kicker">The permanent collection</p>
    <h2 class="page-title">The Gallery</h2>
    <div class="art-grid">
      ${(market.art || []).map(artCard).join("")}
    </div>
  `;
}

function floorLeft() {
  return `
    <p class="eyebrow">The sample room</p>
    <h2 class="page-title">Underfoot.</h2>
    <p class="dek dropcap">A floor is the quietest piece of furniture in the house. These finishes are printed in the back of the magazine, measured, and fitted by extremely small contractors.</p>
    <div class="note">Buy a finish once, then reapply it whenever the mood changes. One finish per room.</div>
    <span class="section-stamp">Samples available at the desk</span>
  `;
}

function floorRight() {
  const market = state.market;
  if (!market) return `<p class="empty">The samples are being unrolled...</p>`;
  return `
    <p class="kicker">The sample room</p>
    <h2 class="page-title">Floor finishes</h2>
    <div class="floor-grid">
      ${(market.floors || []).map(floor => `
        <button type="button" class="floor-chip" data-action="floor" data-id="${escape(floor.id)}" ${(!market.can_hang || floor.current) ? "disabled" : ""}>
          <img src="${image(floor.image_url)}" alt="">
          <b>${escape(floor.label)}</b>
          <small>${floor.current ? "Currently fitted" : floor.unlocked ? "Owned · Apply" : `${money(floor.price)} Bops`}</small>
        </button>
      `).join("")}
    </div>
    ${market.can_hang ? "" : `<p class="note">Step inside one of your homes to fit a floor.</p>`}
  `;
}

function communityLeft() {
  const market = state.market;
  return `
    <p class="eyebrow">Reader gallery</p>
    <h2 class="page-title">Art by<br>neighbours.</h2>
    <p class="dek dropcap">Every print in this section was drawn by a resident. The artist keeps the original; you get a signed, locked copy and they get the Bops.</p>
    ${market?.can_hang ? "<div class=\"note\">Collect a print from the page. It will hang in your current room and stay locked to protect the artist's work.</div>" : "<div class=\"note\">You can browse the reader gallery from anywhere. Step inside a home to collect a print.</div>"}
    <span class="section-stamp">${market?.listings?.length || 0} prints for sale</span>
  `;
}

function listingCard(listing) {
  const canHang = Boolean(state.market?.can_hang);
  const full = Number(state.market?.whiteboards || 0) >= Number(state.market?.max_whiteboards || 4);
  return `
    <article class="listing-card">
      <div class="art-frame">${canvas(listing.surface)}</div>
      <div class="listing-copy">
        <p class="byline">Submitted by ${escape(listing.seller_username)}</p>
        <h3>${escape(listing.title)}</h3>
        <p>${escape(listing.description || "An original from a TinyTown neighbour.")}</p>
        <div class="price-line">
          <span class="price">${listing.owned ? "Collected" : `${money(listing.price)} Bops`}</span>
          ${listing.is_seller ? `<span class="badge dark">Your advert</span>` : ""}
        </div>
        <div class="actions">
          ${listing.is_seller
            ? `<button type="button" class="mag-btn danger" data-action="withdraw-listing" data-id="${escape(listing.id)}">Withdraw</button>`
            : listing.owned
              ? `<button type="button" class="mag-btn" data-action="hang-listing" data-id="${escape(listing.id)}" ${(!canHang || full) ? "disabled" : ""}>${!canHang ? "Step inside a home" : full ? "Walls full" : "Hang another"}</button>`
              : `<button type="button" class="mag-btn" data-action="buy-listing" data-id="${escape(listing.id)}" ${(!canHang || full) ? "disabled" : ""}>${!canHang ? "Step inside a home" : full ? "Walls full" : "Collect print"}</button>`}
        </div>
      </div>
    </article>
  `;
}

function communityRight() {
  const market = state.market;
  if (!market) return `<p class="empty">The reader gallery is being pasted up...</p>`;
  return `
    <p class="kicker">Reader gallery</p>
    <h2 class="page-title">The wall</h2>
    <div class="list-grid">
      ${(market.listings || []).length
        ? market.listings.map(listingCard).join("")
        : `<div class="empty">No reader prints yet. The first one could be yours.</div>`}
    </div>
  `;
}

function sellLeft() {
  return `
    <p class="eyebrow">The submission desk</p>
    <h2 class="page-title">Send it<br>to print.</h2>
    <p class="dek dropcap">Make something on a whiteboard in one of your homes. Then choose it here, give it a title, and set a price. Neighbours can collect as many copies as they like; you are paid each time someone new takes one home.</p>
    <div class="note">You can have four pieces for sale at once. Withdraw a listing to free a slot. Purchased art is locked, but the original stays yours to edit.</div>
    <span class="section-stamp">Paid in full · No gallery cut</span>
  `;
}

function sellCard(item, index) {
  const selected = state.selectedSell === `${item.room_id}|${item.instance_id}`;
  return `
    <article class="sell-card ${selected ? "selected" : ""}" data-action="select-sell" data-key="${escape(`${item.room_id}|${item.instance_id}`)}">
      ${canvas(item.surface)}
      <div>
        <p class="eyebrow">${escape(item.house_label)} · ${escape(item.room_label)}</p>
        <h3>${selected ? "Selected for print" : "Editable whiteboard"}</h3>
        <p>${item.listed ? "Already listed." : "Choose this piece to set a title and price."}</p>
      </div>
    </article>
  `;
}

function sellForm() {
  const selected = (state.market?.sellables || []).find(item => `${item.room_id}|${item.instance_id}` === state.selectedSell);
  if (!selected) return "";
  return `
    <form class="sell-form" id="sell-form" data-room="${escape(selected.room_id)}" data-instance="${escape(selected.instance_id)}">
      <label>Title
        <input id="sell-title" maxlength="80" placeholder="Untitled, but make it memorable" required>
      </label>
      <div class="row">
        <label>Price in Bops
          <input id="sell-price" type="number" min="1" max="10000" value="50" required>
        </label>
        <div class="actions" style="align-items:end">
          <button type="submit" class="mag-btn" id="sell-submit">Send to print</button>
        </div>
      </div>
    </form>
  `;
}

function submitRight() {
  const market = state.market;
  if (!market) return `<p class="empty">The submission desk is sharpening pencils...</p>`;
  return `
    <p class="kicker">The submission desk</p>
    <h2 class="page-title">Sell your work</h2>
    <p class="eyebrow">Your editable whiteboards</p>
    <div class="sell-grid">
      ${(market.sellables || []).length
        ? market.sellables.map(sellCard).join("")
        : `<div class="empty">No editable whiteboards found. Open one of your homes, use a whiteboard, and make a few marks first.</div>`}
    </div>
    ${sellForm()}
    <hr class="rule">
    <p class="eyebrow">Your adverts</p>
    <div class="list-grid">
      ${(market.my_listings || []).length
        ? market.my_listings.map(listing => `
          <article class="listing-card">
            <div class="art-frame">${canvas(listing.surface)}</div>
            <div class="listing-copy">
              <p class="byline">${money(listing.price)} Bops · ${listing.title}</p>
              <h3>${escape(listing.title)}</h3>
              <div class="actions">
                <button type="button" class="mag-btn danger" data-action="withdraw-listing" data-id="${escape(listing.id)}">Withdraw</button>
              </div>
            </div>
          </article>
        `).join("")
        : `<div class="empty">Nothing on the newsstand from you yet.</div>`}
    </div>
  `;
}

function pageContent(pageId) {
  switch (pageId) {
    case "cover": return { left: mastheadLeft(), right: coverRight() };
    case "contents": return { left: contentsLeft(), right: contentsRight() };
    case "homes": return { left: homesLeft(), right: homesRight() };
    case "keys": return { left: keysLeft(), right: keysRight() };
    case "roommates": return { left: roommateLeft(), right: roommateRight() };
    case "gallery": return { left: galleryLeft(), right: galleryRight() };
    case "floors": return { left: floorLeft(), right: floorRight() };
    case "community": return { left: communityLeft(), right: communityRight() };
    case "submit": return { left: sellLeft(), right: submitRight() };
    default: return { left: "", right: "" };
  }
}

function renderRail() {
  rail.replaceChildren();
  PAGES.forEach((page, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rail-btn";
    button.textContent = String(index + 1).padStart(2, "0");
    button.title = page.label;
    button.dataset.page = page.id;
    button.setAttribute("aria-current", index === state.page ? "page" : "false");
    rail.append(button);
  });
}

function render() {
  state.previews.clear();
  const page = currentPage();
  const content = pageContent(page.id);
  leftPage.innerHTML = `<div class="page-scroll">${content.left}</div>`;
  rightPage.innerHTML = `<div class="page-scroll">${content.right}</div>`;
  book.classList.toggle("cover", page.id === "cover");
  folio.textContent = `${String(state.page + 1).padStart(2, "0")} / ${String(PAGES.length).padStart(2, "0")} · ${page.short}`;
  wallet.textContent = money(walletValue());
  renderRail();
  paintPreviews();
  prevButton.disabled = state.page === 0;
  nextButton.disabled = state.page === PAGES.length - 1;
}

function reduceMotion() {
  return Boolean(state.host?.config?.reducedMotion
    || window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

async function turnTo(pageId, direction = 1) {
  const index = PAGE_IDS.get(pageId);
  if (index === undefined || index === state.page || state.busy) return;
  state.busy = true;
  TinyActivity.sound(direction > 0 ? "page" : "pageBack");
  try {
    await ensureData(index);
    if (reduceMotion()) {
      state.page = index;
      render();
      return;
    }
    turnLeaf.innerHTML = rightPage.innerHTML;
    turnLeaf.classList.remove("forward", "back");
    void turnLeaf.offsetWidth;
    turnLeaf.classList.add(direction > 0 ? "forward" : "back");
    state.page = index;
    render();
    await new Promise(resolve => setTimeout(resolve, 250));
    state.page = index;
    render();
    await new Promise(resolve => setTimeout(resolve, 270));
  } finally {
    turnLeaf.classList.remove("forward", "back");
    turnLeaf.innerHTML = "";
    state.busy = false;
  }
}

async function loadList(force = false) {
  if (state.list && !force) return state.list;
  setConnection("Checking the noticeboard...");
  const result = await TinyActivity.command(".tinytown list");
  state.list = result.payload || state.list;
  state.selectedHouse = state.selectedHouse || state.list?.mine?.[0]?.id || "";
  setConnection("");
  return state.list;
}

async function loadRoommates(force = false) {
  if (state.roommates && !force && state.roommates.house_id === state.selectedHouse) return state.roommates;
  const house = state.selectedHouse || state.roommates?.house_id || "";
  const result = await TinyActivity.command(`.tinytown roommates${house ? ` ${house}` : ""}`);
  state.roommates = result.payload || state.roommates;
  state.selectedHouse = state.roommates?.house_id || state.selectedHouse;
  return state.roommates;
}

async function loadMarket(force = false) {
  if (state.market && !force) return state.market;
  const result = await TinyActivity.command(".tinytown market");
  state.market = result.payload || state.market;
  return state.market;
}

async function ensureData(index) {
  const id = PAGES[index]?.id;
  if (!id) return;
  if (id === "cover" || id === "contents" || id === "homes" || id === "keys") await loadList();
  if (id === "roommates") await loadRoommates();
  if (ART_PAGES.has(id)) await loadMarket();
}

async function initialisePage() {
  const requested = String(state.host?.activity?.config?.initial_page || "cover");
  const index = PAGE_IDS.get(requested);
  state.page = index === undefined ? 0 : index;
  await ensureData(state.page);
}

async function refreshAfter(commandType) {
  if (commandType === "house") {
    await loadList(true);
    if (isArtPage()) await loadMarket(true);
  } else if (commandType === "roommates") {
    await loadRoommates(true);
    await loadList(true);
  } else if (commandType === "market") {
    await loadMarket(true);
    if (state.list) await loadList(true);
  }
}

async function runCommand(text, type) {
  if (state.busy) return;
  state.busy = true;
  setConnection("Printing the new edition...");
  try {
    const result = await TinyActivity.command(text);
    state.busy = false;
    setConnection("");
    await refreshAfter(type);
    render();
    TinyActivity.toast(result.message || "Done.");
  } catch (error) {
    state.busy = false;
    setConnection("");
    render();
    TinyActivity.toast(errorMessage(error), true);
  }
}

function buyTemplate(id) {
  if (state.pendingBuy === id) {
    state.pendingBuy = "";
    void runCommand(`.tinytown buy ${id}`, "house");
    return;
  }
  state.pendingBuy = id;
  TinyActivity.sound("select");
  render();
}

function districtFilter(id) {
  state.district = id;
  state.pendingBuy = "";
  TinyActivity.sound("select");
  render();
}

function selectHouse(id) {
  state.selectedHouse = id;
  state.roommates = null;
  TinyActivity.sound("select");
  void loadRoommates().then(render).catch(error => TinyActivity.toast(errorMessage(error), true));
}

function selectSell(key) {
  state.selectedSell = key;
  TinyActivity.sound("select");
  render();
}

function submitSell(form) {
  const title = String(form.querySelector("#sell-title")?.value || "").trim();
  const price = Number(form.querySelector("#sell-price")?.value || 0);
  if (!title) {
    TinyActivity.toast("Give the piece a title first.", true);
    return;
  }
  if (!Number.isInteger(price) || price < 1 || price > 10000) {
    TinyActivity.toast("Set a price from 1 to 10,000 Bops.", true);
    return;
  }
  const room = form.dataset.room;
  const instance = form.dataset.instance;
  state.selectedSell = "";
  void runCommand(`.tinytown sellart ${room} ${instance} ${price} ${title}`, "market");
}

document.addEventListener("click", event => {
  const pageButton = event.target.closest("[data-page]");
  if (pageButton) {
    const target = PAGE_IDS.get(pageButton.dataset.page);
    if (target !== undefined) {
      void turnTo(pageButton.dataset.page, target > state.page ? 1 : -1);
      return;
    }
  }
  const district = event.target.closest("[data-district]");
  if (district) {
    districtFilter(district.dataset.district || "");
    return;
  }
  const house = event.target.closest("[data-house]");
  if (house) {
    selectHouse(house.dataset.house || "");
    return;
  }
  const sell = event.target.closest("[data-action='select-sell']");
  if (sell) {
    selectSell(sell.dataset.key || "");
    return;
  }
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const id = action.dataset.id || "";
  TinyActivity.sound("select");
  switch (action.dataset.action) {
    case "buy": buyTemplate(id); break;
    case "cancel-buy": state.pendingBuy = ""; render(); break;
    case "confirm-buy": state.pendingBuy = ""; void runCommand(`.tinytown buy ${id}`, "house"); break;
    case "enter-house": void runCommand(`.tinytown enter ${id}`, "house"); break;
    case "visit-house": void runCommand(`.tinytown visit ${id}`, "house"); break;
    case "lock-house": void runCommand(`.tinytown lock ${id} ${action.dataset.locked === "1" ? "off" : "on"}`, "house"); break;
    case "adopt": void runCommand(`.tinytown npc adopt ${id}`, "roommates"); break;
    case "remove-npc": void runCommand(`.tinytown npc remove ${id}`, "roommates"); break;
    case "hang-art": void runCommand(`.tinytown hang ${id}`, "market"); break;
    case "floor": void runCommand(`.tinytown floor ${id}`, "market"); break;
    case "buy-listing": void runCommand(`.tinytown buyart ${id}`, "market"); break;
    case "hang-listing": void runCommand(`.tinytown hangart ${id}`, "market"); break;
    case "withdraw-listing": void runCommand(`.tinytown unlistart ${id}`, "market"); break;
    default: break;
  }
});

document.addEventListener("submit", event => {
  if (event.target.id !== "sell-form") return;
  event.preventDefault();
  submitSell(event.target);
});

prevButton.addEventListener("click", () => {
  if (state.page > 0) void turnTo(PAGES[state.page - 1].id, -1);
});
nextButton.addEventListener("click", () => {
  if (state.page < PAGES.length - 1) void turnTo(PAGES[state.page + 1].id, 1);
});
document.addEventListener("keydown", event => {
  if (event.target.matches("input, textarea, select")) return;
  if (event.key === "ArrowRight") {
    event.preventDefault();
    if (state.page < PAGES.length - 1) void turnTo(PAGES[state.page + 1].id, 1);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    if (state.page > 0) void turnTo(PAGES[state.page - 1].id, -1);
  }
});

TinyActivity.subscribe(hostState => {
  state.host = hostState;
  const roomId = currentRoomId();
  const roomChanged = state.roomId !== roomId;
  state.roomId = roomId;
  wallet.textContent = money(walletValue());
  if (!state.initialised) {
    state.initialised = true;
    void initialisePage().then(render).catch(error => {
      setConnection("");
      TinyActivity.toast(errorMessage(error), true);
      render();
    });
    return;
  }
  if (roomChanged) {
    state.market = null;
    state.list = null;
    if (isArtPage()) {
      void loadMarket(true).then(render).catch(error => TinyActivity.toast(errorMessage(error), true));
    } else if (["homes", "keys", "roommates", "contents", "cover"].includes(currentPage().id)) {
      void loadList(true).then(render).catch(error => TinyActivity.toast(errorMessage(error), true));
    }
  } else {
    wallet.textContent = money(walletValue());
  }
});

render();
if (!TinyActivity.state) setConnection("Opening the issue...");
window.setTimeout(() => {
  if (!state.host) setConnection("This issue works best inside Tinyrooms.");
}, 3000);
