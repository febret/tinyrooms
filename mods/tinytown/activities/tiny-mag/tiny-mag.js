import { WHITEBOARD_HEIGHT, WHITEBOARD_WIDTH, drawWhiteboard } from "../../app/js/surface-canvas.js";
import { ART_PAGES, COPY, PAGES, PAGE_IDS } from "./tiny-mag-copy.js";
import { renderHomeChoices, renderRoommateLeft, renderRoommateRight } from "./tiny-mag-roommates.js";

const SPREAD_RATIO = 1.54;
const PAGE_RATIO = SPREAD_RATIO / 2;
const portraitQuery = window.matchMedia("(orientation: portrait)");

const leftPage = document.querySelector("#page-left");
const rightPage = document.querySelector("#page-right");
const book = document.querySelector("#book");
const bookFrame = document.querySelector("#book-frame");
const stage = document.querySelector(".mag-stage");
const rail = document.querySelector("#rail");
const folio = document.querySelector("#folio");
const wallet = document.querySelector("#wallet");
const connection = document.querySelector("#connection");
const turnLeaf = document.querySelector("#turn-leaf");
const prevButton = document.querySelector("#prev");
const nextButton = document.querySelector("#next");
const homeDialog = document.querySelector("#home-dialog");
const homeDialogTitle = document.querySelector("#home-dialog-title");
const homeDialogCopy = document.querySelector("#home-dialog-copy");
const homeChoices = document.querySelector("#home-choices");

const state = {
  page: 0,
  leaf: 0,
  portrait: portraitQuery.matches,
  host: null,
  list: null,
  roommates: null,
  market: null,
  pendingBuy: "",
  pendingCandidate: null,
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
    element.width = WHITEBOARD_WIDTH;
    element.height = WHITEBOARD_HEIGHT;
    const context = element.getContext("2d");
    if (!context) continue;
    drawWhiteboard(context, surface.content || surface);
  }
}

function walletValue() {
  return Number(state.host?.user?.bops ?? state.list?.wallet ?? state.market?.wallet ?? 0);
}

function currentRoomId() {
  return String(state.host?.room?.id || "");
}

function displayHouseId() {
  const mine = state.list?.mine || [];
  const current = String(state.list?.current_house_id || "");
  if (current && mine.some(house => house.id === current)) return current;
  return mine[0]?.id || "";
}

function mastheadLeft() {
  const copy = COPY.masthead;
  return `
    <p class="kicker cover-kicker"><span>${copy.issue}</span><span>${copy.publication}</span></p>
    <h1 class="masthead"><small>${copy.titleSmall}</small>${copy.titleLines.map(line => `<span class="masthead-line">${line}</span>`).join("")}</h1>
    <p class="cover-standfirst">${copy.standfirst}</p>
    <ul class="cover-lines">
      ${copy.features.map(([title, text]) => `<li><strong>${title}</strong><span>${text}</span></li>`).join("")}
    </ul>
    <div class="cover-bottom">
      <p class="cover-meta">
        <span><b>${(state.list?.templates || []).length || 20}</b> front doors</span>
        <span><b>${(state.list?.districts || []).length || 4}</b> districts</span>
        <span><b>${money(walletValue())}</b> Bops</span>
      </p>
      <span class="cover-sticker">${copy.sticker}</span>
    </div>
  `;
}

function coverRight() {
  const copy = COPY.masthead;
  const feature = state.list?.templates?.[0];
  return `
    <figure class="cover-photo">
      ${feature ? `<img src="${image(feature.preview_url)}" alt="">` : `<span class="cover-photo-fallback"></span>`}
      <div class="cover-overlay">
        <p class="kicker">${copy.coverKicker}</p>
        <h2 class="cover-title">${copy.coverTitle.map((line, index) => index === 1 ? `<em>${line}</em>` : line).join("<br>")}</h2>
        <p class="cover-dek">${copy.coverDek}</p>
      </div>
      <figcaption>
        <span>${copy.coverCaption}</span>
        <strong>${feature ? escape(feature.label) : copy.coverFallback}</strong>
        <em>${feature ? `${escape(feature.district_label)} · from ${money(feature.price)} Bops` : "from 100 Bops"}</em>
      </figcaption>
    </figure>
  `;
}

