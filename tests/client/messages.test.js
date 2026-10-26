import test from "node:test";
import assert from "node:assert/strict";

import { buildPhoneMessagesCommand } from "../../client/app/js/commands.js";
import { createStore } from "../../client/app/js/state.js";
import { phoneView } from "../../client/app/js/views/phone-view.js";
import { messagesAppMarkup } from "../../client/app/js/views/messages-view.js";

function baseState(overrides = {}) {
  return {
    user: {
      id: "self",
      username: "Ada",
      friends: { friends: [], incoming: [], outgoing: [] },
      starredTracks: [],
      phoneUnread: 0,
    },
    room: { inventory: [] },
    views: { main: "phone" },
    selection: { kind: "core", id: "phone" },
    ui: {
      phoneApp: "messages",
      phoneFriendIndex: 0,
      phoneMessages: {
        threads: [],
        unread: 0,
        threadKey: null,
        messages: [],
        peers: [],
        picking: false,
      },
      phoneMusic: { mode: "suggestions", path: "", query: "", items: [], top: [], community: [], queue: [], queueIndex: 0, loading: false, error: "", loaded: false },
    },
    ...overrides,
  };
}

test("phone message commands quote the body", () => {
  assert.equal(buildPhoneMessagesCommand("list"), ".phone_msg list");
  assert.equal(buildPhoneMessagesCommand("peers"), ".phone_msg peers");
  assert.equal(buildPhoneMessagesCommand("open", "player:abc"), ".phone_msg open player:abc");
  assert.equal(
    buildPhoneMessagesCommand("send", "player:abc", "hey there friend"),
    '.phone_msg send player:abc "hey there friend"',
  );
});

test("messages home shows three apps with an unread meta", () => {
  const state = baseState({
    user: { id: "self", friends: { friends: [], incoming: [], outgoing: [] }, starredTracks: [], phoneUnread: 2 },
    ui: { phoneApp: "apps", phoneMessages: { threads: [], unread: 2, threadKey: null, messages: [], peers: [], picking: false } },
  });
  const markup = phoneView(state);
  assert.match(markup, /data-phone-app="messages"/);
  assert.match(markup, /2 new/);
  assert.match(markup, /phone-icon-messages\.png/);
  assert.match(markup, /data-phone-key="messages"/);
  assert.doesNotMatch(markup, /Messages are not available yet/);
});

test("empty inbox invites a new text", () => {
  const markup = messagesAppMarkup(baseState());
  assert.match(markup, /No texts yet/);
  assert.match(markup, /data-phone-messages-action="new"/);
});

test("thread list marks unread threads", () => {
  const state = baseState({
    ui: {
      phoneApp: "messages",
      phoneMessages: {
        threads: [
          { threadKey: "player:abc", kind: "player", peerName: "Pip", preview: "hey!", lastAt: "2026-10-25T10:05:00+00:00", unread: 2 },
          { threadKey: "npc:tinytown:ttnpc:one", kind: "npc", peerName: "Wren", preview: "hi", lastAt: "2026-10-25T09:00:00+00:00", unread: 0 },
        ],
        unread: 2,
        threadKey: null,
        messages: [],
        peers: [],
        picking: false,
      },
    },
  });
  const markup = messagesAppMarkup(state);
  assert.match(markup, /Pip/);
  assert.match(markup, /Wren/);
  assert.match(markup, /phone-thread-dot/);
  const escapeRegExp = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pipTime = new Date("2026-10-25T10:05:00+00:00").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const wrenTime = new Date("2026-10-25T09:00:00+00:00").toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  assert.match(markup, new RegExp(`F · ${escapeRegExp(pipTime)} · 2`));
  assert.match(markup, new RegExp(`R · ${escapeRegExp(wrenTime)}`));
  assert.doesNotMatch(markup, /NEW/);
});

