import { withBase } from "./base-path.js";

const SOUND_FILE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]*\.wav$/;
const PLAY_GAIN = 0.55;

const UI_SOUND_FILES = {
  tap: "tap.wav",
  click: "click1.wav",
  select: "click2.wav",
  flip: "swipe1.wav",
  card: "switch.wav",
  coin: "ring.wav",
  error: "retro-error.wav",
  success: "chirp3.wav",
  notify: "tick1.wav",
  room: "steps.wav",
  open: "door-open-old.wav",
  close: "door-close.wav",
  toggle: "switch.wav",
  cutscene: "cutscene-start.wav",
};

let context;
let resumePending = false;
let warned = false;
const buffers = new Map();
const pending = new Map();
const failed = new Set();

/** Resolve a semantic alias or file name to a library file name. */
export function resolveSoundFile(nameOrAlias) {
  const value = String(nameOrAlias || "").trim();
  if (!value) return "";
  if (UI_SOUND_FILES[value]) return UI_SOUND_FILES[value];
  if (value.includes("..")) return "";
  const name = value.split(/[\\/]/).pop() || "";
  return SOUND_FILE_PATTERN.test(name) ? name : "";
}

/** Return the served URL for a semantic alias or sound file name. */
export function soundUrl(nameOrAlias) {
  const file = resolveSoundFile(nameOrAlias);
  return file ? withBase(`/assets/sounds/${file}`) : "";
}

function audioContext() {
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) {
    if (!warned) console.warn("This browser does not support Tinyrooms interaction audio.");
    warned = true;
    return null;
  }
  try {
    context ||= new AudioContext();
    return context;
  } catch (error) {
    if (!warned) console.warn("Unable to start Tinyrooms interaction audio.", error);
    warned = true;
    return null;
  }
}

async function resumeContext(target) {
  if (target.state !== "suspended" || resumePending) return;
  resumePending = true;
  try {
    await target.resume();
  } catch (error) {
    console.warn("Unable to resume interaction audio. Check browser sound permissions.", error);
  } finally {
    resumePending = false;
  }
}

async function loadSound(target, file) {
  if (buffers.has(file)) return buffers.get(file);
  if (failed.has(file)) return null;
  if (pending.has(file)) return pending.get(file);
  const request = fetch(soundUrl(file))
    .then(response => {
      if (!response.ok) throw new Error(`Sound ${file} returned ${response.status}.`);
      return response.arrayBuffer();
    })
    .then(data => target.decodeAudioData(data))
    .then(buffer => {
      buffers.set(file, buffer);
      pending.delete(file);
      return buffer;
    })
    .catch(error => {
      pending.delete(file);
      failed.add(file);
      if (!warned) console.warn(`Unable to load sound '${file}'.`, error);
      warned = true;
      return null;
    });
  pending.set(file, request);
  return request;
}

async function playFile(file) {
  const target = audioContext();
  if (!target) return;
  await resumeContext(target);
  const buffer = await loadSound(target, file);
  if (!buffer) return;
  const source = target.createBufferSource();
  source.buffer = buffer;
  const gain = target.createGain();
  gain.gain.value = PLAY_GAIN;
  source.connect(gain).connect(target.destination);
  source.onended = () => {
    source.disconnect();
    gain.disconnect();
  };
  source.start();
}

/** Play one sound from the shared library; accepts aliases or file names. */
export function playSound(nameOrAlias, enabled) {
  if (!enabled) return;
  const file = resolveSoundFile(nameOrAlias);
  if (!file) {
    if (!warned) console.warn(`Unknown Tinyrooms sound '${nameOrAlias}'.`);
    warned = true;
    return;
  }
  void playFile(file);
}

/** Warm the decoder cache for common interaction sounds. */
export function preloadSounds(names) {
  const target = audioContext();
  if (!target) return;
  for (const name of names || []) {
    const file = resolveSoundFile(name);
    if (file) void loadSound(target, file);
  }
}
