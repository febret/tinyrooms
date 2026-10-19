import * as THREE from "three";

const RANDOM_ANIMATION_PAUSE_MS = 1000;

function createRecordMixer(record, model) {
  const mixer = new THREE.AnimationMixer(model);
  record.mixers.push(mixer);
  return mixer;
}

function startLoopedClip(record, model, clip) {
  createRecordMixer(record, model).clipAction(clip).setLoop(THREE.LoopRepeat, Infinity).play();
}

function startRandomClips(record, model, clips, isActive) {
  const mixer = createRecordMixer(record, model);
  let lastIndex = -1;
  function pick() {
    if (!isActive()) return;
    let index = Math.floor(Math.random() * clips.length);
    if (clips.length > 1) {
      while (index === lastIndex) index = Math.floor(Math.random() * clips.length);
    }
    lastIndex = index;
    const action = mixer.clipAction(clips[index]);
    action.reset();
    action.setLoop(THREE.LoopOnce, 1);
    action.clampWhenFinished = true;
    const onFinished = event => {
      if (event.action !== action) return;
      mixer.removeEventListener("finished", onFinished);
      if (!isActive()) return;
      record.animTimers.push(setTimeout(pick, RANDOM_ANIMATION_PAUSE_MS));
    };
    mixer.addEventListener("finished", onFinished);
    action.play();
  }
  pick();
}

/** Start the prop animation named in the room snapshot, if any. */
export function playPropAnimation(entry, record, prop, model, clips, isCurrent) {
  // Respect reduced-motion preferences; also keeps rendered frames deterministic.
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  const mode = typeof prop.animation === "string" ? prop.animation.trim() : "";
  if (!mode) return;
  if (!clips || !clips.length) {
    console.warn(`Prop ${prop.id} requests animation "${mode}" but the model has no animations.`);
    return;
  }
  if (mode === "auto") {
    startLoopedClip(record, model, clips[0]);
    return;
  }
  const isActive = () => isCurrent(entry) && entry.props.get(record.id) === record;
  if (mode === "random") {
    startRandomClips(record, model, clips, isActive);
    return;
  }
  const clip = clips.find(candidate => candidate.name === mode);
  if (!clip) {
    console.warn(`Prop ${prop.id} requests unknown animation "${mode}".`);
    return;
  }
  startLoopedClip(record, model, clip);
}
