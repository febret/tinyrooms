import { escapeHtml, updateMarkup } from "./presentation.js";

const STATUS_CYCLE_MS = 2400;
const PILL_COUNTERS = [
  { key: "energy", label: "Energy", maximum: "maxEnergy" },
  { key: "health", label: "Health", maximum: "maxHealth" },
  { key: "cleanliness", label: "Cleanliness", maximum: "maxCleanliness" },
];

function counterLevel(counters, key, maximum) {
  const value = Math.max(0, Number(counters?.[key] ?? 0));
  const limit = Math.max(0, Number(counters?.[maximum] ?? 0));
  if (!(limit > 0)) return 0;
  return Math.max(0, Math.min(100, (value / limit) * 100));
}

function counterText(counters, key, maximum) {
  const value = Math.floor(Number(counters?.[key] ?? 0));
  const limit = Math.max(0, Number(counters?.[maximum] ?? 0));
  return limit > 0 ? `${value}/${limit}` : `${value}`;
}

/** Choose the freshest self-peep counters/statuses, falling back to bootstrap user state. */
export function statusSnapshot(state) {
  const self = (state.room?.occupants || []).find(peep => peep.id === state.user?.id) || null;
  const counters = self?.counters || state.user?.counters || {};
  const statuses = [...(self?.statuses || state.user?.statuses || [])];
  const definitions = state.user?.statusDefinitions || {};
  return { counters, statuses, definitions };
}

export function statusButtonMarkup(state) {
  if (!state.loggedIn) return "";
  const { counters, statuses, definitions } = statusSnapshot(state);
  const pressed = state.views.main === "journal" && state.ui.journalTab === "Self";
  const summary = PILL_COUNTERS.map(entry => `${entry.label} ${counterText(counters, entry.key, entry.maximum)}`).join(" · ");
  const statusNames = statuses.map(id => definitions?.[id]?.label || id).filter(Boolean);
  const label = statusNames.length
    ? `Wellbeing: ${summary}. Active statuses: ${statusNames.join(", ")}. Open Self.`
    : `Wellbeing: ${summary}. No active statuses. Open Self.`;
  return `
    <button type="button" class="status-button${pressed ? " selected" : ""}" data-status-toggle="1"
      aria-label="${escapeHtml(label)}" aria-pressed="${pressed}" title="Wellbeing: open Self">
      <span class="status-pills" aria-hidden="true">
        ${PILL_COUNTERS.map(entry => `
          <span class="status-pill ${entry.key}" style="--fill:${counterLevel(counters, entry.key, entry.maximum).toFixed(1)}%" title="${escapeHtml(`${entry.label} ${counterText(counters, entry.key, entry.maximum)}`)}"><i></i></span>
        `).join("")}
      </span>
      ${statuses.length ? `
        <span class="status-cycle" aria-hidden="true">
          ${statuses.map(id => {
            const definition = definitions?.[id] || {};
            const glyph = String(definition.icon || "•");
            const name = String(definition.label || id);
            return `<span class="status-glyph" data-status="${escapeHtml(id)}" data-status-label="${escapeHtml(name)}" title="${escapeHtml(name)}">${escapeHtml(glyph)}</span>`;
          }).join("")}
        </span>
      ` : ""}
    </button>
  `;
}

/** Render the toolbar wellbeing button and cycle its active-status glyph. */
export function createStatusButton({ root, onAction }) {
  let statusKey = "";
  let index = 0;
  let timer = null;

  const stop = () => {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };

  const tick = () => {
    const button = root.querySelector("[data-status-toggle]");
    const glyphs = button ? [...button.querySelectorAll(".status-glyph")] : [];
    if (glyphs.length < 2) return;
    index = (index + 1) % glyphs.length;
    glyphs.forEach((glyph, position) => glyph.classList.toggle("active", position === index));
  };

  function render(state) {
    if (!root || !state.loggedIn) {
      stop();
      statusKey = "";
      if (root && root.firstChild) root.replaceChildren();
      return;
    }
    const changed = updateMarkup(root, statusButtonMarkup(state));
    const button = root.querySelector("[data-status-toggle]");
    if (!button) {
      stop();
      return;
    }
    if (changed) button.onclick = () => onAction({ type: "open-view", view: "self" });
    const glyphs = [...button.querySelectorAll(".status-glyph")];
    const key = glyphs.map(glyph => glyph.dataset.status).join("|");
    if (key !== statusKey) {
      statusKey = key;
      index = 0;
    }
    glyphs.forEach((glyph, position) => glyph.classList.toggle("active", position === index));
    const shouldCycle = glyphs.length > 1 && !state.ui.reducedMotion;
    if (shouldCycle && timer === null) timer = setInterval(tick, STATUS_CYCLE_MS);
    if (!shouldCycle) stop();
  }

  return { render, destroy: stop };
}