function contentsLeft() {
  const copy = COPY.contents;
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    <div class="note">${copy.note}</div>
    <span class="section-stamp">${copy.stamp}</span>
  `;
}

function contentsRight() {
  const copy = COPY.contents;
  let group = "";
  const rows = PAGES.slice(2).map((page, index) => {
    const heading = page.group !== group
      ? `<li class="contents-group"><span>${escape(page.group)}</span></li>`
      : "";
    group = page.group;
    return `${heading}
      <li data-page="${escape(page.id)}">
        <span class="num">${String(index + 3).padStart(2, "0")}</span>
        <b>${escape(page.label)}</b>
        <span class="hint">${escape(page.blurb)}</span>
      </li>`;
  }).join("");
  return `
    <p class="eyebrow">${copy.rightEyebrow}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <ul class="contents-list">${rows}</ul>
    <p class="note">${copy.walletNote} <strong>${money(walletValue())}</strong>.</p>
  `;
}

function districtNotes() {
  const districts = state.list?.districts || [];
  if (!districts.length) return "";
  return `
    <p class="eyebrow">${COPY.homes.districtEyebrow}</p>
    <div class="district-notes">
      ${districts.map(district => `
        <article>
          <h3>${escape(district.label)}</h3>
          <p class="district-tagline">${escape(district.tagline)}</p>
          <p>${escape(district.description)}</p>
        </article>
      `).join("")}
    </div>
  `;
}

function homesLeft() {
  const copy = COPY.homes;
  const available = Math.max(0, (state.list?.max_houses || 4) - (state.list?.mine?.length || 0));
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    ${districtNotes()}
    <div class="note">${copy.note}</div>
    <span class="section-stamp">${copy.stamp}: ${available}</span>
  `;
}

function templateCard(template) {
  const labels = COPY.labels;
  const pending = state.pendingBuy === template.id;
  const canAfford = walletValue() >= Number(template.price || 0);
  return `
    <article class="estate-card">
      <figure class="estate-figure">
        <img src="${image(template.preview_url)}" alt="" loading="lazy">
        <figcaption>${escape(template.district_label)} · ${escape(template.size)}</figcaption>
      </figure>
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
            ? `<button type="button" class="mag-btn" data-action="confirm-buy" data-id="${escape(template.id)}">${labels.confirm} · ${money(template.price)} Bops</button>
               <button type="button" class="mag-btn quiet" data-action="cancel-buy">${labels.cancelBuy}</button>`
            : `<button type="button" class="mag-btn" data-action="buy" data-id="${escape(template.id)}" ${canAfford ? "" : "disabled"}>
                 ${canAfford ? `${labels.buy} · ${money(template.price)} Bops` : labels.needBops}
               </button>`}
        </div>
      </div>
    </article>
  `;
}

function homesRight() {
  const copy = COPY.homes;
  const templates = state.list?.templates || [];
  const districts = state.list?.districts || [];
  const groups = districts
    .map(district => ({
      district,
      templates: templates.filter(template => template.district === district.id),
    }))
    .filter(group => group.templates.length);
  const neighbours = (state.list?.houses || []).filter(house => !house.is_owner);
  return `
    <p class="kicker">${copy.rightKicker}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <div class="property-list">
      ${groups.length ? groups.map(group => `
        <section class="district-block">
          <header class="district-heading">
            <h3>${escape(group.district.label)}</h3>
            <p>${escape(group.district.tagline)}</p>
          </header>
          <div class="list-grid">${group.templates.map(templateCard).join("")}</div>
        </section>
      `).join("") : `<div class="empty">${copy.districtEmpty}</div>`}
    </div>
    <hr class="rule">
    <p class="eyebrow">${copy.openHouses}</p>
    <div class="list-grid">
      ${neighbours.length ? neighbours.map(house => `
        <article class="estate-card compact">
          <figure class="estate-figure">
            <img src="${image(house.preview_url)}" alt="" loading="lazy">
            <figcaption>${escape(house.district_label)}</figcaption>
          </figure>
          <div class="estate-copy">
            <p class="eyebrow">${escape(house.district_label)}</p>
            <h3>${escape(house.label)}</h3>
            <p>${escape(house.owner_username)}'s place · ${house.room_count} rooms</p>
            <div class="actions">
              <button type="button" class="mag-btn quiet" data-action="visit-house" data-id="${escape(house.id)}" ${house.locked ? "disabled" : ""}>
                ${house.locked ? COPY.labels.locked : COPY.labels.visitHouse}
              </button>
            </div>
          </div>
        </article>
      `).join("") : `<div class="empty">${copy.openHousesEmpty}</div>`}
    </div>
  `;
}

