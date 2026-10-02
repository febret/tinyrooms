import { escapeHtml } from "../presentation.js";

const EMOTE_CATEGORIES = [
  { key: "Expression", heading: "Emotes" },
  { key: "Animation", heading: "Animations" },
  { key: "Cutscene", heading: "Scenes" },
];

function optionMarkup(stack, index) {
  const definition = stack.definition || {};
  const copies = stack.quantity > 1 ? `, ${stack.quantity} copies` : "";
  return `
    <button type="button" class="emote-option" data-emote-play="${escapeHtml(stack.stackId)}"
      style="--emote-index:${index}" aria-label="${escapeHtml(`${definition.label}${copies}`)}"
      title="${escapeHtml(definition.label)}">
      <img class="emote-option-art" src="${escapeHtml(definition.imageUrl)}" alt="">
    </button>
  `;
}

/** Render the horizontally expanding Emote picker anchored to the chat bar. */
export function emoteMenuMarkup(state) {
  const emotes = (state.room?.inventory || []).filter(stack => stack.definition?.type === "emote");
  const columns = EMOTE_CATEGORIES.map(({ key, heading }) => {
    const stacks = emotes.filter(stack => (stack.definition?.category || "Expression") === key);
    return `
      <section class="emote-column" data-emote-category="${key}" aria-label="${escapeHtml(heading)}">
        <div class="emote-options">
          ${stacks.length
            ? stacks.map((stack, index) => optionMarkup(stack, index)).join("")
            : '<p class="emote-empty">None yet</p>'}
        </div>
        <h3 class="emote-heading">${escapeHtml(heading)}</h3>
      </section>
    `;
  }).join("");
  return `<div class="emote-menu-track">${columns}</div>`;
}
