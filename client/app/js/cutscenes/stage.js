import { BUILTIN_FRAMES, DEFAULT_FRAME } from "./frames.js";
import { assetSource, placeholderBox, spriteForAsset } from "./placeholders.js";
import { cardFaceSvg } from "../card-face.js";

const frames = new Map(Object.entries(BUILTIN_FRAMES));
let session = null;
let warned = new Set();

/** Log a stage misuse once per message. */
function warnOnce(key, message) {
  if (warned.has(key)) return;
  warned.add(key);
  console.warn(`[Tinyrooms cutscene] ${message}`);
}

/** Register a frame type from a cutscene module's top level. */
export function registerCutsceneFrame(name, descriptor) {
  const key = String(name || "").trim();
  if (!key || !descriptor || typeof descriptor.cssClass !== "string") {
    warnOnce("descriptor", "A frame registration needs a name and a cssClass.");
    return;
  }
  if (frames.has(key) && !BUILTIN_FRAMES[key]) {
    warnOnce(key, `Frame type '${key}' is already registered.`);
    return;
  }
  const fallback = BUILTIN_FRAMES[key] || BUILTIN_FRAMES[DEFAULT_FRAME];
  // Descriptor ms values feed manager phase waits; omitted values/from inherit
  // the named built-in or plain. Custom duplicates are rejected; built-ins may
  // currently be replaced. build decorates the stage with merged frame options.
  frames.set(key, {
    cssClass: descriptor.cssClass,
    introMs: Number.isFinite(descriptor.introMs) ? descriptor.introMs : fallback.introMs,
    outroMs: Number.isFinite(descriptor.outroMs) ? descriptor.outroMs : fallback.outroMs,
    from: typeof descriptor.from === "string" ? descriptor.from : fallback.from,
    build: typeof descriptor.build === "function" ? descriptor.build : null,
  });
}

/** Return every registered frame name. */
export function frameNames() {
  return [...frames.keys()];
}

/** Return a frame descriptor, falling back to the plain frame. */
export function resolveFrame(name) {
  const key = String(name || "").trim();
  if (frames.has(key)) return { name: key, ...frames.get(key) };
  if (key) warnOnce(`frame:${key}`, `Unknown frame type '${key}'; using ${DEFAULT_FRAME}.`);
  return { name: DEFAULT_FRAME, ...frames.get(DEFAULT_FRAME) };
}

function requireSession() {
  if (!session) {
    warnOnce("session", "Stage helpers were called outside a playing cutscene.");
    return null;
  }
  return session;
}

/** Return the live cutscene context, or null. */
export function currentCutscene() {
  return session ? session.ctx : null;
}

/** Return the live abort signal, or a signal that never aborts. */
function currentSignal() {
  if (session) return session.controller.signal;
  return new AbortController().signal;
}

/** Create the cutscene stage for the current playback and return its root node. */
export function beginCutscene(frameType, options) {
  const active = requireSession();
  if (!active) return null;
  if (active.stageCreated) return active.stage;
  const frame = resolveFrame(frameType || active.ctx.frame);
  // Explicit options shallowly override params.frame_options. from defaults to
  // the descriptor edge; positive duration sets CSS animation ms, not the play
  // cap or manager phase waits. background/accent are CSS colors; radius is px.
  // Unset style options retain stylesheet defaults; extra keys reach frame.build.
  const settings = { ...(active.ctx.params?.frame_options || {}), ...(options || {}) };
  const from = typeof settings.from === "string" ? settings.from : frame.from;
  const duration = Number(settings.duration);
  active.frame.className = `cutscene-frame ${frame.cssClass}`;
  active.frame.dataset.from = from;
  active.frame.dataset.cutscene = active.ctx.id;
  const frameStyle = active.frame.style;
  if (duration > 0) frameStyle.setProperty("--cutscene-frame-duration", `${duration}ms`);
  if (typeof settings.background === "string") frameStyle.setProperty("--cutscene-stage-background", settings.background);
  if (typeof settings.accent === "string") frameStyle.setProperty("--cutscene-accent", settings.accent);
  if (typeof settings.radius === "number") active.stage.style.borderRadius = `${settings.radius}px`;
  if (frame.build) {
    try {
      frame.build(active.stage, settings);
    } catch (error) {
      console.error("[Tinyrooms cutscene] Frame build failed.", error);
    }
  }
  active.frame.setAttribute("role", "dialog");
  active.frame.setAttribute("aria-label", active.ctx.title || "Cutscene");
  active.stage.dataset.cutsceneStage = active.ctx.id;
  active.root.dataset.state = "playing";
  active.root.hidden = false;
  active.stageCreated = true;
  // Return only the stage: the specified dom.frame/dom.root conveniences are absent.
  return active.stage;
}

/** End the current playback early; the frame outro still plays. */
export function endCutscene(result) {
  const active = requireSession();
  if (!active) return;
  // Requests body completion without awaiting outro; the manager ignores result.
  active.resolve(result);
}

/** Abort the current playback the way a user skip does. */
export function skipCutscene() {
  const active = requireSession();
  if (!active) return;
  // Despite the abort wording above, this currently only requests completion
  // when ctx.skip allows it; signal abort is deferred until closeSession.
  active.skip();
}

