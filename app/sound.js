// Sound effects using Web Audio API

// Shared audio context and cached buffers
let audioContext = null;
let bopBuffer = null;
let pageFlipBuffer = null;

// Get or create audio context
function getAudioContext() {
  if (!audioContext) {
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
  }
  return audioContext;
}

// Render bop sound to buffer (offline rendering)
function generateBopSound() {
  if (bopBuffer) {
    return bopBuffer;
  }
  
  const audioCtx = getAudioContext();
  const sampleRate = audioCtx.sampleRate;
  const duration = 0.25;
  const bufferSize = Math.floor(sampleRate * duration);
  
  // Create offline context for rendering
  const offlineCtx = new OfflineAudioContext(1, bufferSize, sampleRate);
  
  // Create oscillator with random pitch
  const osc = offlineCtx.createOscillator();
  const gain = offlineCtx.createGain();
  const filter = offlineCtx.createBiquadFilter();
  
  const frequency = 200 + Math.random() * 50;
  osc.frequency.value = frequency;
  osc.type = 'sine';
  
  // Envelope
  gain.gain.setValueAtTime(0.0, 0);
  gain.gain.linearRampToValueAtTime(0.3, 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, duration);
  
  // Filter
  filter.type = "lowpass";
  filter.frequency.value = 80;
  
  // Connect
  osc.connect(filter);
  filter.connect(gain);
  gain.connect(offlineCtx.destination);
  
  osc.start(0);
  osc.stop(duration);
  
  // Render and cache
  offlineCtx.startRendering().then(renderedBuffer => {
    bopBuffer = renderedBuffer;
  });
  
  return null; // Will be available on next call after rendering completes
}

// Generate page flip buffer
function generatePageFlipSound() {
  if (pageFlipBuffer) {
    return pageFlipBuffer;
  }
  
  const audioCtx = getAudioContext();
  const sampleRate = audioCtx.sampleRate;
  const duration = 0.5;
  const bufferSize = Math.floor(sampleRate * duration);
  
  // Create offline context for rendering
  const offlineCtx = new OfflineAudioContext(1, bufferSize, sampleRate);
  
  // Create noise buffer
  const noiseBufferSize = Math.floor(sampleRate * 0.15);
  const noiseBuffer = offlineCtx.createBuffer(1, noiseBufferSize, sampleRate);
  const output = noiseBuffer.getChannelData(0);
  
  // Generate white noise with envelope
  for (let i = 0; i < noiseBufferSize; i++) {
    const t = i / noiseBufferSize;
    const envelope = Math.pow(1 - t, 2);
    output[i] = (Math.random() * 2 - 1) * envelope * 0.3;
  }
  
  const noiseSource = offlineCtx.createBufferSource();
  noiseSource.buffer = noiseBuffer;
  
  const lowpass = offlineCtx.createBiquadFilter();
  lowpass.type = "lowpass";
  lowpass.frequency.value = 900;
  lowpass.Q.value = 1;
  
  const gain = offlineCtx.createGain();
  gain.gain.setValueAtTime(0.001, 0);
  gain.gain.linearRampToValueAtTime(1.0, 0.30);
  gain.gain.exponentialRampToValueAtTime(0.001, duration);
  
  // Connect
  noiseSource.connect(lowpass);
  lowpass.connect(gain);
  gain.connect(offlineCtx.destination);
  
  noiseSource.start(0);
  
  // Render and cache
  offlineCtx.startRendering().then(renderedBuffer => {
    pageFlipBuffer = renderedBuffer;
  });
  
  return null; // Will be available on next call after rendering completes
}

// Initialize buffers on first load
generateBopSound();
generatePageFlipSound();

// Play pre-rendered bop sound
function playBopSound() {
  if (!bopBuffer) {
    // Buffer not ready yet, regenerate and try again later
    generateBopSound();
    return;
  }
  
  const audioCtx = getAudioContext();
  const source = audioCtx.createBufferSource();
  source.buffer = bopBuffer;
  source.connect(audioCtx.destination);
  source.start(0);
}

// Play pre-rendered page flip sound
function playPageFlipSound() {
  if (!pageFlipBuffer) {
    // Buffer not ready yet, regenerate and try again later
    generatePageFlipSound();
    return;
  }
  
  const audioCtx = getAudioContext();
  const source = audioCtx.createBufferSource();
  source.buffer = pageFlipBuffer;
  source.connect(audioCtx.destination);
  source.start(0);
}

