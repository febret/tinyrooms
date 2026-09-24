import { PATHS } from "./api.js";

function websocketUrl() {
  const url = new URL(PATHS.websocket, window.location.origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}

function requestId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

/** Connect to /ws, route envelopes, and resolve one promise per command request_id. */
export function createSocketClient({ onStatus, onSnapshot, onRoomEvent, onSessionReplaced, onProfileResync, onErrorEnvelope, onResult }) {
  let socket = null;
  const pending = new Map();

  function status(transport) {
    onStatus?.(transport);
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

  return {
    connect() {
      this.disconnect();
      status({ connected: false, status: "connecting", message: "Connecting to the room…" });
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => {
        status({ connected: true, status: "connected", message: "Connected." });
      };
      socket.onclose = event => {
        clearPending("The room connection closed.");
        const message = event.code === 4403
          ? "World entry is blocked until your sticker is confirmed."
          : event.code === 4401
            ? "Sign in again before reconnecting."
            : "Connection lost.";
        status({ connected: false, status: "closed", message });
      };
      socket.onerror = () => {
        status({ connected: false, status: "error", message: "The room connection encountered an error." });
      };
      socket.onmessage = event => {
        const envelope = JSON.parse(String(event.data || "{}"));
        if (envelope.type === "room.snapshot") {
          onSnapshot?.(envelope);
          return;
        }
        if (envelope.type === "room.event") {
          onRoomEvent?.(envelope);
          return;
        }
        if (envelope.type === "profile.resync") {
          onProfileResync?.(envelope);
          return;
        }
        if (envelope.type === "session.replaced") {
          clearPending(envelope.message || "This session was replaced elsewhere.");
          onSessionReplaced?.(envelope);
          this.disconnect();
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
    },
    disconnect() {
      if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
      }
      clearPending("The room connection was replaced.");
      status({ connected: false, status: "idle", message: "" });
    },
    requestSnapshot() {
      try {
        sendJson({ v: 1, type: "snapshot.request" });
      } catch {
        // Ignore refresh attempts while disconnected.
      }
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
