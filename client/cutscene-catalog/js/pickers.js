import { createThumbnailManager } from "../../app/js/editing/prop-thumbnails.js";
import { withBase } from "../../app/js/base-path.js";
import { escapeHtml } from "../../app/js/presentation.js";

const thumbnails = createThumbnailManager();

export function choiceImage(choice) {
  if (choice.imageUrl) {
    return `<img class="cc-choice-image" src="${escapeHtml(withBase(choice.imageUrl))}" alt="" loading="lazy">`;
  }
  if (choice.modelUrl) {
    return `<img class="cc-choice-image" src="" alt="" data-thumb-model="${escapeHtml(withBase(choice.modelUrl))}" data-thumb-scale="${escapeHtml(String(choice.scale || 1))}">`;
  }
  return `<span class="cc-choice-image cc-choice-empty" aria-hidden="true">?</span>`;
}

export function createPicker({ dialog, title, search, list }) {
  const state = { onPick: null };

  function renderChoices(choices) {
    const needle = search.value.trim().toLowerCase();
    const visible = choices.filter(choice =>
      !needle || `${choice.label || ""} ${choice.sub || ""} ${choice.value || ""}`.toLowerCase().includes(needle));
    list.innerHTML = visible.length
      ? visible.map((choice, index) => `
        <button type="button" class="cc-choice" data-choice-index="${index}" title="Use ${escapeHtml(choice.value)}">
          ${choiceImage(choice)}
          <span class="cc-choice-label">${escapeHtml(choice.label || choice.value)}</span>
          ${choice.sub ? `<span class="cc-choice-sub">${escapeHtml(choice.sub)}</span>` : ""}
          <code class="cc-choice-value">${escapeHtml(choice.value)}</code>
        </button>`).join("")
      : `<p class="cc-empty">No matches.</p>`;
    list.querySelectorAll("[data-choice-index]").forEach(button => {
      button.onclick = () => {
        state.onPick?.(visible[Number(button.dataset.choiceIndex)]);
        dialog.close();
      };
    });
    thumbnails.sync(list);
  }

  search.oninput = () => {
    if (state.choices) renderChoices(state.choices);
  };

  return {
    open({ title: heading, choices, onPick }) {
      state.choices = choices;
      state.onPick = onPick;
      title.textContent = heading;
      search.value = "";
      renderChoices(choices);
      dialog.showModal();
    },
  };
}
