import { escapeHtml } from "../presentation.js";

function packCard(pack) {
  const art = pack.backImageUrl
    ? `<div class="shop-pack-art" style="background-image: url('${escapeHtml(pack.backImageUrl)}')" role="img" aria-label="${escapeHtml(pack.label)} pack art"></div>`
    : `<div class="shop-pack-art" aria-hidden="true"></div>`;
  return `
    <article class="shop-pack">
      ${art}
      <div class="shop-pack-copy">
        <strong>${escapeHtml(pack.label)}</strong>
        <p class="shop-pack-description">${escapeHtml(pack.description || "")}</p>
        <p class="shop-pack-meta">${escapeHtml(pack.size)} cards · ${escapeHtml(pack.price)} Bops</p>
      </div>
      <button type="button" class="primary" data-buy-pack="${escapeHtml(pack.id)}">Buy</button>
    </article>
  `;
}

export function shopView(state) {
  const bops = Number(state.user?.bops ?? 0);
  const packs = state.user?.packs || [];
  const list = packs.length
    ? packs.map(packCard).join("")
    : `<p class="empty-state">No card packs are available.</p>`;
  return `
    <section class="shop-view editor-dock-panel" role="region" aria-label="Card Shop">
      <header class="shop-dock-header">
        <strong>Card Shop</strong>
        <span class="shop-balance" aria-live="polite">${escapeHtml(bops)} Bops</span>
        <span class="shop-lede">Each pack opens three independent cards; duplicates are possible.</span>
        <button type="button" class="quiet" data-close-shop="1">Close</button>
      </header>
      <div class="shop-dock-body">
        <div class="shop-packs">${list}</div>
      </div>
    </section>
  `;
}
