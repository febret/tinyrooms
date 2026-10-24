import { PATHS } from "./api.js";
import { withBase } from "./base-path.js";

function websocketUrl() {
  const url = new URL(withBase(PATHS.websocket), window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}

function requestId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Connect to /ws, route envelopes, and resolve one promise per command request_id. */
export function createSocketClient({
  onStatus,
  onSnapshot,
  onRoomEvent,
  onRtcSignal,
  onSessionReplaced,
  onProfileResync,
  onErrorEnvelope,
  onResult,
  reconnectBaseMs = 1000,
  reconnectMaxMs = 30000,
}) {
  let socket = null;
  const pending = new Map();
  let reconnectTimer = null;
  let reconnectAttempt = 0;
  let manualClose = false;

  function status(transport) {
    onStatus?.(transport);
  }

  function clearReconnectTimer() {
    if (reconnectTimer === null) return;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  function scheduleReconnect() {
    if (reconnectTimer !== null) return;
    reconnectAttempt += 1;
    const delay = Math.min(reconnectMaxMs, reconnectBaseMs * 2 ** (reconnectAttempt - 1));
    status({ connected: false, status: "reconnecting", message: "Connection lost. Reconnecting…" });
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, delay);
  }

  function settlePending(envelope) {
    if (!pending.has(envelope.request_id)) return;
    const request = pending.get(envelope.request_id);
    pending.delete(envelope.request_id);
    if (envelope.ok) request.resolve(envelope);
    else request.reject(new Error(envelope.message || "Command rejected."));
  }

  function clearPending(message) {
    for (const [, request] of pending) request.reject(new Error(message));
    pending.clear();
  }

  function sendJson(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      throw new Error("The room connection is not ready.");
    }
    socket.send(JSON.stringify(payload));
  }

  function open() {
    clearReconnectTimer();
    manualClose = false;
    status({
      connected: false,
      status: reconnectAttempt > 0 ? "reconnecting" : "connecting",
      message: reconnectAttempt > 0 ? "Reconnecting to the room…" : "Connecting to the room…",
    });
    let next;
    try {
      next = new WebSocket(websocketUrl());
    } catch {
      scheduleReconnect();
      return;
    }
    socket = next;
    next.onopen = () => {
      if (socket !== next) return;
      reconnectAttempt = 0;
      status({ connected: true, status: "connected", message: "Connected." });
    };
    next.onclose = event => {
      if (socket !== next) return;
      socket = null;
      clearPending("The room connection closed.");
      if (manualClose) return;
      const message = event.code === 4403
        ? "World entry is blocked until your sticker is confirmed."
        : event.code === 4401
          ? "Sign in again before reconnecting."
          : "Connection lost.";
      if (event.code === 4401 || event.code === 4403) {
        status({ connected: false, status: "closed", message });
        return;
      }
      scheduleReconnect();
    };
    next.onerror = () => {
      if (socket !== next) return;
      status({ connected: false, status: "error", message: "The room connection encountered an error." });
    };
    next.onmessage = event => {
      const envelope = JSON.parse(String(event.data || "{}"));
      if (envelope.type === "room.snapshot") {
        onSnapshot?.(envelope);
        return;
      }
      if (envelope.type === "room.event") {
        onRoomEvent?.(envelope);
        return;
      }
      if (envelope.type === "rtc.signal") {
        onRtcSignal?.(envelope);
        return;
      }
      if (envelope.type === "profile.resync") {
        onProfileResync?.(envelope);
        return;
      }
      if (envelope.type === "session.replaced") {
        clearPending(envelope.message || "This session was replaced elsewhere.");
        onSessionReplaced?.(envelope);
        manualDisconnect();
        return;
      }
      if (envelope.type === "error") {
        onErrorEnvelope?.(envelope);
        return;
      }
      if (envelope.type === "result") {
        onResult?.(envelope);
        settlePending(envelope);
      }
    };
  }

  function manualDisconnect() {
    manualClose = true;
    clearReconnectTimer();
    reconnectAttempt = 0;
    if (socket) {
      const current = socket;
      socket = null;
      current.onopen = null;
      current.onclose = null;
      current.onerror = null;
      current.onmessage = null;
      current.close();
    }
    clearPending("The room connection was replaced.");
    status({ connected: false, status: "idle", message: "" });
  }

  return {
    connect() {
      manualDisconnect();
      open();
    },
    disconnect() {
      manualDisconnect();
    },
    requestSnapshot(revisions) {
      try {
        const envelope = { v: 1, type: "snapshot.request" };
        const layout = Number(revisions?.layoutRevision);
        const environment = Number(revisions?.environmentRevision);
        if (Number.isFinite(layout) && layout >= 0) envelope.layout_revision = layout;
        if (Number.isFinite(environment) && environment >= 0) envelope.environment_revision = environment;
        sendJson(envelope);
      } catch {
        // Ignore refresh attempts while disconnected.
      }
    },
    sendRtcPresence(enabled) {
      return sendJson({ v: 1, type: "rtc.presence", enabled: Boolean(enabled) });
    },
    sendRtcSignal(to, signal) {
      return sendJson({ v: 1, type: "rtc.signal", to, signal });
    },
    sendCommand(command) {
      const id = requestId();
      return new Promise((resolve, reject) => {
        pending.set(id, { resolve, reject });
        try {
          sendJson({ v: 1, type: "command", request_id: id, command });
        } catch (error) {
          pending.delete(id);
          reject(error);
        }
      });
    },
  };
}