function keysLeft() {
  const copy = COPY.keys;
  const mine = state.list?.mine || [];
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    <div class="fact-strip">
      <div><b>${mine.length}</b><span>keys</span></div>
      <div><b>${mine.reduce((total, house) => total + house.room_count, 0)}</b><span>rooms</span></div>
      <div><b>${money(walletValue())}</b><span>Bops</span></div>
    </div>
    <div class="note">${copy.note}</div>
    <span class="section-stamp">${mine.length} ${copy.stamp}</span>
  `;
}

function houseKey(house, { owned = false } = {}) {
  const inside = (state.list?.current_room_id || "").startsWith(`home:${house.id}:`);
  return `
    <article class="house-key">
      <figure class="house-key-figure">
        <img src="${image(house.preview_url)}" alt="" loading="lazy">
        <figcaption>${escape(house.district_label)}</figcaption>
      </figure>
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
            ${inside ? COPY.labels.enterAgain : owned ? COPY.labels.enter : house.locked ? COPY.labels.locked : COPY.labels.visit}
          </button>
          ${owned ? `<button type="button" class="mag-btn quiet" data-action="lock-house" data-id="${escape(house.id)}" data-locked="${house.locked ? "1" : "0"}">${house.locked ? COPY.labels.unlock : COPY.labels.lock}</button>` : ""}
        </div>
      </div>
    </article>
  `;
}

function keysRight() {
  const copy = COPY.keys;
  const mine = state.list?.mine || [];
  const neighbours = (state.list?.houses || []).filter(house => !house.is_owner);
  return `
    <p class="kicker">${copy.rightKicker}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <div class="list-grid">
      ${mine.length ? mine.map(house => houseKey(house, { owned: true })).join("") : `<div class="empty">${copy.mineEmpty}</div>`}
    </div>
    <hr class="rule">
    <p class="eyebrow">${copy.neighbours}</p>
    <div class="list-grid">
      ${neighbours.length ? neighbours.map(house => houseKey(house)).join("") : `<div class="empty">${copy.neighboursEmpty}</div>`}
    </div>
  `;
}

function roommateContext() {
  return { escape, image };
}

function galleryLeft() {
  const copy = COPY.gallery;
  const market = state.market;
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    ${market?.can_hang
      ? `<div class="note">${copy.noteInside} <strong>${escape(market.room?.house || "your home")} · ${escape(market.room?.label || "")}</strong>. ${market.whiteboards} of ${market.max_whiteboards} wall spaces used.</div>`
      : `<div class="note">${copy.noteOutside}</div>`}
    <span class="section-stamp">${market?.unlocked_art?.length || 0} ${copy.stamp}</span>
  `;
}

function artCard(piece, index) {
  const labels = COPY.labels;
  const owned = (state.market?.unlocked_art || []).includes(piece.id);
  const canHang = Boolean(state.market?.can_hang);
  const full = Number(state.market?.whiteboards || 0) >= Number(state.market?.max_whiteboards || 4);
  return `
    <article class="art-card">
      <div class="art-frame">${canvas(piece.surface)}</div>
      <div class="art-meta">
        <p class="eyebrow">Plate ${String(index + 1).padStart(2, "0")} · ${escape((piece.tags || []).slice(0, 2).join(" · "))}</p>
        <h3>${escape(piece.label)}</h3>
        <p>${escape(piece.description)}</p>
        <div class="price-line">
          <span class="price">${owned ? labels.collected : `${money(piece.price)} Bops`}</span>
          ${full ? `<span class="badge">Walls full</span>` : ""}
        </div>
        <div class="actions">
          <button type="button" class="mag-btn" data-action="hang-art" data-id="${escape(piece.id)}" ${(!canHang || full) ? "disabled" : ""}>
            ${!canHang ? labels.stepInside : full ? labels.makeSpace : owned ? labels.hangAnother : labels.buyHang}
          </button>
        </div>
      </div>
    </article>
  `;
}

