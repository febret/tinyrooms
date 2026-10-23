import test from "node:test";
import assert from "node:assert/strict";

import { lookDialogBubble, lookPreview } from "../../client/app/js/look-preview.js";

function dialogState(selection, { imageUrl = "/sticker.png", text = "Pick a topic." } = {}) {
  return {
    selection,
    room: { dialog: { peepId: "pip", peepLabel: "Pip", text } },
    description: { imageUrl, title: "Pip" },
  };
}

test("the dialog bubble appears above the selected dialog peep preview", () => {
  const state = dialogState({ kind: "peep", id: "pip" });
  const html = lookDialogBubble(state, state.description);
  assert.match(html, /look-dialog-bubble/);
  assert.match(html, /Pick a topic\./);

  const preview = lookPreview(state, state.description);
  assert.match(preview.markup, /look-preview/);
  assert.match(preview.markup, /look-dialog-bubble/);
});

test("the dialog bubble disappears when another entity is selected", () => {
  const state = dialogState({ kind: "room", id: "room" }, { imageUrl: "" });
  assert.equal(lookDialogBubble(state, state.description), "");
  assert.doesNotMatch(lookPreview(state, state.description).markup, /look-dialog-bubble/);
});
