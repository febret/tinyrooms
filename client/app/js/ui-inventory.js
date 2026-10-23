import { withBase } from "./base-path.js";
import { escapeHtml } from "./presentation.js";
import { buildMergeCommand, buildSwapStickerCommand } from "./commands.js";
import { cardFaceSvg } from "./card-face.js";

export function operationId(prefix) {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export async function mergeStack(deps, stackId) {
  const { store, dialogs, sendCommand, toast, showError } = deps;
  const state = store.getState();
  const stack = state.user?.inventory?.find(entry => entry.stackId === stackId);
  if (!stack) return;
  const candidates = (state.user?.inventory || []).filter(entry =>
    entry.stackId !== stackId
    && entry.definition?.id === stack.definition?.id
    && entry.quantity < (stack.definition?.stackLimit || 1)
  );
  if (!candidates.length) {
    toast("No other stack of that card has room to merge into.", "info");
    return;
  }
  let destination = candidates[0];
  if (candidates.length > 1) {
    const choice = await dialogs.choose("Merge into which stack?", candidates.map(entry => ({
      value: entry.stackId,
      label: `${entry.definition.label} ×${entry.quantity}`,
    })));
    if (!choice) return;
    destination = candidates.find(entry => entry.stackId === choice) || candidates[0];
  }
  try { await sendCommand(buildMergeCommand(stackId, destination.stackId)); } catch (error) { showError(error); }
}

export async function openStickerSwap(deps) {
  const { store, dialogs, sendCommand, showError } = deps;
  const state = store.getState();
  if (!Array.isArray(state.user?.powers) || !state.user.powers.length) {
    try { await sendCommand(".play sticker-designer replace"); } catch (error) { showError(error); }
    return;
  }
  const stickers = state.stickers || [];
  const current = state.user?.sticker || "";
  const cost = state.user?.stickerSwapCost ?? 0;
  await dialogs.open(
    `<section class="global-dialog sticker-swap" role="dialog" aria-modal="true" aria-labelledby="sticker-swap-title">
      <h2 id="sticker-swap-title">Swap Sticker</h2>
      <p>Choose a new sticker. Confirming a different sticker costs ${cost} Bops; keeping the current one is free.</p>
      <div class="sticker-grid">${stickers.map(entry => {
        const name = String(entry?.name || "");
        const imageUrl = withBase(entry?.image_url || `/assets/stickers/${name}`);
        return `<button type="button" class="sticker-choice ${name === current ? "current" : ""}" data-sticker="${escapeHtml(name)}"><img src="${escapeHtml(imageUrl)}" alt=""></button>`;
      }).join("")}</div>
      <div class="dialog-actions">
        <button type="button" class="quiet design-custom-sticker">Design a Custom Sticker…</button>
        <button type="button" class="quiet cancel-swap">Cancel</button>
      </div>
    </section>`,
    (shade, close, cancel) => {
      shade.querySelector(".cancel-swap").onclick = cancel;
      shade.querySelector(".design-custom-sticker").onclick = async () => {
        close();
        try { await sendCommand(".play sticker-designer replace"); } catch (error) { showError(error); }
      };
      shade.querySelectorAll("[data-sticker]").forEach(button => {
        button.onclick = async () => {
          const chosen = button.dataset.sticker;
          close();
          try { await sendCommand(buildSwapStickerCommand(chosen)); } catch (error) { showError(error); }
        };
      });
    },
  );
}

export async function openPack(deps, stackId) {
  if (!stackId) return;
  try {
    await deps.sendCommand(`.open_pack @card:${stackId} ${operationId("open")}`);
  } catch (error) {
    deps.showError(error);
  }
}

export function showPackReveal(deps, cards) {
  deps.playTone("success");
  deps.dialogs.open(
    `<section class="global-dialog pack-reveal" role="dialog" aria-modal="true" aria-labelledby="pack-reveal-title">
      <h2 id="pack-reveal-title">Your ${escapeHtml(cards.length)} cards</h2>
      <div class="pack-reveal-cards">${cards.map(card => `
        <figure class="pack-reveal-card">${cardFaceSvg(card, { label: card.label })}<figcaption>${escapeHtml(card.label)}</figcaption></figure>
      `).join("")}</div>
      <div class="dialog-actions"><button type="button" class="primary pack-reveal-close">Continue</button></div>
    </section>`,
    (shade, close) => {
      const button = shade.querySelector(".pack-reveal-close");
      button.onclick = close;
      button.focus({ preventScroll: true });
    },
  );
}