/** Resolve after a delay, or reject when the cutscene is aborted. */
export function wait(ms) {
  // Abort rejects with AbortError; outside playback there is no session to cancel it.
  const delay = Math.max(0, Number(ms) || 0);
  return new Promise((resolve, reject) => {
    const signal = currentSignal();
    const timer = setTimeout(() => {
      cleanup();
      resolve();
    }, delay);
    const onAbort = () => {
      cleanup();
      reject(new DOMException("The cutscene ended.", "AbortError"));
    };
    function cleanup() {
      clearTimeout(timer);
      if (session) session.timers.delete(timer);
      signal.removeEventListener("abort", onAbort);
    }
    if (session) session.timers.add(timer);
    if (signal.aborted) onAbort();
    else signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Play one sound through the host audio engine during this cutscene. */
export function sound(nameOrUrl) {
  const active = requireSession();
  if (active) active.sound?.(nameOrUrl);
}

/** Write one caption into the frame's caption region. */
export function caption(cue, options) {
  const active = requireSession();
  // Render immediately (cue.at is ignored here). Missing text/speaker are empty;
  // cue.style and options.className add classes. The handle hides only this line.
  const text = typeof cue === "string" ? cue : cue?.say || "";
  const speaker = typeof cue === "string" ? "" : cue?.speaker || "";
  const element = document.createElement("p");
  element.className = "cutscene-caption";
  if (typeof cue === "object" && cue?.style) element.classList.add(cue.style);
  if (options?.className) element.classList.add(options.className);
  if (speaker) {
    const name = document.createElement("span");
    name.className = "cutscene-caption-speaker";
    name.textContent = speaker;
    element.append(name);
  }
  element.append(document.createTextNode(text));
  if (active) {
    active.captions.append(element);
    return { element, hide: () => element.remove() };
  }
  return { element, hide: () => element.remove() };
}

/** Play a cue list on its scheduled offsets, resolving when the last one clears. */
export async function captions(cues) {
  // Offsets are milliseconds from this call, not session/body start. Lines
  // accumulate, then all clear 1600ms after the last cue. Closing before scheduled
  // cues fire clears their timers without settling those cue promises.
  const list = Array.isArray(cues) ? cues : [];
  if (!list.length) return;
  const handles = [];
  const timers = [];
  for (const cue of list) {
    const delay = Math.max(0, Number(cue?.at) || 0);
    timers.push(
      new Promise(resolve => {
        const timer = setTimeout(() => {
          if (session) session.timers.delete(timer);
          if (cue?.sound) session?.sound?.(cue.sound);
          handles.push(caption(cue));
          resolve();
        }, delay);
        if (session) session.timers.add(timer);
      }),
    );
  }
  await Promise.all(timers);
  await wait(1600);
  for (const handle of handles) handle.hide();
}

function findAsset(ctx, ref) {
  if (!ctx || !Array.isArray(ctx.assets)) return undefined;
  return ctx.assets.find(asset => asset.ref === ref);
}

/** Return the raw asset record for a placeholder reference. */
export function asset(ref) {
  return findAsset(currentCutscene(), ref);
}

/** Return a synchronous image URL for a sticker or card, or an empty string. */
export function spriteUrl(ref) {
  const record = findAsset(currentCutscene(), ref);
  if (!record || record.kind === "prop") return "";
  return assetSource(record);
}

/** Resolve one placeholder into a ready-to-insert element. */
export async function sprite(ref, options) {
  // Match the server's exact ref; never derive paths from tokens. Props await a
  // thumbnail image, not a canvas. label supplies fallback text/alt; className
  // replaces classes on resolved sprites. Missing records return a box directly.
  const record = findAsset(currentCutscene(), ref);
  if (!record) return placeholderBox(typeof options?.label === "string" ? { label: options.label } : null);
  const element = await spriteForAsset(record);
  if (typeof options?.className === "string") element.className = options.className;
  if (options?.label) element.alt = options.label;
  return element;
}

/**
 * Resolve a card placeholder into its full composed face (an SVG inside a
 * wrapper element). `sprite()` stays the illustration/animation for cards used
 * as scene objects; use this for reveals that present the card itself.
 */
export async function cardFace(ref, options) {
  const record = findAsset(currentCutscene(), ref);
  if (record?.kind !== "card" || !record.definition) return sprite(ref, options);
  const wrapper = document.createElement("div");
  wrapper.className = typeof options?.className === "string" ? options.className : "cutscene-card-face";
  wrapper.innerHTML = cardFaceSvg(record.definition, { label: options?.label || record.label || "" });
  return wrapper;
}

/** Resolve several placeholders together. */
export function sprites(refs) {
  const list = Array.isArray(refs) ? refs : [];
  return Promise.all(list.map(ref => sprite(ref)));
}

/** Create the playback session record used by the manager and the stage helpers. */
export function openSession({ ctx, root, frame, stage, captions: captionRegion, controller, skip, resolve, sound: playSound }) {
  if (!(controller instanceof AbortController)) {
    throw new Error("A cutscene playback needs an AbortController.");
  }
  session = {
    ctx,
    root,
    frame,
    stage,
    captions: captionRegion,
    skip,
    resolve,
    sound: playSound,
    controller,
    timers: new Set(),
    stageCreated: false,
    // Session-open monotonic time, before import/intro; captions does not use it.
    startedAt: performance.now(),
  };
  return session;
}

/** Abort and clear the live session, cancelling every runtime-owned timer. */
export function closeSession() {
  if (!session) return;
  const active = session;
  session = null;
  for (const timer of active.timers) clearTimeout(timer);
  active.timers.clear();
  if (!active.controller.signal.aborted) active.controller.abort();
}
