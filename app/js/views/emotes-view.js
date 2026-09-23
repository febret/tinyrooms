import { cardsGrid, modalShell } from "./view-helpers.js";

export function emotesView(state) {
  const category = state.ui.emoteCategory || "Expression";
  const categories = ["Expression", "Animation", "Effects"];
  const emotes = (state.room?.inventory || []).filter(stack => stack.definition?.type === "emote");
  const visible = emotes.filter(stack => {
    const value = stack.definition?.category || (stack.definition?.effect ? "Effects" : "Expression");
    return value === category;
  });
  return modalShell({
    extraClass: "emotes-view",
    ariaLabel: "Emotes",
    title: "Your Emotes",
    body: `
      <div class="emote-radial" role="group" aria-label="Emote categories">
        ${categories.map(name => `<button type="button" class="emote-category ${name === category ? "selected" : ""}" data-emote-category="${name}">${name}</button>`).join("")}
      </div>
      ${cardsGrid(visible, "emote", state.selection, `You do not own any ${category.toLowerCase()} emotes yet.`)}
    `,
  });
}