function galleryRight() {
  const copy = COPY.gallery;
  const market = state.market;
  if (!market) return `<p class="empty">${copy.empty}</p>`;
  return `
    <p class="kicker">${copy.rightKicker}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <div class="art-grid">
      ${(market.art || []).map((piece, index) => artCard(piece, index)).join("")}
    </div>
  `;
}

function floorLeft() {
  const copy = COPY.floors;
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    <div class="note">${copy.note}</div>
    <span class="section-stamp">${copy.stamp}</span>
  `;
}

function floorRight() {
  const copy = COPY.floors;
  const market = state.market;
  if (!market) return `<p class="empty">${copy.empty}</p>`;
  return `
    <p class="kicker">${copy.rightKicker}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <div class="floor-grid">
      ${(market.floors || []).map(floor => `
        <button type="button" class="floor-chip" data-action="floor" data-id="${escape(floor.id)}" ${(!market.can_hang || floor.current) ? "disabled" : ""}>
          <img src="${image(floor.image_url)}" alt="" loading="lazy">
          <b>${escape(floor.label)}</b>
          <small>${floor.current ? COPY.labels.currentlyFitted : floor.unlocked ? COPY.labels.ownedApply : `${money(floor.price)} Bops`}</small>
        </button>
      `).join("")}
    </div>
    ${market.can_hang ? "" : `<p class="note">${copy.note}</p>`}
  `;
}

function communityLeft() {
  const copy = COPY.community;
  const market = state.market;
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    <div class="note">${market?.can_hang ? copy.noteInside : copy.noteOutside}</div>
    <span class="section-stamp">${market?.listings?.length || 0} ${copy.stamp}</span>
  `;
}

function listingCard(listing) {
  const labels = COPY.labels;
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
          <span class="price">${listing.owned ? labels.collected : `${money(listing.price)} Bops`}</span>
          ${listing.is_seller ? `<span class="badge dark">Your advert</span>` : ""}
        </div>
        <div class="actions">
          ${listing.is_seller
            ? `<button type="button" class="mag-btn danger" data-action="withdraw-listing" data-id="${escape(listing.id)}">${labels.withdraw}</button>`
            : listing.owned
              ? `<button type="button" class="mag-btn" data-action="hang-listing" data-id="${escape(listing.id)}" ${(!canHang || full) ? "disabled" : ""}>${!canHang ? labels.stepInside : full ? labels.makeSpace : labels.hangAnother}</button>`
              : `<button type="button" class="mag-btn" data-action="buy-listing" data-id="${escape(listing.id)}" ${(!canHang || full) ? "disabled" : ""}>${!canHang ? labels.stepInside : full ? labels.makeSpace : labels.collect}</button>`}
        </div>
      </div>
    </article>
  `;
}

function communityRight() {
  const copy = COPY.community;
  const market = state.market;
  if (!market) return `<p class="empty">${copy.empty}</p>`;
  return `
    <p class="kicker">${copy.rightKicker}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <div class="list-grid">
      ${(market.listings || []).length
        ? market.listings.map(listingCard).join("")
        : `<div class="empty">${copy.empty}</div>`}
    </div>
  `;
}

function sellLeft() {
  const copy = COPY.submit;
  return `
    <p class="eyebrow">${copy.eyebrow}</p>
    <h2 class="page-title">${copy.title.join("<br>")}</h2>
    <p class="dek dropcap">${copy.dek}</p>
    <div class="note">${copy.note}</div>
    <span class="section-stamp">${copy.stamp}</span>
  `;
}

function sellCard(item) {
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
          <button type="submit" class="mag-btn" id="sell-submit">${COPY.labels.submit}</button>
        </div>
      </div>
    </form>
  `;
}