test("open thread renders bubbles and escapes bodies", () => {
  const state = baseState({
    ui: {
      phoneApp: "messages",
      phoneMessages: {
        threads: [{ threadKey: "player:abc", kind: "player", peerName: "Pip", preview: "hi", lastAt: "", unread: 0 }],
        unread: 0,
        threadKey: "player:abc",
        messages: [
          { messageId: "m1", direction: "in", senderName: "Pip", body: "<b>hi</b>", createdAt: "2026-10-25T10:05:00+00:00", read: true },
          { messageId: "m2", direction: "out", senderName: "Ada", body: "hello back", createdAt: "2026-10-25T10:06:00+00:00", read: true },
        ],
        peers: [],
        picking: false,
      },
    },
  });
  const markup = messagesAppMarkup(state);
  assert.match(markup, /phone-bubble in/);
  assert.match(markup, /phone-bubble out/);
  assert.match(markup, /&lt;b&gt;hi&lt;\/b&gt;/);
  assert.match(markup, /data-phone-messages-compose="player:abc"/);
  assert.match(markup, /data-phone-messages-action="back"/);
});

test("system threads are read-only", () => {
  const state = baseState({
    ui: {
      phoneApp: "messages",
      phoneMessages: {
        threads: [{ threadKey: "system:events", kind: "system", peerName: "Town Crier", preview: "fest", lastAt: "", unread: 0 }],
        unread: 0,
        threadKey: "system:events",
        messages: [{ messageId: "m1", direction: "in", senderName: "Town Crier", body: "fest", createdAt: "", read: true }],
        peers: [],
        picking: false,
      },
    },
  });
  const markup = messagesAppMarkup(state);
  assert.match(markup, /read-only/);
  assert.doesNotMatch(markup, /data-phone-messages-compose/);
});

test("phone result payload merges the inbox without touching friends", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", username: "Ada", inventory: [] } });
  store.dispatch({
    type: "result",
    ok: true,
    payload: {
      phone_messages: {
        threads: [{ thread_key: "player:abc", kind: "player", peer_name: "Pip", preview: "hey", last_at: "2026-10-25T10:05:00+00:00", unread: 1 }],
        unread: 1,
      },
    },
  });
  const inbox = store.getState().ui.phoneMessages;
  assert.equal(inbox.threads.length, 1);
  assert.equal(inbox.threads[0].peerName, "Pip");
  assert.equal(store.getState().user.phoneUnread, 1);
});

test("live phone events update the inbox and toast when hidden", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", username: "Ada", inventory: [] } });
  store.dispatch({
    type: "snapshot",
    room: { id: "hub", occupants: [], npcs: [], inventory: [], roomCards: [], props: [] },
  });
  const before = store.getState().ui.toasts.length;
  store.dispatch({
    type: "room-event",
    event: { type: "phone.message", thread_key: "player:abc", sender_name: "Pip", preview: "hey", body: "hey there", unread: 1 },
  });
  const state = store.getState();
  assert.equal(state.ui.phoneMessages.threads.length, 1);
  assert.equal(state.user.phoneUnread, 1);
  assert.equal(state.ui.toasts.length, before + 1);
});

test("live phone events append to the open thread without a toast", () => {
  const store = createStore();
  store.dispatch({ type: "bootstrap", user: { id: "self", username: "Ada", inventory: [] } });
  store.dispatch({
    type: "snapshot",
    room: { id: "hub", occupants: [], npcs: [], inventory: [], roomCards: [], props: [] },
  });
  store.dispatch({ type: "phone-app", app: "messages" });
  store.dispatch({ type: "phone-messages-select", threadKey: "player:abc" });
  const before = store.getState().ui.toasts.length;
  store.dispatch({
    type: "room-event",
    event: { type: "phone.message", thread_key: "player:abc", sender_name: "Pip", preview: "hey", body: "hey there", unread: 1 },
  });
  const state = store.getState();
  assert.equal(state.ui.phoneMessages.threads[0].unread, 0);
  assert.equal(state.ui.phoneMessages.messages.length, 1);
  assert.equal(state.ui.toasts.length, before);
});
