import { escapeHtml } from "./presentation.js";

/** Manage full-application dialogs, their focus, and consistent cancellation. */
export function createDialogs(layer) {
  const entries = [];
  function refreshInert() {
    const shell = layer.parentElement;
    for (const child of shell.children) {
      if (child !== layer && child.id !== "toast-stack") {
        child.inert = entries.length > 0;
      }
    }
  }
  function open(markup, onReady, onCancel = () => {}) {
    const previous = document.activeElement;
    const shade = document.createElement("div");
    shade.className = "global-shade";
    shade.innerHTML = markup;
    const entry = { shade, cancel };
    function close() {
      const index = entries.indexOf(entry);
      if (index < 0) return;
      entries.splice(index, 1);
      shade.remove();
      refreshInert();
      if (previous?.isConnected && !previous.closest("[inert]")) previous.focus({ preventScroll: true });
    }
    function cancel() { close(); onCancel(); }
    entries.push(entry);
    layer.append(shade);
    refreshInert();
    shade.addEventListener("keydown", event => {
      if (event.key !== "Tab") return;
      const controls = [...shade.querySelectorAll('button:not(:disabled),input:not(:disabled),[tabindex="0"]')];
      if (!controls.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    onReady?.(shade, close, cancel);
    return close;
  }
  return {
    open,
    get active() { return entries.length > 0; },
    cancel() { entries.at(-1)?.cancel(); },
    closeAll() { while (entries.length) entries.at(-1).cancel(); },
    confirm(title, message, acceptLabel = "Continue") {
      return new Promise(resolve => {
        open(`<section class="global-dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
          <h2 id="dialog-title">${escapeHtml(title)}</h2><p>${escapeHtml(message)}</p>
          <div class="dialog-actions"><button type="button" class="cancel">Cancel</button>
          <button type="button" class="primary accept">${escapeHtml(acceptLabel)}</button></div></section>`,
        (shade, close, cancel) => {
          shade.querySelector(".cancel").onclick = cancel;
          shade.querySelector(".accept").onclick = () => { close(); resolve(true); };
          shade.querySelector(".cancel").focus();
        }, () => resolve(false));
      });
    },
    quantity(intent, max) {
      return new Promise(resolve => {
        open(`<section class="global-dialog compact" role="dialog" aria-modal="true" aria-labelledby="qty-title">
          <h2 id="qty-title">${intent === "pickup" ? "Pick up cards" : "Drop cards"}</h2>
          <p>Choose how many cards to ${intent === "pickup" ? "pick up" : "drop"}.</p>
          <input class="qty-input" type="range" min="1" max="${max}" value="1" aria-label="Quantity">
          <div class="qty-row"><output class="qty-output">1</output><span>of ${max}</span></div>
          <div class="dialog-actions"><button type="button" class="cancel">Cancel</button>
          <button type="button" class="primary accept">Confirm</button></div></section>`,
        (shade, close, cancel) => {
          const input = shade.querySelector(".qty-input");
          input.oninput = () => { shade.querySelector(".qty-output").value = input.value; };
          shade.querySelector(".cancel").onclick = cancel;
          shade.querySelector(".accept").onclick = () => { close(); resolve(Number(input.value)); };
          input.focus();
        }, () => resolve(null));
      });
    },
    description(title, text) {
      open(`<section class="global-dialog" role="dialog" aria-modal="true" aria-labelledby="description-title">
        <h2 id="description-title">${escapeHtml(title)}</h2><p>${escapeHtml(text)}</p>
        <div class="dialog-actions"><button type="button" class="close">Close</button></div></section>`,
      (shade, close) => { shade.querySelector("button").onclick = close; shade.querySelector("button").focus(); });
    },
  };
}
