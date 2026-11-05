// Tiny 8-bit synth for the Hacker Collective. No audio files; every bleep is
// generated so the activity needs no new sound assets.

const PRESETS = {
  tap: { wave: "square", from: 520, to: 420, ms: 60, gain: 0.08 },
  key: { wave: "square", from: 880, to: 880, ms: 35, gain: 0.05 },
  good: { wave: "triangle", from: 640, to: 980, ms: 170, gain: 0.1 },
  bad: { wave: "sawtooth", from: 210, to: 120, ms: 220, gain: 0.09 },
  open: { wave: "square", from: 320, to: 720, ms: 260, gain: 0.08 },
  node: { wave: "triangle", from: 480, to: 960, ms: 320, gain: 0.12 },
  core: { wave: "square", from: 360, to: 1180, ms: 620, gain: 0.11 },
  fail: { wave: "sawtooth", from: 300, to: 90, ms: 420, gain: 0.1 },
  tick: { wave: "square", from: 1200, to: 1200, ms: 20, gain: 0.03 },
};

export function createAudio(enabled = () => true) {
  let context = null;
  let muted = false;

  function ctx() {
    if (muted || !enabled()) return null;
    if (!window.AudioContext) return null;
    if (!context) {
      try {
        context = new window.AudioContext();
      } catch {
        return null;
      }
    }
    if (context.state === "suspended") void context.resume();
    return context;
  }

  function blip(kind = "tap") {
    const audio = ctx();
    if (!audio) return;
    const preset = PRESETS[kind] || PRESETS.tap;
    const now = audio.currentTime;
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.type = preset.wave;
    oscillator.frequency.setValueAtTime(Math.max(40, preset.from), now);
    oscillator.frequency.exponentialRampToValueAtTime(Math.max(40, preset.to), now + preset.ms / 1000);
    gain.gain.setValueAtTime(preset.gain, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + preset.ms / 1000);
    oscillator.connect(gain).connect(audio.destination);
    oscillator.start(now);
    oscillator.stop(now + preset.ms / 1000 + 0.02);
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
    };
  }

  function sweep(from, to, seconds = 0.5) {
    const audio = ctx();
    if (!audio) return;
    const now = audio.currentTime;
    const oscillator = audio.createOscillator();
    const gain = audio.createGain();
    oscillator.type = "sawtooth";
    oscillator.frequency.setValueAtTime(from, now);
    oscillator.frequency.exponentialRampToValueAtTime(to, now + seconds);
    gain.gain.setValueAtTime(0.06, now);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + seconds);
    oscillator.connect(gain).connect(audio.destination);
    oscillator.start(now);
    oscillator.stop(now + seconds + 0.02);
  }

  return {
    blip,
    sweep,
    setMuted(value) {
      muted = Boolean(value);
    },
    get muted() {
      return muted;
    },
  };
}
