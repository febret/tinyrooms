let context;
let resumePending = false;
let warned = false;

/** Play a quiet physical card rustle/click or a short result chime. */
export function playSound(kind, enabled) {
  if (!enabled) return;
  const AudioContext = window.AudioContext || window.webkitAudioContext;
  if (!AudioContext) {
    if (!warned) console.warn("This browser does not support Tinyrooms interaction audio.");
    warned = true;
    return;
  }
  context ||= new AudioContext();
  if (context.state === "suspended" && !resumePending) {
    resumePending = true;
    context.resume().then(() => { resumePending = false; }, error => {
      resumePending = false;
      console.warn("Unable to resume interaction audio. Check browser sound permissions.", error);
    });
  }
  const duration = kind === "flip" ? .15 : .06;
  const buffer = context.createBuffer(1, Math.ceil(context.sampleRate * duration), context.sampleRate);
  const samples = buffer.getChannelData(0);
  for (let i = 0; i < samples.length; i++) samples[i] = (Math.random() * 2 - 1) * (1 - i / samples.length) ** 2;
  const source = context.createBufferSource();
  source.buffer = buffer;
  const filter = context.createBiquadFilter();
  filter.type = "bandpass";
  filter.frequency.value = kind === "flip" ? 1750 : 750;
  const gain = context.createGain();
  gain.gain.value = kind === "flip" ? .11 : .07;
  source.connect(filter).connect(gain).connect(context.destination);
  source.onended = () => { source.disconnect(); filter.disconnect(); gain.disconnect(); };
  source.start();
  const notes = kind === "error" ? [180, 130] : kind === "success" ? [523, 659, 784] : [];
  notes.forEach((frequency, index) => {
    const oscillator = context.createOscillator();
    const envelope = context.createGain();
    const when = context.currentTime + index * .06;
    oscillator.frequency.value = frequency;
    envelope.gain.setValueAtTime(.0001, when);
    envelope.gain.linearRampToValueAtTime(.035, when + .01);
    envelope.gain.exponentialRampToValueAtTime(.0001, when + .18);
    oscillator.connect(envelope).connect(context.destination);
    oscillator.onended = () => { oscillator.disconnect(); envelope.disconnect(); };
    oscillator.start(when);
    oscillator.stop(when + .2);
  });
}
