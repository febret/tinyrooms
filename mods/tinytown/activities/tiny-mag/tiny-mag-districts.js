import { COPY } from "./tiny-mag-copy.js";

export function districtTemplates(list, districtId) {
  return (list?.templates || []).filter(template => template.district === districtId);
}

export function districtPriceRange(entries, money) {
  if (!entries.length) return "";
  const prices = entries.map(entry => Number(entry.price || 0));
  return `${entries.length} doors · soon yours · from ${money(Math.min(...prices))} Bops`;
}

function buyActions(template, ctx) {
  const labels = COPY.labels;
  if (Number(template.owned || 0) > 0) {
    return `<button type="button" class="mag-btn quiet district-buy" disabled>${labels.ownedOne}</button>`;
  }
  const pending = ctx.pendingBuy === template.id;
  const canAfford = ctx.wallet >= Number(template.price || 0);
  if (pending) {
    return `<button type="button" class="mag-btn district-buy" data-action="confirm-buy" data-id="${ctx.escape(template.id)}">${labels.confirm} · ${ctx.money(template.price)} Bops</button>
      <button type="button" class="mag-btn quiet district-buy" data-action="cancel-buy">${labels.cancelBuy}</button>`;
  }
  return `<button type="button" class="mag-btn district-buy" data-action="buy" data-id="${ctx.escape(template.id)}" ${canAfford ? "" : "disabled"}>
    ${canAfford ? `${labels.buy} · ${ctx.money(template.price)} Bops` : labels.needBops}
  </button>`;
}

function unlockLine(template, ctx) {
  const unlocks = template.unlocks || [];
  if (!unlocks.length) return "";
  const names = unlocks
    .map(entry => `<em title="${ctx.escape(entry.label)} · ${entry.prop_count} props">${ctx.escape(entry.label)}</em>`)
    .join(", ");
  return `<p class="prop-unlocks" title="${ctx.escape(unlocks.map(entry => `${entry.label} (${entry.prop_count} props)`).join(", "))}"><span>${COPY.labels.unlocks}:</span> ${names}</p>`;
}

function districtCard(template, ctx, variant) {
  return `
    <article class="district-home district-home--${variant}">
      <figure class="district-figure">
        <img src="${ctx.image(template.preview_url)}" alt="" loading="lazy">
      </figure>
      <div class="district-home-copy">
        <p class="eyebrow">${ctx.escape(template.size)} · ${template.room_count} rooms</p>
        <h3>${ctx.escape(template.label)}</h3>
        <p class="district-home-dek">${ctx.escape(template.description)}</p>
        ${unlockLine(template, ctx)}
        <div class="price-line">
          <span class="price">${ctx.money(template.price)} Bops</span>
          ${template.owned ? `<span class="badge good">Owned</span>` : ""}
        </div>
        <div class="actions">${buyActions(template, ctx)}</div>
      </div>
    </article>
  `;
}

export function renderDistrictLeft(district, entries, ctx) {
  const copy = COPY.districts;
  const [hero, second] = entries;
  return `
    <div class="district-spread district-spread--left">
      <header class="district-masthead">
        <p class="eyebrow">${copy.eyebrow}</p>
        <h2 class="page-title district-title">${ctx.escape(district.label)}</h2>
        <p class="district-tagline">${ctx.escape(district.tagline)}</p>
        <p class="dek dropcap district-dek">${ctx.escape(district.description)}</p>
        <p class="district-facts">${districtPriceRange(entries, ctx.money)}</p>
      </header>
      <div class="district-homes district-homes--left">
        ${hero ? districtCard(hero, ctx, "hero") : ""}
        ${second ? districtCard(second, ctx, "row") : ""}
      </div>
      <div class="note district-note">${copy.note}</div>
    </div>
  `;
}

export function renderDistrictRight(district, entries, ctx) {
  const rest = entries.slice(2);
  const [wide, tall, small] = rest;
  return `
    <div class="district-spread district-spread--right">
      <p class="kicker">${COPY.districts.rightKicker} · ${ctx.escape(district.label)}</p>
      <div class="district-homes district-homes--right">
        ${wide ? districtCard(wide, ctx, "wide") : ""}
        <div class="district-pair">
          ${tall ? districtCard(tall, ctx, "tall") : ""}
          ${small ? districtCard(small, ctx, "small") : ""}
        </div>
      </div>
    </div>
  `;
}

export function renderDistrictEmpty(district, ctx) {
  return `
    <div class="district-spread">
      <p class="eyebrow">${COPY.districts.eyebrow}</p>
      <h2 class="page-title district-title">${ctx.escape(district.label)}</h2>
      <div class="empty">${COPY.districts.districtEmpty}</div>
    </div>
  `;
}
