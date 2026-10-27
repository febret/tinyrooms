function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

const MOBILE_LAYOUT_QUERY = "(max-width: 780px), (orientation: portrait), (max-height: 550px)";

function mobileLayout() {
  return typeof window.matchMedia === "function" && window.matchMedia(MOBILE_LAYOUT_QUERY).matches;
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
  pillRoot,
  getState,
  onActivityBridge,
  onCommand,
  onStickerConfirm,
  onToast,
}) {
  const windows = new Map();
  const inertBackground = new Set();
  const shell = layer.closest(".app-shell") || document.body;
  let modalEntry = null;
  let previousFocus = null;
  let titleSequence = 0;

  function syncMaximized() {
    shell.classList.toggle("activity-maximized", [...windows.values()].some(entry => !entry.minimized));
  }

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

  function syncPill(entry) {
    if (!entry.pill) return;
    const label = `Restore ${entry.activity.title}`;
    entry.pill.hidden = !entry.minimized;
    if (entry.pill.textContent !== entry.activity.title) entry.pill.textContent = entry.activity.title;
    entry.pill.classList.toggle("attention", entry.minimized && Boolean(entry.activity.attention));
    if (entry.pill.getAttribute("aria-label") !== label) entry.pill.setAttribute("aria-label", label);
    entry.pill.title = label;
  }

  /**
   * Fill the space between the peep sidebar, the top heading bar, and the bottom
   * interaction UI. The layer itself is inset to that region, so the window
   * simply fills it edge to edge.
   */
  function applyGeometry(entry) {
    if (entry.minimized) return;
    const frame = { width: layer.clientWidth, height: layer.clientHeight };
    if (entry.required) {
      const margin = Math.min(8, frame.width / 4, frame.height / 4);
      const availableWidth = Math.max(0, frame.width - margin * 2);
      const availableHeight = Math.max(0, frame.height - margin * 2);
      entry.node.style.width = `${Math.min(900, availableWidth)}px`;
      entry.node.style.height = `${Math.min(entry.height, availableHeight)}px`;
      const actualWidth = entry.node.getBoundingClientRect().width;
      const actualHeight = entry.node.getBoundingClientRect().height;
      entry.node.style.left = `${Math.max(0, (frame.width - actualWidth) / 2)}px`;
      entry.node.style.top = `${Math.max(0, (frame.height - actualHeight) / 2)}px`;
      return;
    }
    // On phones the window fills the whole client, including the topbar and the
    // bottom interaction bars; on desktop it starts below the topbar.
    const top = mobileLayout()
      ? 0
      : clamp((document.querySelector(".topbar")?.getBoundingClientRect().bottom ?? layer.getBoundingClientRect().top)
        - layer.getBoundingClientRect().top + 8, 0, frame.height);
    entry.node.style.left = "0px";
    entry.node.style.top = `${top}px`;
    entry.node.style.width = `${frame.width}px`;
    entry.node.style.height = `${Math.max(0, frame.height - top)}px`;
  }

  function updateControls(entry) {
    entry.required = requiredSticker(entry.activity);
    if (entry.required) entry.minimized = false;
    entry.node.classList.toggle("required", entry.required);
    entry.node.setAttribute("aria-modal", String(entry.required));
    entry.min.hidden = entry.required;
    entry.close.hidden = entry.required;
    entry.node.hidden = entry.minimized;
    entry.iframe.title = entry.activity.title;
    syncPill(entry);
  }

  function restoreActivity(entry) {
    if (entry.required || !entry.minimized) return;
    entry.minimized = false;
    bringToFront(entry);
    updateControls(entry);
    applyGeometry(entry);
    sendState(entry);
    syncMaximized();
    entry.node.focus({ preventScroll: true });
  }

  function removeWindow(id) {
    const entry = windows.get(id);
    if (!entry) return;
    entry.node.remove();
    entry.pill?.remove();
    windows.delete(id);
    syncMaximized();
  }

  async function closeActivity(entry, bridgeType = "activity.cancel") {
    if (requiredSticker(entry.activity) || entry.closing) return;
    entry.closing = true;
    entry.close.disabled = true;
    try {
      const flush = await flushActivity(entry);
      if (!flush.ok && !flush.timedOut) {
        onToast(flush.message || "The whiteboard could not be saved before closing.", "error");
        return;
      }
      if (!flush.ok && flush.timedOut) {
        onToast(flush.message || "The whiteboard did not respond before closing.", "error");
      }
      await onActivityBridge(entry.activity, bridgeType);
    } catch (error) {
      onToast(error instanceof Error ? error.message : String(error), "error");
    } finally {
      entry.closing = false;
      entry.close.disabled = false;
    }
  }

  let flushSequence = 0;
  const flushWaiters = new Map();

  function flushActivity(entry) {
    if (entry.activity.kind !== "whiteboard" || !entry.iframe.contentWindow) {
      return Promise.resolve({ ok: true });
    }
    const requestId = `flush-${Date.now()}-${++flushSequence}`;
    return new Promise(resolve => {
      const timer = window.setTimeout(() => {
        flushWaiters.delete(requestId);
        resolve({ ok: false, timedOut: true, message: "The whiteboard did not respond before closing." });
      }, 6000);
      flushWaiters.set(requestId, { resolve, timer });
      entry.iframe.contentWindow.postMessage({
        type: "tinyrooms.host.before-close",
        activityId: entry.activity.id,
        requestId,
      }, window.location.origin);
    });
  }

  function makeWindow(activity) {
    const node = document.createElement("section");
    node.className = "activity-window reveal";
    node.setAttribute("role", "dialog");
    node.tabIndex = -1;
    node.innerHTML = `
      <header class="activity-titlebar" aria-label="Activity window">
        <div class="activity-title">
          <strong></strong>
          <span class="activity-subtitle"></span>
        </div>
        <div class="activity-controls">
          <button type="button" class="quiet activity-min" aria-label="Minimize activity" title="Minimize activity">—</button>
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
      min: node.querySelector(".activity-min"),
      close: node.querySelector(".activity-close"),
      minimized: false,
      height: activity.kind === "sticker-designer" ? 640 : 560,
    };
    if (pillRoot) {
      entry.pill = document.createElement("button");
      entry.pill.type = "button";
      entry.pill.className = "activity-pill";
      entry.pill.hidden = true;
      entry.pill.onclick = () => restoreActivity(entry);
      pillRoot.append(entry.pill);
    }
    entry.title.textContent = activity.title;
    entry.title.id = `activity-title-${++titleSequence}`;
    node.setAttribute("aria-labelledby", entry.title.id);
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
    entry.min.onclick = () => {
      if (entry.required) return;
      bringToFront(entry);
      entry.minimized = true;
      updateControls(entry);
      syncMaximized();
    };
    entry.close.onclick = () => {
      void closeActivity(entry);
    };
    layer.append(node);
    windows.set(activity.id, entry);
    applyGeometry(entry);
    bringToFront(entry);
    syncMaximized();
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
    if (event.data.type === "tinyrooms.activity.before-close-result") {
      const waiter = flushWaiters.get(event.data.requestId);
      if (waiter) {
        window.clearTimeout(waiter.timer);
        flushWaiters.delete(event.data.requestId);
        waiter.resolve({
          ok: event.data.ok !== false,
          message: String(event.data.message || ""),
        });
      }
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
    if (event.data.type === "tinyrooms.activity.result") {
      try {
        const response = await onActivityBridge(entry.activity, "activity.result", {
          result: event.data.result,
          token: entry.activity.token,
        });
        entry.iframe.contentWindow?.postMessage({
          type: "tinyrooms.host.result",
          activityId: entry.activity.id,
          requestId: event.data.requestId,
          ok: true,
          message: "Result recorded.",
          payload: {
            records: response.records || null,
            recorded: Boolean(response.recorded),
            seconds: response.seconds ?? null,
          },
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
    if (event.data.type === "tinyrooms.activity.surface.save") {
      try {
        const response = await onActivityBridge(entry.activity, "activity.surface", {
          content: event.data.content || {},
        });
        entry.iframe.contentWindow?.postMessage({
          type: "tinyrooms.host.result",
          activityId: entry.activity.id,
          requestId: event.data.requestId,
          ok: true,
          message: "Whiteboard saved.",
          payload: { surface: response.surface || null },
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
        const selection = { sticker: String(event.data.sticker || "") };
        if (typeof event.data.image === "string" && event.data.image) selection.image = event.data.image;
        if (event.data.design && typeof event.data.design === "object") selection.design = event.data.design;
        await onStickerConfirm(selection);
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
        return;
      }
      entry.subtitle.textContent = String(event.data.message || "Needs attention");
      syncPill(entry);
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
        entry.subtitle.textContent = activity.attention ? "Needs attention" : "";
        entry.node.classList.toggle("attention", Boolean(activity.attention));
        updateControls(entry);
        const nextUrl = new URL(activity.iframeUrl, window.location.origin).href;
        if (entry.iframe.src !== nextUrl) entry.iframe.src = nextUrl;
        applyGeometry(entry);
        sendState(entry);
      }
      syncMaximized();
      syncModal();
    },
  };
}
