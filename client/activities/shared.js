(() => {
  "use strict";

  document.documentElement.classList.toggle("embedded", window.parent !== window);

  const origin = window.location.origin;
  const basePath = typeof window.__TR_BASE__ === "string" ? window.__TR_BASE__ : "";
  const activityId = new URLSearchParams(window.location.search).get("session_id") || "";
  const listeners = new Set();
  const pending = new Map();
  const diagnostics = new Set();
  const feedback = document.createElement("div");
  feedback.id = "feedback";
  feedback.setAttribute("role", "status");
  feedback.setAttribute("aria-live", "polite");
  document.body.append(feedback);

  let state = null;
  let audio = null;
  let sequence = 0;
  let muted = false;
  let roomMuted = false;
  let audioDeniedShown = false;
  let toastTimer = 0;

  function escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  }

  function image(url) {
    if (!url) return "";
    let value = String(url);
    if (basePath && value.startsWith("/") && !value.startsWith("//") && value !== basePath && !value.startsWith(`${basePath}/`)) {
      value = `${basePath}${value}`;
    }
    try {
      const resolved = new URL(value, origin);
      if (resolved.origin !== origin || !/^https?:$/.test(resolved.protocol)) throw new TypeError("cross-origin");
      return resolved.href;
    } catch {
      const key = `bad-image:${String(url)}`;
      if (!diagnostics.has(key)) {
        diagnostics.add(key);
        console.warn("[Tinyrooms activity] Rejected image URL.", url);
      }
      return "";
    }
  }

  const SOUND_FILES = {
    tap: "tap.wav",
    click: "click1.wav",
    select: "click2.wav",
    cutscene: "cutscene-start.wav",
    flip: "swipe1.wav",
    page: "swipe2.wav",
    pageBack: "swipe1.wav",
    select: "click3.wav",
    coin: "ring.wav",
    stamp: "switch.wav",
    error: "retro-error.wav",
    success: "chirp3.wav",
    notify: "task-notify.wav",
    open: "door-open-old.wav",
    close: "door-close.wav",
  };
  const soundBuffers = new Map();
  const soundPending = new Map();
  const soundFailed = new Set();

  function context() {
    if (!window.AudioContext) return null;
    audio ||= new window.AudioContext();
    return audio;
  }

  function soundUrl(file) {
    const base = typeof window.__TR_BASE__ === "string" ? window.__TR_BASE__ : "";
    return `${base}/assets/sounds/${file}`;
  }

  async function loadSound(ctx, file) {
    if (soundBuffers.has(file)) return soundBuffers.get(file);
    if (soundFailed.has(file)) return null;
    if (soundPending.has(file)) return soundPending.get(file);
    const request = fetch(soundUrl(file))
      .then(response => {
        if (!response.ok) throw new Error(`Sound ${file} returned ${response.status}.`);
        return response.arrayBuffer();
      })
      .then(data => ctx.decodeAudioData(data))
      .then(buffer => {
        soundBuffers.set(file, buffer);
        soundPending.delete(file);
        return buffer;
      })
      .catch(error => {
        soundPending.delete(file);
        soundFailed.add(file);
        console.warn("[Tinyrooms activity] Unable to load sound.", error);
        return null;
      });
    soundPending.set(file, request);
    return request;
  }

  function sound(kind = "tap") {
    if (muted || roomMuted) return;
    const ctx = context();
    if (!ctx) return;
    if (ctx.state === "suspended") {
      ctx.resume().catch(error => {
        if (!audioDeniedShown) {
          audioDeniedShown = true;
          console.warn("[Tinyrooms activity] Audio resume failed.", error);
          toast("Sound is blocked by the browser. Gameplay still works.", true, false);
        }
      });
    }
    void loadSound(ctx, SOUND_FILES[kind] || SOUND_FILES.tap).then(buffer => {
      if (!buffer) return;
      const source = ctx.createBufferSource();
      const gain = ctx.createGain();
      source.buffer = buffer;
      gain.gain.value = .55;
      source.connect(gain).connect(ctx.destination);
      source.onended = () => { source.disconnect(); gain.disconnect(); };
      source.start();
    });
  }

  function toast(message, error = false, withSound = true) {
    clearTimeout(toastTimer);
    feedback.textContent = String(message || (error ? "Something went wrong." : "Done."));
    feedback.classList.toggle("error", error);
    if (withSound) sound(error ? "error" : "tap");
    toastTimer = window.setTimeout(() => {
      feedback.textContent = "";
    }, error ? 7000 : 4200);
  }

  function celebrate() {
    sound("success");
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    for (let index = 0; index < 20; index += 1) {
      const piece = document.createElement("i");
      piece.className = "confetti";
      piece.style.left = `${30 + Math.random() * 40}%`;
      piece.style.background = ["#e4be75", "#b8d2b8", "#ec9f8b"][index % 3];
      piece.style.setProperty("--drift", `${Math.random() * 240 - 120}px`);
      piece.style.animationDelay = `${Math.random() * 0.2}s`;
      document.body.append(piece);
      window.setTimeout(() => piece.remove(), 1900);
    }
  }

  function request(messageType, payload) {
    if (window.parent === window) return Promise.reject(new Error("Open this activity from Tinyrooms."));
    const requestId = `${Date.now()}-${++sequence}`;
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        pending.delete(requestId);
        reject(new Error("The Tinyrooms host did not respond in time."));
      }, 15000);
      pending.set(requestId, { resolve, reject, timer });
      window.parent.postMessage({ type: messageType, activityId, requestId, ...payload }, origin);
    });
  }

  function command(commandText) {
    return request("tinyrooms.activity.command", { command: String(commandText || "") });
  }

  function result({ result: outcome } = {}) {
    return request("tinyrooms.activity.result", { result: outcome || null });
  }

  function saveSurface(content) {
    return request("tinyrooms.activity.surface.save", { content: content || {} });
  }

  function confirmSticker(selection) {
    const payload = typeof selection === "string" ? { sticker: selection } : (selection || {});
    const message = { sticker: String(payload.sticker || "") };
    if (typeof payload.image === "string" && payload.image) message.image = payload.image;
    if (payload.design && typeof payload.design === "object") message.design = payload.design;
    return request("tinyrooms.activity.sticker.confirm", message);
  }

  function notify(message) {
    window.parent.postMessage({ type: "tinyrooms.activity.attention", activityId, message: String(message || "") }, origin);
  }

  function close(reason = "cancel") {
    window.parent.postMessage({ type: "tinyrooms.activity.close", activityId, reason }, origin);
  }

  function subscribe(listener) {
    listeners.add(listener);
    if (state) listener(state);
    return () => listeners.delete(listener);
  }

  let beforeCloseHandler = null;

  function onBeforeClose(handler) {
    beforeCloseHandler = typeof handler === "function" ? handler : null;
    return () => {
      if (beforeCloseHandler === handler) beforeCloseHandler = null;
    };
  }

  function card(id) {
    const inventory = state?.room?.inventory || state?.user?.inventory || [];
    const stack = inventory.find(item => item.definition?.id === id || item.stackId === id);
    return stack?.definition || { id, label: id, imageUrl: "" };
  }

  document.addEventListener("click", event => {
    if (event.target.closest("button")) sound();
  });
  document.addEventListener("input", event => {
    if (event.target.matches("input,select,textarea")) sound();
  });

  window.addEventListener("message", event => {
    if (event.origin !== origin || event.source !== window.parent || !event.data || typeof event.data.type !== "string") return;
    if (event.data.activityId && activityId && event.data.activityId !== activityId) return;
    if (event.data.type === "tinyrooms.host.state") {
      state = event.data.state;
      roomMuted = state?.config?.soundEnabled === false;
      listeners.forEach(listener => listener(state));
      return;
    }
    if (event.data.type === "tinyrooms.host.before-close") {
      (async () => {
        let ok = true;
        let message = "Ready to close.";
        try {
          if (beforeCloseHandler) await beforeCloseHandler();
        } catch (error) {
          ok = false;
          message = error instanceof Error ? error.message : String(error);
        }
        window.parent.postMessage({
          type: "tinyrooms.activity.before-close-result",
          activityId,
          requestId: event.data.requestId,
          ok,
          message,
        }, origin);
      })();
      return;
    }
    if (event.data.type === "tinyrooms.host.result" && pending.has(event.data.requestId)) {
      const requestState = pending.get(event.data.requestId);
      clearTimeout(requestState.timer);
      pending.delete(event.data.requestId);
      if (event.data.state) {
        state = event.data.state;
        roomMuted = state?.config?.soundEnabled === false;
        listeners.forEach(listener => listener(state));
      }
      if (event.data.ok) requestState.resolve(event.data);
      else requestState.reject(new Error(event.data.message || "The Tinyrooms host rejected that request."));
    }
  });

  window.TinyActivity = {
    escape,
    image,
    sound,
    toast,
    celebrate,
    subscribe,
    command,
    result,
    saveSurface,
    onBeforeClose,
    confirmSticker,
    notify,
    close,
    card,
    get activityId() {
      return activityId;
    },
    get state() {
      return state;
    },
    setMuted(value) {
      muted = Boolean(value);
    },
  };

  window.parent.postMessage({ type: "tinyrooms.activity.ready", activityId }, origin);

  window.setTimeout(() => {
    if (!state) {
      document.querySelectorAll(".connection").forEach(node => {
        node.textContent = window.parent === window
          ? "Open this activity from Tinyrooms."
          : "Waiting for Tinyrooms… If this persists, reopen the activity.";
      });
    }
  }, 4000);
})();