function submitRight() {
  const copy = COPY.submit;
  const market = state.market;
  if (!market) return `<p class="empty">The submission desk is sharpening pencils.</p>`;
  return `
    <p class="kicker">${copy.rightKicker}</p>
    <h2 class="page-title">${copy.rightTitle}</h2>
    <p class="eyebrow">${copy.sellables}</p>
    <div class="sell-grid">
      ${(market.sellables || []).length
        ? market.sellables.map(sellCard).join("")
        : `<div class="empty">${copy.sellablesEmpty}</div>`}
    </div>
    ${sellForm()}
    <hr class="rule">
    <p class="eyebrow">${copy.adverts}</p>
    <div class="list-grid">
      ${(market.my_listings || []).length
        ? market.my_listings.map(listing => `
          <article class="listing-card">
            <div class="art-frame">${canvas(listing.surface)}</div>
            <div class="listing-copy">
              <p class="byline">${money(listing.price)} Bops · ${listing.title}</p>
              <h3>${escape(listing.title)}</h3>
              <div class="actions">
                <button type="button" class="mag-btn danger" data-action="withdraw-listing" data-id="${escape(listing.id)}">${COPY.labels.withdraw}</button>
              </div>
            </div>
          </article>
        `).join("")
        : `<div class="empty">${copy.advertsEmpty}</div>`}
    </div>
  `;
}

function pageContent(pageId) {
  const ctx = roommateContext();
  switch (pageId) {
    case "cover": return { left: mastheadLeft(), right: coverRight() };
    case "contents": return { left: contentsLeft(), right: contentsRight() };
    case "homes": return { left: homesLeft(), right: homesRight() };
    case "keys": return { left: keysLeft(), right: keysRight() };
    case "roommates": return {
      left: renderRoommateLeft(state.roommates, ctx),
      right: renderRoommateRight(state.roommates, ctx),
    };
    case "gallery": return { left: galleryLeft(), right: galleryRight() };
    case "floors": return { left: floorLeft(), right: floorRight() };
    case "community": return { left: communityLeft(), right: communityRight() };
    case "submit": return { left: sellLeft(), right: submitRight() };
    default: return { left: "", right: "" };
  }
}

