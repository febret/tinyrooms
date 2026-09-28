// Instant inventory selling used by the Inventory's sell mode.
//
// A click sells exactly one copy with no confirmation dialog; the refreshed
// inventory arrives on the command result and is applied by the store.

import { buildSellCommand } from "./commands.js";
import { flyCoinReward } from "./coin-effects.js";
import { findInventoryCard } from "./state.js";

/** Sell one copy of an inventory stack, without a confirmation step. */
export async function sellInventoryCard(stackId, { store, sendCommand, playCoin, onError, onToast }) {
  const state = store.getState();
  const stack = findInventoryCard(state, stackId);
  if (!stack) return;
  if (stack.definition?.sellPrice == null) {
    onToast(`${stack.definition?.label || "That card"} cannot be sold.`, "info");
    return;
  }
  const tile = document.querySelector(`#panel-layer [data-stack-id="${CSS.escape(stackId)}"]`);
  const from = tile ? tile.getBoundingClientRect() : null;
  try {
    const envelope = await sendCommand(buildSellCommand(stackId, 1));
    const gained = Number(envelope?.payload?.sale?.bops_gained || 0);
    if (gained > 0) {
      const target = document.querySelector("#peeps-panel .peep-chip.self .peep-marker")
        || document.querySelector("#peeps-panel .peep-chip.self");
      playCoin();
      flyCoinReward({
        from: from || { x: window.innerWidth / 2, y: window.innerHeight / 2 },
        to: target,
        bops: gained,
        reducedMotion: state.ui.reducedMotion,
      });
    }
  } catch (error) {
    onError(error);
  }
}
