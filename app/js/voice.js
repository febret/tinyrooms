let container = null;

const TALK_DURATION_MS = 10_000;
const TALK_TICK_MS = 100;

function audioContainer() {
  if (!container) {
    container = document.createElement("div");
    container.id = "voice-audio";
    container.setAttribute("aria-hidden", "true");
    container.style.display = "none";
    document.body.append(container);
  }
  return container;
}

function supported() {
  return typeof window !== "undefined"
    && Boolean(window.RTCPeerConnection)
    && Boolean(navigator.mediaDevices?.getUserMedia);
}

function closePeer(entry) {
  try { entry.pc.onicecandidate = null; } catch { /* ignore */ }
  try { entry.pc.ontrack = null; } catch { /* ignore */ }
  try { entry.pc.onconnectionstatechange = null; } catch { /* ignore */ }
  try { entry.pc.close(); } catch { /* ignore */ }
  if (entry.audio) {
    entry.audio.srcObject = null;
    entry.audio.remove();
  }
}

/**
 * Manage direct peer-to-peer audio for users in the same room.
 *
 * The smaller account id is the deterministic offerer so two peers never
 * create competing offers. Remote audio elements are hidden but stay in the
 * document so browser autoplay (granted by the enable gesture) keeps working.
 */
export function createVoiceChat({ sendSignal, sendPresence, onError, onStateChange, onTalk }) {
  const peers = new Map();
  let localStream = null;
  let iceServers = [];
  let selfId = "";
  let enabled = false;
  let muted = false;
  let talking = false;
  let talkTimer = null;
  let talkDuration = TALK_DURATION_MS;
  let talkEndsAt = 0;

  function state() {
    return { enabled, muted, talking, peerCount: peers.size, supported: supported() };
  }

  function emit() {
    onStateChange?.(state());
  }

  function applyTrackEnabled() {
    const live = enabled && !muted && talking;
    for (const track of localStream?.getAudioTracks() || []) track.enabled = live;
  }

  function notifyTalk() {
    const remaining = talking ? Math.max(0, talkEndsAt - performance.now()) : 0;
    onTalk?.({ talking, remainingMs: remaining, durationMs: talkDuration });
  }

  function fail(error) {
    const message = error instanceof Error ? error.message : String(error);
    onError?.(message);
  }

  function ensurePeer(accountId) {
    let entry = peers.get(accountId);
    if (entry) return entry;
    const pc = new RTCPeerConnection({ iceServers });
    const audio = new Audio();
    audio.autoplay = true;
    audio.playsInline = true;
    audio.dataset.peerId = accountId;
    audioContainer().append(audio);
    entry = { pc, audio, pendingCandidates: [], hasRemote: false, state: "connecting" };
    peers.set(accountId, entry);
    for (const track of localStream?.getTracks() || []) pc.addTrack(track, localStream);
    pc.onicecandidate = event => {
      if (!event.candidate) return;
      void sendSignal?.(accountId, {
        kind: "candidate",
        candidate: event.candidate.candidate,
        sdp_mid: event.candidate.sdpMid || "",
        sdp_m_line_index: event.candidate.sdpMLineIndex ?? 0,
      });
    };
    pc.ontrack = event => {
      entry.audio.srcObject = event.streams[0] || new MediaStream([event.track]);
      entry.audio.play().catch(() => {});
    };
    pc.onconnectionstatechange = () => {
      entry.state = pc.connectionState;
      emit();
      if (["failed", "closed"].includes(pc.connectionState)) dropPeer(accountId);
    };
    emit();
    return entry;
  }

  function dropPeer(accountId) {
    const entry = peers.get(accountId);
    if (!entry) return;
    peers.delete(accountId);
    closePeer(entry);
    emit();
  }

  async function flushCandidates(entry) {
    const queued = entry.pendingCandidates.splice(0);
    for (const candidate of queued) {
      try { await entry.pc.addIceCandidate(candidate); } catch { /* stale candidate */ }
    }
  }

  async function offerTo(accountId) {
    const entry = ensurePeer(accountId);
    if (entry.offering) return;
    entry.offering = true;
    try {
      const offer = await entry.pc.createOffer();
      await entry.pc.setLocalDescription(offer);
      await sendSignal?.(accountId, { kind: "offer", sdp: entry.pc.localDescription.sdp });
    } finally {
      entry.offering = false;
    }
  }

  async function handleSignal(envelope) {
    const from = String(envelope.from || "");
    if (!from || from === selfId) return;
    const { signal } = envelope;
    if (!signal) return;
    if (signal.kind === "bye") {
      dropPeer(from);
      return;
    }
    const entry = ensurePeer(from);
    try {
      if (signal.kind === "offer" || signal.kind === "answer") {
        await entry.pc.setRemoteDescription({ type: signal.kind, sdp: signal.sdp });
        entry.hasRemote = true;
        await flushCandidates(entry);
        if (signal.kind === "offer") {
          const answer = await entry.pc.createAnswer();
          await entry.pc.setLocalDescription(answer);
          await sendSignal?.(from, { kind: "answer", sdp: entry.pc.localDescription.sdp });
        }
      } else if (signal.kind === "candidate") {
        const candidate = {
          candidate: signal.candidate,
          sdpMid: signal.sdp_mid ?? "",
          sdpMLineIndex: signal.sdp_m_line_index ?? 0,
        };
        if (entry.hasRemote) await entry.pc.addIceCandidate(candidate);
        else entry.pendingCandidates.push(candidate);
      }
    } catch (error) {
      fail(error);
    }
  }

  function reconcile(enabledIds) {
    if (!enabled) return;
    const wanted = new Set(enabledIds.filter(id => id && id !== selfId));
    for (const accountId of [...peers.keys()]) {
      if (!wanted.has(accountId)) dropPeer(accountId);
    }
    for (const accountId of wanted) {
      ensurePeer(accountId);
      if (selfId < accountId && !peers.get(accountId).offered) {
        peers.get(accountId).offered = true;
        offerTo(accountId);
      }
    }
  }

  async function enable() {
    if (!supported()) throw new Error("Audio chat is not supported in this browser.");
    if (enabled) return;
    localStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    muted = false;
    talking = false;
    enabled = true;
    applyTrackEnabled();
    emit();
    notifyTalk();
    await sendPresenceSafe(true);
  }

  async function sendPresenceSafe(value) {
    try {
      await sendPresence?.(value);
    } catch (error) {
      fail(error);
    }
  }

  function disable() {
    if (!enabled && !localStream && peers.size === 0) return;
    stopTalk();
    enabled = false;
    muted = false;
    for (const accountId of [...peers.keys()]) {
      void sendSignal?.(accountId, { kind: "bye" });
      dropPeer(accountId);
    }
    for (const track of localStream?.getTracks() || []) track.stop();
    localStream = null;
    emit();
    void sendPresenceSafe(false);
  }

  function reset() {
    stopTalk();
    enabled = false;
    muted = false;
    for (const accountId of [...peers.keys()]) dropPeer(accountId);
    for (const track of localStream?.getTracks() || []) track.stop();
    localStream = null;
    emit();
  }

  function toggleMute() {
    muted = !muted;
    if (muted) stopTalk();
    applyTrackEnabled();
    emit();
    return muted;
  }

  function startTalk() {
    if (!enabled || muted || talking) return;
    talking = true;
    talkDuration = TALK_DURATION_MS;
    talkEndsAt = performance.now() + talkDuration;
    applyTrackEnabled();
    emit();
    notifyTalk();
    talkTimer = setInterval(tickTalk, TALK_TICK_MS);
  }

  function tickTalk() {
    if (!talking) return;
    if (performance.now() >= talkEndsAt) {
      stopTalk();
      return;
    }
    notifyTalk();
  }

  function stopTalk() {
    const wasTalking = talking;
    talking = false;
    if (talkTimer) {
      clearInterval(talkTimer);
      talkTimer = null;
    }
    applyTrackEnabled();
    if (wasTalking) emit();
    notifyTalk();
  }

  function toggleTalk() {
    if (talking) stopTalk();
    else startTalk();
  }

  function configure({ iceServers: servers, selfId: accountId } = {}) {
    if (Array.isArray(servers)) iceServers = servers;
    if (accountId) selfId = String(accountId);
  }

  function isEnabled() { return enabled; }
  function isMuted() { return muted; }
  function isTalking() { return talking; }

  return {
    configure,
    enable,
    disable,
    reset,
    toggleMute,
    startTalk,
    stopTalk,
    toggleTalk,
    handleSignal,
    reconcile,
    isEnabled,
    isMuted,
    isTalking,
    getState: state,
  };
}
