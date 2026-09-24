function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function hostPayload(state, activity) {
  return {
    user: state.user,
    room: state.room,
    stickers: state.stickers,
    activity,
    config: {
      soundEnabled: state.ui.soundEnabled,
      reducedMotion: state.ui.reducedMotion,
    },
  };
}

/** Host activity iframes and bridge strict same-origin messages to HTTP or WebSocket actions. */
export function createActivityManager({
  layer,
  getState,
  onActivityBridge,
  onCommand,
  onStickerConfirm,
  onToast,
}) {
  const windows = new Map();
  const inertBackground = new Set();
  let modalEntry = null;
  let previousFocus = null;
  let titleSequence = 0;

  function bringToFront(entry) {
    const ordered = [...windows.values()].filter(item => item !== entry);
    ordered.push(entry);
    ordered.sort((a, b) => Number(a.required) - Number(b.required));
    ordered.forEach((item, index) => { item.node.style.zIndex = String(index + 1); });
    entry.node.classList.remove("attention");
  }

  function requiredSticker(activity) {
    return activity.kind === "sticker-designer" && !getState().user?.initialStickerComplete;
  }

  function syncModal() {
    const next = [...windows.values()].find(entry => entry.required) || null;
    const changed = next !== modalEntry;
    if (!next && !changed) return;
    const globalLayer = document.querySelector("#global-modal-layer");
    const globalModalOpen = Boolean(globalLayer?.childElementCount);
    const wasModal = Boolean(modalEntry);
    if (changed) {
      for (const element of inertBackground) {
        if (!globalModalOpen || element.parentElement !== globalLayer.parentElement) element.inert = false;
      }
      inertBackground.clear();
    }
    modalEntry = next;
    if (next) {
      if (!wasModal) previousFocus = document.activeElement;
      // Global confirmations sit above onboarding and temporarily own focus/inert.
      if (globalModalOpen) return;
      // Inert siblings at every ancestor level, never the board containing the iframe.
      for (let branch = next.node; branch.parentElement; branch = branch.parentElement) {
        for (const sibling of branch.parentElement.children) {
          if (sibling === globalLayer || sibling.id === "toast-stack") continue;
          if (sibling !== branch && !sibling.inert) {
            sibling.inert = true;
            inertBackground.add(sibling);
          }
        }
        if (branch.parentElement === document.body) break;
      }
      if (changed || !next.node.contains(document.activeElement)) next.node.focus({ preventScroll: true });
    } else if (previousFocus?.isConnected && !previousFocus.closest("[inert]")) {
      previousFocus.focus({ preventScroll: true });
      previousFocus = null;
    }
  }

  document.addEventListener("focusin", event => {
    if (modalEntry && !modalEntry.node.closest("[inert]") && !document.querySelector("#global-modal-layer")?.childElementCount && !modalEntry.node.contains(event.target)) {
      modalEntry.node.focus({ preventScroll: true });
    }
  });

  new MutationObserver(syncModal).observe(layer.closest(".app-shell") || document.body, {
    subtree: true,
    childList: true,
    attributes: true,
    attributeFilter: ["inert"],
  });

  function sendState(entry) {
    entry.iframe.contentWindow?.postMessage({
      type: "tinyrooms.host.state",
      activityId: entry.activity.id,
      state: hostPayload(getState(), entry.activity),
    }, window.location.origin);
  }

  function applyGeometry(entry) {
    const frame = { width: layer.clientWidth, height: layer.clientHeight };
    const margin = Math.min(8, frame.width / 4, frame.height / 4);
    let topMargin = margin;
    const settings = document.querySelector("#settings > summary");
    if (!entry.required && settings && getComputedStyle(settings).visibility !== "hidden") {
      const control = settings.getBoundingClientRect();
      const bounds = layer.getBoundingClientRect();
      if (control.width && control.right > bounds.left && control.left < bounds.right && control.bottom > bounds.top) {
        topMargin = Math.min(Math.max(margin, control.bottom - bounds.top + margin), Math.max(margin, frame.height - margin));
      }
    }
    const availableWidth = Math.max(0, frame.width - margin * 2);
    const availableHeight = Math.max(0, frame.height - topMargin - margin);
    const expanded = entry.maximized && !entry.minimized;
    const width = Math.min(entry.required ? 820 : entry.width, availableWidth);
    entry.node.style.width = `${expanded ? availableWidth : width}px`;
    const titleHeight = (entry.titleBar.getBoundingClientRect().height || 50) + entry.node.offsetHeight - entry.node.clientHeight;
    const height = Math.min(entry.minimized ? titleHeight : entry.height, availableHeight);
    entry.node.style.height = `${expanded ? availableHeight : height}px`;
    const actualWidth = entry.node.getBoundingClientRect().width;
    const actualHeight = entry.node.getBoundingClientRect().height;
    if (entry.required) {
      entry.left = Math.max(0, (frame.width - actualWidth) / 2);
      entry.top = Math.max(0, (frame.height - actualHeight) / 2);
    } else if (expanded) {
      entry.node.style.left = `${margin}px`;
      entry.node.style.top = `${topMargin}px`;
      return;
    } else {
      entry.left = clamp(entry.left, margin, Math.max(margin, frame.width - actualWidth - margin));
      entry.top = clamp(entry.top, topMargin, Math.max(topMargin, frame.height - actualHeight - margin));
    }
    entry.node.style.left = `${entry.left}px`;
    entry.node.style.top = `${entry.top}px`;
  }

  function updateControls(entry) {
    entry.required = requiredSticker(entry.activity);
    if (entry.required) {
      entry.minimized = false;
      entry.maximized = false;
    }
    entry.node.classList.toggle("required", entry.required);
    entry.node.classList.toggle("minimized", entry.minimized);
    entry.node.classList.toggle("maximized", entry.maximized);
    entry.node.setAttribute("aria-modal", String(entry.required));
    entry.min.hidden = entry.max.hidden = entry.close.hidden = entry.required;
    entry.body.hidden = entry.minimized;
    entry.min.setAttribute("aria-label", entry.minimized ? "Restore activity" : "Minimize activity");
    entry.max.setAttribute("aria-label", entry.maximized ? "Restore activity size" : "Maximize activity");
    entry.max.setAttribute("aria-pressed", String(entry.maximized));
    entry.min.title = entry.min.getAttribute("aria-label");
    entry.max.title = entry.max.getAttribute("aria-label");
    entry.titleBar.tabIndex = entry.required ? -1 : 0;
    entry.iframe.title = entry.activity.title;
  }

  function removeWindow(id) {
    const entry = windows.get(id);
    if (!entry) return;
    entry.node.remove();
    windows.delete(id);
  }

  async function closeActivity(entry, bridgeType = "activity.cancel") {
    if (requiredSticker(entry.activity) || entry.closing) return;
    entry.closing = true;
    entry.close.disabled = true;
    try {
      await onActivityBridge(entry.activity, bridgeType);
    } catch (error) {
      onToast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      entry.closing = false;
      entry.close.disabled = false;
    }
  }

  function makeWindow(activity) {
    const node = document.createElement("section");
    node.className = "activity-window reveal";
    node.setAttribute("role", "dialog");
    node.tabIndex = -1;
    node.innerHTML = `
      <header class="activity-titlebar" aria-label="Activity window. Use arrow keys to move.">
        <div class="activity-title">
          <strong></strong>
          <span class="activity-subtitle"></span>
        </div>
        <div class="activity-controls">
          <button type="button" class="quiet activity-min" aria-label="Minimize activity">—</button>
          <button type="button" class="quiet activity-max" aria-label="Maximize activity">▢</button>
          <button type="button" class="quiet activity-close" aria-label="Close activity" title="Close activity">✕</button>
        </div>
      </header>
      <div class="activity-body">
        <iframe referrerpolicy="same-origin" sandbox="allow-scripts allow-same-origin allow-forms"></iframe>
      </div>
    `;
    const entry = {
      activity,
      node,
      iframe: node.querySelector("iframe"),
      title: node.querySelector("strong"),
      subtitle: node.querySelector(".activity-subtitle"),
      titleBar: node.querySelector(".activity-titlebar"),
      body: node.querySelector(".activity-body"),
      min: node.querySelector(".activity-min"),
      max: node.querySelector(".activity-max"),
      close: node.querySelector(".activity-close"),
      minimized: false,
      maximized: false,
      left: 28 + windows.size * 14,
      top: 24 + windows.size * 14,
      width: activity.kind === "sticker-designer" ? 760 : activity.kind === "bedrooms" ? 720 : 560,
      height: activity.kind === "sticker-designer" ? 600 : activity.kind === "bedrooms" ? 520 : 420,
    };
    entry.title.textContent = activity.title;
    entry.title.id = `activity-title-${++titleSequence}`;
    node.setAttribute("aria-labelledby", entry.title.id);
    entry.subtitle.textContent = activity.roomBound ? "Room activity" : "";
    updateControls(entry);
    const iframeControls = () => [...(entry.iframe.contentDocument?.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex="-1"])',
    ) || [])].filter(element => !element.closest("[hidden], [inert]") && element.getClientRects().length);
    node.addEventListener("keydown", event => {
      if (!entry.required || event.key !== "Tab") return;
      const controls = iframeControls();
      event.preventDefault();
      if (controls.length) controls[event.shiftKey ? controls.length - 1 : 0].focus();
    });
    entry.iframe.addEventListener("load", () => {
      const iframeDocument = entry.iframe.contentDocument;
      if (!iframeDocument) {
        onToast("The activity must load from this Tinyrooms host.", "error");
        return;
      }
      iframeDocument.addEventListener("keydown", event => {
        if (!entry.required || event.key !== "Tab") return;
        const controls = iframeControls();
        const first = controls[0];
        const last = controls.at(-1);
        if (!first) {
          event.preventDefault();
          node.focus();
        } else if ((event.shiftKey && iframeDocument.activeElement === first) || (!event.shiftKey && iframeDocument.activeElement === last)) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        }
      });
    });
    entry.iframe.src = activity.iframeUrl;
    node.addEventListener("pointerdown", () => bringToFront(entry));
    node.addEventListener("focusin", () => bringToFront(entry));
    const titleBar = entry.titleBar;
    let drag = null;
    titleBar.addEventListener("pointerdown", event => {
      if (event.target.closest("button") || event.button !== 0 || !event.isPrimary || entry.required || (entry.maximized && !entry.minimized)) return;
      event.preventDefault();
      titleBar.focus({ preventScroll: true });
      bringToFront(entry);
      drag = { id: event.pointerId, x: event.clientX, y: event.clientY, left: entry.left, top: entry.top };
      node.classList.add("dragging");
      titleBar.setPointerCapture(event.pointerId);
    });
    titleBar.addEventListener("pointermove", event => {
      if (!drag || event.pointerId !== drag.id) return;
      entry.left = drag.left + event.clientX - drag.x;
      entry.top = drag.top + event.clientY - drag.y;
      applyGeometry(entry);
    });
    const endDrag = event => {
      if (!drag || event.pointerId !== drag.id) return;
      drag = null;
      node.classList.remove("dragging");
      if (titleBar.hasPointerCapture(event.pointerId)) titleBar.releasePointerCapture(event.pointerId);
    };
    titleBar.addEventListener("pointerup", endDrag);
    titleBar.addEventListener("pointercancel", endDrag);
    titleBar.addEventListener("lostpointercapture", endDrag);
    titleBar.addEventListener("keydown", event => {
      if (event.target !== titleBar || entry.required || (entry.maximized && !entry.minimized)) return;
      const movement = { ArrowLeft: [-16, 0], ArrowRight: [16, 0], ArrowUp: [0, -16], ArrowDown: [0, 16] }[event.key];
      if (!movement) return;
      event.preventDefault();
      entry.left += movement[0];
      entry.top += movement[1];
      applyGeometry(entry);
    });
    entry.min.onclick = () => {
      if (entry.required) return;
      bringToFront(entry);
      entry.minimized = !entry.minimized;
      updateControls(entry);
      applyGeometry(entry);
      if (!entry.minimized) sendState(entry);
    };
    entry.max.onclick = () => {
      if (entry.required) return;
      bringToFront(entry);
      entry.maximized = !entry.maximized;
      entry.minimized = false;
      updateControls(entry);
      applyGeometry(entry);
      if (!entry.minimized) sendState(entry);
    };
    entry.close.onclick = () => {
      void closeActivity(entry);
    };
    layer.append(node);
    windows.set(activity.id, entry);
    applyGeometry(entry);
    bringToFront(entry);
    return entry;
  }

  window.addEventListener("message", async event => {
    if (event.origin !== window.location.origin || !event.data || typeof event.data.type !== "string") return;
    const entry = [...windows.values()].find(item => item.iframe.contentWindow === event.source);
    if (!entry) return;
    if (event.data.activityId && event.data.activityId !== entry.activity.id) return;
    if (event.data.type === "tinyrooms.activity.ready") {
      try {
        await onActivityBridge(entry.activity, "activity.ready");
      } catch (error) {
        onToast(`Activity could not report ready: ${error instanceof Error ? error.message : String(error)}`, "error");
      }
      sendState(entry);
      return;
    }
    if (event.data.type === "tinyrooms.activity.command") {
      try {
        const result = await onCommand(String(event.data.command || ""));
        entry.iframe.contentWindow?.postMessage({
          type: "tinyrooms.host.result",
          activityId: entry.activity.id,
          requestId: event.data.requestId,
          ok: true,
          message: result?.message || "Done.",
          payload: result?.payload || null,
          state: hostPayload(getState(), entry.activity),
        }, window.location.origin);
      } catch (error) {
        entry.iframe.contentWindow?.postMessage({
          type: "tinyrooms.host.result",
          activityId: entry.activity.id,
          requestId: event.data.requestId,
          ok: false,
          message: error instanceof Error ? error.message : String(error),
          payload: null,
          state: hostPayload(getState(), entry.activity),
        }, window.location.origin);
      }
      return;
    }
    if (event.data.type === "tinyrooms.activity.sticker.confirm") {
      try {
        await onStickerConfirm(String(event.data.sticker || ""));
        entry.iframe.contentWindow?.postMessage({
          type: "tinyrooms.host.result",
          activityId: entry.activity.id,
          requestId: event.data.requestId,
          ok: true,
          message: "Sticker confirmed.",
          payload: null,
          state: hostPayload(getState(), getState().activities[0] || null),
        }, window.location.origin);
      } catch (error) {
        entry.iframe.contentWindow?.postMessage({
          type: "tinyrooms.host.result",
          activityId: entry.activity.id,
          requestId: event.data.requestId,
          ok: false,
          message: error instanceof Error ? error.message : String(error),
          payload: null,
          state: hostPayload(getState(), entry.activity),
        }, window.location.origin);
      }
      return;
    }
    if (event.data.type === "tinyrooms.activity.attention") {
      try {
        const response = await onActivityBridge(entry.activity, "activity.attention", { message: String(event.data.message || "") });
        entry.activity = response.activity || entry.activity;
      } catch (error) {
        onToast(`Activity attention could not be saved: ${error instanceof Error ? error.message : String(error)}`, "error");
        entry.subtitle.textContent = "Attention could not be saved";
        if (entry.minimized) entry.node.classList.add("attention");
        return;
      }
      entry.subtitle.textContent = String(event.data.message || "Needs attention");
      if (entry.minimized) entry.node.classList.add("attention");
      onToast(String(event.data.message || `${entry.activity.title} needs attention.`), "info");
      return;
    }
    if (event.data.type === "tinyrooms.activity.close") {
      await closeActivity(entry, event.data.reason === "complete" ? "activity.complete" : "activity.cancel");
    }
  });

  new ResizeObserver(() => {
    windows.forEach(entry => applyGeometry(entry));
  }).observe(layer);

  return {
    async sync(activities) {
      const nextIds = new Set((activities || []).map(activity => activity.id));
      for (const id of [...windows.keys()]) {
        if (!nextIds.has(id)) removeWindow(id);
      }
      for (const activity of activities || []) {
        const entry = windows.get(activity.id) || makeWindow(activity);
        entry.activity = activity;
        entry.title.textContent = activity.title;
        entry.subtitle.textContent = activity.attention ? "Needs attention" : activity.roomBound ? "Room activity" : "";
        entry.node.classList.toggle("attention", Boolean(activity.attention));
        updateControls(entry);
        const nextUrl = new URL(activity.iframeUrl, window.location.origin).href;
        if (entry.iframe.src !== nextUrl) entry.iframe.src = nextUrl;
        applyGeometry(entry);
        sendState(entry);
      }
      syncModal();
    },
  };
}
