import { closeSession, currentCutscene, openSession, resolveFrame } from "./stage.js";
import { resetPlaceholders } from "./placeholders.js";

const MAX_QUEUE = 6;
const SHELL_SELECTOR = "#app";

/**
 * Own the client-side cutscene queue and playback lifecycle.
 *
 * Playback is fire-and-forget: the manager renders whatever `cutscene.play`
 * messages arrive, in arrival order, and never reports anything back. Reduced
 * motion disables cutscenes outright, so nothing is queued at all in that case.
 */
export function createCutsceneManager({ layer, getState, onToast, onBlockingChange }) {
  const queue = [];
  const modules = new Map();
  const logged = new Set();
  let playing = false;
  let current = null;
  let warnedQueue = false;
  let lastRoomId = null;
  let lastReducedMotion = false;

  function reducedMotion() {
    return Boolean(getState()?.ui?.reducedMotion);
  }

  function roomId() {
    return getState()?.room?.id || null;
  }

  function signedIn() {
    return document.querySelector(SHELL_SELECTOR)?.dataset.auth === "in";
  }

  function connected() {
    return Boolean(getState()?.transport?.connected);
  }

  function logOnce(key, message) {
    if (logged.has(key)) return;
    logged.add(key);
    console.warn(`[Tinyrooms cutscene] ${message}`);
  }

  function stop(reason) {
    current?.stop(reason);
  }

  /** Drop pending entries, keeping non-room-bound ones when asked. */
  function clearQueue({ roomBoundOnly = false } = {}) {
    if (!queue.length) return;
    const kept = roomBoundOnly ? queue.filter(entry => !entry.roomBound) : [];
    const dropped = queue.length - kept.length;
    queue.length = 0;
    queue.push(...kept);
    if (dropped > 0) logOnce(`drop:${dropped}`, `Dropped ${dropped} queued cutscene(s).`);
  }

  /** Enqueue a `cutscene.play` message, starting it when nothing is playing. */
  function enqueue(event) {
    const cutscene = event?.cutscene;
    if (!cutscene || typeof cutscene.script_url !== "string") return;
    if (reducedMotion()) {
      logOnce("reduced", "Cutscenes are disabled while reduced motion is on.");
      return;
    }
    const roomBound = cutscene.room_bound !== false;
    const eventRoom = event.room_id || null;
    if (roomBound && eventRoom && roomId() && eventRoom !== roomId()) {
      logOnce(`stale:${eventRoom}`, "Ignored a room-bound cutscene for another room.");
      return;
    }
    const entry = {
      id: String(cutscene.id || ""),
      sourceId: String(cutscene.source?.id || ""),
      roomBound,
      roomId: eventRoom,
      cutscene,
    };
    if (queue.some(queued => queued.id === entry.id && queued.sourceId === entry.sourceId)) {
      logOnce(`duplicate:${entry.id}:${entry.sourceId}`, `Already queued ${entry.id}.`);
      return;
    }
    const limit = Math.max(1, Number(cutscene.max_queue) || 3);
    while (queue.filter(queued => queued.id === entry.id).length >= limit) {
      const index = queue.findIndex(queued => queued.id === entry.id);
      if (index < 0) break;
      queue.splice(index, 1);
      logOnce(`cap:${entry.id}`, `Queue is full for ${entry.id}; dropped the oldest.`);
    }
    if (queue.length >= MAX_QUEUE) {
      if (!warnedQueue) {
        warnedQueue = true;
        onToast?.("Your cutscene queue is full.");
      }
      logOnce("full", "Cutscene queue is full; dropping the newest.");
      return;
    }
    queue.push(entry);
    void advance();
  }

  /** Build the layer skeleton for one playback. */
  function build(entry) {
    layer.dataset.state = "loading";
    layer.hidden = false;
    const root = document.createElement("div");
    root.className = "cutscene-root";
    root.dataset.cutscene = entry.id;
    const frame = document.createElement("div");
    frame.className = "cutscene-frame";
    const stage = document.createElement("div");
    stage.className = "cutscene-stage";
    const captions = document.createElement("div");
    captions.className = "cutscene-captions";
    const skip = document.createElement("button");
    skip.type = "button";
    skip.className = "cutscene-skip";
    skip.textContent = "Skip";
    skip.hidden = entry.cutscene.skip === false;
    frame.append(stage, captions, skip);
    root.append(frame);
    layer.replaceChildren(root);
    return { root, frame, stage, captions, skip };
  }

  /** Run one frame phase, resolving when its animation ends or times out. */
  function playPhase(frame, phase, durationMs) {
    return new Promise(resolve => {
      let settled = false;
      const finish = event => {
        if (event && event.target !== frame) return;
        if (settled) return;
        settled = true;
        frame.removeEventListener("animationend", finish);
        clearTimeout(timer);
        resolve();
      };
      const timer = setTimeout(finish, durationMs + 260);
      frame.addEventListener("animationend", finish);
      frame.dataset.phase = phase;
    });
  }

  function setBlocking(active) {
    const shell = document.querySelector(SHELL_SELECTOR);
    if (shell) shell.classList.toggle("cutscene-playing", active);
    layer.dataset.blocking = active ? "1" : "0";
    onBlockingChange?.(active);
  }

  function onKeyDown(event) {
    if (event.key !== "Escape") return;
    if (!currentCutscene()?.skip) return;
    event.preventDefault();
    event.stopPropagation();
    stop("skipped");
  }

  function onLayerClick() {
    if (!currentCutscene()?.skip) return;
    stop("skipped");
  }

  /** Import a cutscene module, caching the namespace promise by URL. */
  async function importModule(url) {
    if (modules.has(url)) return modules.get(url);
    const pending = import(url).catch(error => {
      modules.delete(url);
      throw error;
    });
    modules.set(url, pending);
    return pending;
  }

  /** Play the head of the queue until it is empty. */
  async function advance() {
    if (playing) return;
    const entry = queue.shift();
    if (!entry) return;
    playing = true;
    const cutscene = entry.cutscene;
    const descriptor = resolveFrame(cutscene.frame);
    const parts = build(entry);
    let settled = false;
    let abandoned = false;
    let release;
    const bodyDone = new Promise(resolve => {
      release = resolve;
    });
    const token = {
      stop() {
        if (settled) return;
        const active = currentCutscene();
        if (!active || !active.skip) return;
        settled = true;
        release();
      },
      abandon() {
        if (settled) return;
        settled = true;
        abandoned = true;
        release();
      },
    };
    const controller = new AbortController();
    const session = openSession({
      ctx: Object.freeze({
        id: entry.id,
        title: String(cutscene.title || ""),
        frame: cutscene.frame || "plain",
        duration: Number(cutscene.duration) || 0,
        skip: cutscene.skip !== false,
        audience: cutscene.audience || "private",
        origin: cutscene.origin || "command",
        source: cutscene.source || null,
        params: Object.freeze({ ...(cutscene.params || {}) }),
        text: Array.isArray(cutscene.text) ? cutscene.text : [],
        assets: Array.isArray(cutscene.assets) ? cutscene.assets : [],
        roomId: entry.roomId,
        signal: controller.signal,
      }),
      root: parts.root,
      frame: parts.frame,
      stage: parts.stage,
      captions: parts.captions,
      controller,
      skip: token.stop,
      resolve: () => {
        if (settled) return;
        settled = true;
        release();
      },
    });
    current = token;
    document.addEventListener("keydown", onKeyDown, true);
    layer.addEventListener("click", onLayerClick);
    setBlocking(true);
    const restoreFocus = document.activeElement;
    if (parts.skip && !parts.skip.hidden) parts.skip.focus({ preventScroll: true });

    let cap = null;
    try {
      const module = await importModule(cutscene.script_url);
      const run = module?.default;
      if (typeof run !== "function") throw new Error("no default export");
      const capMs = Number(cutscene.duration) || 0;
      if (capMs > 0) cap = setTimeout(token.stop, capMs);
      const played = playPhase(parts.frame, "intro", descriptor.introMs).then(() => {
        parts.frame.dataset.phase = "body";
        layer.dataset.state = "playing";
        return run(session.ctx);
      });
      played.catch(error => {
        if (error?.name !== "AbortError") {
          console.error(`[Tinyrooms cutscene] ${entry.id} failed.`, error);
        }
      });
      await bodyDone;
      if (cap) clearTimeout(cap);
      if (!abandoned) {
        layer.dataset.state = "outro";
        await playPhase(parts.frame, "outro", descriptor.outroMs);
      }
    } catch (error) {
      console.error(`[Tinyrooms cutscene] ${entry.id} could not be played.`, error);
    } finally {
      if (cap) clearTimeout(cap);
      document.removeEventListener("keydown", onKeyDown, true);
      layer.removeEventListener("click", onLayerClick);
      setBlocking(false);
      if (restoreFocus instanceof HTMLElement && document.contains(restoreFocus)) {
        restoreFocus.focus({ preventScroll: true });
      }
      closeSession();
      parts.root.remove();
      if (!layer.childElementCount) {
        layer.hidden = true;
        layer.dataset.state = "idle";
      }
      if (current === token) current = null;
      playing = false;
      void advance();
    }
  }

  /** React to room changes, sign-out, and reduced-motion flips. */
  function sync() {
    if (!signedIn() || !connected()) {
      clearQueue();
      current?.abandon();
      return;
    }
    if (reducedMotion() !== lastReducedMotion) {
      lastReducedMotion = reducedMotion();
      if (lastReducedMotion) {
        clearQueue();
        if (playing) {
          closeSession();
          layer.replaceChildren();
          layer.hidden = true;
          layer.dataset.state = "idle";
          setBlocking(false);
        }
      }
    }
    const room = roomId();
    if (room !== lastRoomId) {
      lastRoomId = room;
      resetPlaceholders();
      if (queue.some(entry => entry.roomBound)) clearQueue({ roomBoundOnly: true });
    }
  }

  return { enqueue, sync, clearQueue };
}