function renderRail() {
  rail.replaceChildren();
  let groupName = "";
  let group = null;
  PAGES.forEach((page, index) => {
    if (page.group !== groupName) {
      groupName = page.group;
      group = document.createElement("div");
      group.className = "rail-group";
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", groupName);
      const label = document.createElement("span");
      label.className = "rail-label";
      label.textContent = groupName;
      group.append(label);
      rail.append(group);
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "rail-btn";
    button.textContent = String(index + 1).padStart(2, "0");
    button.title = page.label;
    button.dataset.page = page.id;
    button.setAttribute("aria-current", index === state.page ? "page" : "false");
    group.append(button);
  });
}

function render() {
  state.previews.clear();
  const page = currentPage();
  const content = pageContent(page.id);
  leftPage.innerHTML = `<div class="page-scroll">${content.left}</div>`;
  rightPage.innerHTML = `<div class="page-scroll">${content.right}</div>`;
  const portrait = state.portrait;
  leftPage.hidden = portrait && state.leaf !== 0;
  rightPage.hidden = portrait && state.leaf !== 1;
  leftPage.dataset.folio = String(state.page * 2 + 1).padStart(2, "0");
  rightPage.dataset.folio = String(state.page * 2 + 2).padStart(2, "0");
  book.classList.toggle("portrait", portrait);
  book.classList.toggle("landscape", !portrait);
  book.classList.toggle("cover", page.id === "cover");
  const leafLabel = state.leaf === 0 ? "left" : "right";
  folio.textContent = portrait
    ? `${String(state.page + 1).padStart(2, "0")} / ${String(PAGES.length).padStart(2, "0")} · ${page.short} · ${leafLabel}`
    : `${String(state.page + 1).padStart(2, "0")} / ${String(PAGES.length).padStart(2, "0")} · ${page.short}`;
  wallet.textContent = money(walletValue());
  renderRail();
  paintPreviews();
  const atStart = state.page === 0 && (!portrait || state.leaf === 0);
  const atEnd = state.page === PAGES.length - 1 && (!portrait || state.leaf === 1);
  prevButton.disabled = atStart;
  nextButton.disabled = atEnd;
  window.requestAnimationFrame(fitBook);
}

function fitBook() {
  if (!stage) return;
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  if (!width || !height) return;
  const ratio = state.portrait ? PAGE_RATIO : SPREAD_RATIO;
  let bookWidth = Math.min(width, height * ratio);
  let bookHeight = bookWidth / ratio;
  if (bookHeight > height) {
    bookHeight = height;
    bookWidth = bookHeight * ratio;
  }
  bookFrame.style.width = `${Math.floor(bookWidth)}px`;
  bookFrame.style.height = `${Math.floor(bookHeight)}px`;
}

function reduceMotion() {
  return Boolean(state.host?.config?.reducedMotion
    || window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches);
}

function visibleLeafMarkup() {
  if (!state.portrait) return rightPage.innerHTML;
  return state.leaf === 0 ? leftPage.innerHTML : rightPage.innerHTML;
}

async function turnTo(pageId, direction = 1, { leaf = 0 } = {}) {
  const index = PAGE_IDS.get(pageId);
  if (index === undefined || state.busy) return;
  await moveTo({ page: index, leaf }, direction);
}

async function moveTo(target, direction = 1) {
  const page = Math.max(0, Math.min(PAGES.length - 1, target.page));
  const leaf = state.portrait ? Math.max(0, Math.min(1, target.leaf ?? 0)) : 0;
  if (state.busy || (page === state.page && leaf === state.leaf)) return;
  state.busy = true;
  TinyActivity.sound(direction > 0 ? "page" : "pageBack");
  try {
    await ensureData(page);
    if (reduceMotion()) {
      state.page = page;
      state.leaf = leaf;
      render();
      return;
    }
    turnLeaf.innerHTML = visibleLeafMarkup();
    turnLeaf.classList.remove("forward", "back");
    void turnLeaf.offsetWidth;
    turnLeaf.classList.add(direction > 0 ? "forward" : "back");
    state.page = page;
    state.leaf = leaf;
    render();
    await new Promise(resolve => setTimeout(resolve, 250));
    render();
    await new Promise(resolve => setTimeout(resolve, 270));
  } finally {
    turnLeaf.classList.remove("forward", "back");
    turnLeaf.innerHTML = "";
    state.busy = false;
  }
}

function step(direction) {
  if (state.portrait) {
    if (direction > 0) {
      if (state.leaf === 0) void moveTo({ page: state.page, leaf: 1 }, 1);
      else if (state.page < PAGES.length - 1) void moveTo({ page: state.page + 1, leaf: 0 }, 1);
    } else if (state.leaf === 1) {
      void moveTo({ page: state.page, leaf: 0 }, -1);
    } else if (state.page > 0) {
      void moveTo({ page: state.page - 1, leaf: 1 }, -1);
    }
    return;
  }
  if (direction > 0 && state.page < PAGES.length - 1) void moveTo({ page: state.page + 1, leaf: 0 }, 1);
  if (direction < 0 && state.page > 0) void moveTo({ page: state.page - 1, leaf: 0 }, -1);
}

async function loadList(force = false) {
  if (state.list && !force) return state.list;
  setConnection("Checking the noticeboard...");
  const result = await TinyActivity.command(".tinytown list");
  state.list = result.payload || state.list;
  setConnection("");
  return state.list;
}

async function loadRoommates(force = false) {
  const house = displayHouseId();
  if (state.roommates && !force && state.roommates.house_id === house) return state.roommates;
  const result = await TinyActivity.command(`.tinytown roommates${house ? ` ${house}` : ""}`);
  state.roommates = result.payload || state.roommates;
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
  await loadList();
  if (id === "roommates") await loadRoommates();
  if (ART_PAGES.has(id)) await loadMarket();
}

async function initialisePage() {
  const requested = String(state.host?.activity?.config?.initial_page || "cover");
  const index = PAGE_IDS.get(requested);
  state.page = index === undefined ? 0 : index;
  state.leaf = 0;
  await ensureData(state.page);
}

async function refreshAfter(commandType) {
  if (commandType === "house") {
    await loadList(true);
    if (isArtPage()) await loadMarket(true);
  } else if (commandType === "roommates") {
    await loadList(true);
    await loadRoommates(true);
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

function openHomeDialog(candidateId) {
  const candidate = (state.roommates?.candidates || []).find(item => item.id === candidateId);
  if (!candidate) return;
  const houses = state.list?.mine || [];
  if (!houses.length) {
    TinyActivity.toast(COPY.dialog.noHouse, true);
    return;
  }
  state.pendingCandidate = candidate;
  homeDialogTitle.textContent = COPY.dialog.title;
  homeDialogCopy.textContent = `${candidate.name} has answered the advert. ${COPY.dialog.copy}`;
  homeChoices.innerHTML = renderHomeChoices(houses, { escape });
  TinyActivity.sound("select");
  homeDialog.showModal();
  homeChoices.querySelector("button:not(:disabled)")?.focus();
}

function closeHomeDialog() {
  state.pendingCandidate = null;
  if (homeDialog.open) homeDialog.close();
}

function assignHome(houseId) {
  const candidate = state.pendingCandidate;
  if (!candidate || !houseId) return;
  closeHomeDialog();
  void runCommand(`.tinytown npc adopt ${candidate.id} ${houseId}`, "roommates");
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
    case "invite": openHomeDialog(id); break;
    case "assign-home": assignHome(id); break;
    case "close-home": closeHomeDialog(); break;
    case "remove-npc": void runCommand(`.tinytown npc remove ${id}`, "roommates"); break;
    case "hang-art": void runCommand(`.tinytown hang ${id}`, "market"); break;
    case "floor": void runCommand(`.tinytown floor ${id}`, "market"); break;
    case "buy-listing": void runCommand(`.tinytown buyart ${id}`, "market"); break;
    case "hang-listing": void runCommand(`.tinytown hangart ${id}`, "market"); break;
    case "withdraw-listing": void runCommand(`.tinytown unlistart ${id}`, "market"); break;
    default: break;
  }
});

homeDialog.addEventListener("click", event => {
  if (event.target === homeDialog) closeHomeDialog();
});
homeDialog.addEventListener("close", () => {
  state.pendingCandidate = null;
});

document.addEventListener("submit", event => {
  if (event.target.id !== "sell-form") return;
  event.preventDefault();
  submitSell(event.target);
});

prevButton.addEventListener("click", () => step(-1));
nextButton.addEventListener("click", () => step(1));
document.addEventListener("keydown", event => {
  if (event.target.matches("input, textarea, select")) return;
  if (event.key === "ArrowRight") {
    event.preventDefault();
    step(1);
  } else if (event.key === "ArrowLeft") {
    event.preventDefault();
    step(-1);
  }
});

function onOrientationChange() {
  state.portrait = portraitQuery.matches;
  state.leaf = 0;
  render();
}
portraitQuery.addEventListener?.("change", onOrientationChange);
window.addEventListener("resize", () => window.requestAnimationFrame(fitBook));

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
    state.roommates = null;
    const pageId = currentPage().id;
    void (async () => {
      await loadList(true);
      if (ART_PAGES.has(pageId)) await loadMarket(true);
      if (pageId === "roommates") await loadRoommates(true);
      render();
    })().catch(error => TinyActivity.toast(errorMessage(error), true));
  } else {
    wallet.textContent = money(walletValue());
  }
});

render();
if (!TinyActivity.state) setConnection("Opening the issue...");
window.setTimeout(() => {
  if (!state.host) setConnection("This issue works best inside Tinyrooms.");
}, 3000);
