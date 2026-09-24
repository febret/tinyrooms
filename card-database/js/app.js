import { escapeHtml } from "./util.js";

const content = document.getElementById("cdb-content");
const status = document.getElementById("cdb-status");
const search = document.getElementById("cdb-search");

let database = null;
let query = "";

function badges(card) {
  const parts = [
    `<span class="badge scope-${card.scope === "world" ? "world" : "base"}">${escapeHtml(card.scope)}</span>`,
    `<span class="badge">${escapeHtml(card.type)}</span>`,
  ];
  if (card.rarity) parts.push(`<span class="badge rarity">${escapeHtml(card.rarity)}</span>`);
  if (card.collectible) parts.push('<span class="badge">collectible</span>');
  return `<div class="badges">${parts.join("")}</div>`;
}

function details(card) {
  const lines = [];
  if (card.bonuses && Object.keys(card.bonuses).length) {
    lines.push(`Bonuses: ${Object.entries(card.bonuses).map(([key, value]) => `${key} +${value}`).join(", ")}`);
  }
  if (card.effect) lines.push(`Effect: ${card.effect}${card.amount != null ? ` (${card.amount})` : ""}`);
  if (card.target) lines.push(`Target: ${card.target}`);
  if (card.energy_cost != null) lines.push(`Energy: ${card.energy_cost}`);
  if (card.packs.length) lines.push(`Packs: ${card.packs.join(", ")}`);
  if (card.recipes.length) lines.push(`Recipes: ${card.recipes.join(", ")}`);
  return lines.map(line => `<p class="detail-line">${escapeHtml(line)}</p>`).join("");
}

function renderCards() {
  const cards = (database?.cards || []).filter(card => {
    if (!query) return true;
    const haystack = `${card.id} ${card.label} ${card.description} ${card.type} ${card.rarity || ""}`.toLowerCase();
    return haystack.includes(query);
  });
  if (!cards.length) {
    return '<p class="cdb-status">No matching cards.</p>';
  }
  return `
    <div class="card-grid">
      ${cards.map(card => `
        <article class="card-tile">
          <img src="${escapeHtml(card.image_url)}" alt="${escapeHtml(card.label)}" loading="lazy">
          <h3>${escapeHtml(card.label)}</h3>
          ${badges(card)}
          <p>${escapeHtml(card.description || "")}</p>
          ${details(card)}
        </article>
      `).join("")}
    </div>
  `;
}

function renderPacks() {
  const packs = database?.packs || [];
  if (!packs.length) return "";
  return `
    <section class="cdb-section">
      <h2>Packs</h2>
      <div class="pack-list">
        ${packs.map(pack => `
          <article class="pack-card">
            <h3>${escapeHtml(pack.label)}</h3>
            <p>${escapeHtml(pack.description || "")}</p>
            <p class="detail-line">${pack.cards.length} cards · ${escapeHtml(pack.source)}</p>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderRecipes() {
  const recipes = database?.recipes || [];
  if (!recipes.length) return "";
  return `
    <section class="cdb-section">
      <h2>Recipes</h2>
      <div class="recipe-list">
        ${recipes.map(recipe => `
          <article class="recipe-card">
            <h3>${escapeHtml(recipe.label)}</h3>
            <p>${escapeHtml(recipe.description || "")}</p>
            <p class="detail-line">In: ${recipe.ingredients.map(item => `${item.card_id}×${item.quantity}`).join(", ") || "—"}</p>
            <p class="detail-line">Out: ${recipe.output.map(item => `${item.card_id}×${item.quantity}`).join(", ") || "—"}</p>
          </article>
        `).join("")}
      </div>
    </section>
  `;
}

function renderErrors() {
  const errors = database?.errors || [];
  if (!errors.length) return "";
  return `
    <section class="cdb-section">
      <h2>Reference and validation notes</h2>
      <ul class="error-list">
        ${errors.map(error => `<li><code>${escapeHtml(error.scope)}:${escapeHtml(error.id)}</code> ${escapeHtml(error.message)}</li>`).join("")}
      </ul>
    </section>
  `;
}

function render() {
  if (!database) return;
  content.innerHTML = `
    <section class="cdb-section">
      <h2>Cards (${database.cards.length})</h2>
      ${renderCards()}
    </section>
    ${renderPacks()}
    ${renderRecipes()}
    ${renderErrors()}
  `;
}

search.addEventListener("input", event => {
  query = event.target.value.trim().toLowerCase();
  render();
});

async function boot() {
  try {
    const response = await fetch("/api/card-database", { credentials: "same-origin" });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const body = await response.json();
    database = body.database;
    render();
    status.textContent = "";
  } catch (error) {
    status.textContent = `Could not load the Card Database: ${error.message}`;
  }
}

boot();
