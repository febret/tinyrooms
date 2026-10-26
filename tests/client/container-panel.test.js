import test from "node:test";
import assert from "node:assert/strict";

import { containerPanelMarkup, createContainerPanel } from "../../client/app/js/container-panel.js";
import { describeSelection, selectionActions } from "../../client/app/js/cards.js";
import { normalizeContainer } from "../../client/app/js/normalize.js";
import { createStore } from "../../client/app/js/state.js";

const DEFINITION = {
  id: "poop",
  label: "Poop",
  description: "A piece of poop.",
  image_url: "/assets/poop-art.png",
  rarity: "Common",
  tags: [],
};

const PAYLOAD = {
  instance_id: "cabinet",
  room_id: "bathroom",
  label: "Saari Cabinet",
  cards: [
    { stack_id: "c1", quantity: 2, pinned: false, definition: DEFINITION, quick_actions: [] },
    { stack_id: "c2", quantity: 1, pinned: false, definition: { ...DEFINITION, id: "smile", label: "Smile" }, quick_actions: [] },
  ],
};

function panelState(overrides = {}) {
  return {
    room: { id: "bathroom" },
    container: normalizeContainer(PAYLOAD),
    selection: { kind: "prop", id: "cabinet" },
    views: { main: null },
    ui: { containerOpen: true },
    ...overrides,
  };
}

test("container payloads normalize to panel state", () => {
  const container = normalizeContainer(PAYLOAD);
  assert.equal(container.instanceId, "cabinet");
  assert.equal(container.label, "Saari Cabinet");
  assert.deepEqual(container.cards.map(card => [card.stackId, card.quantity]), [["c1", 2], ["c2", 1]]);
  assert.equal(container.cards[0].definition.label, "Poop");
  assert.equal(normalizeContainer(null), null);
  assert.equal(normalizeContainer({}).label, "Container");
});

test("open-container stores contents and opens the panel", () => {
  const store = createStore();
  assert.equal(store.getState().container, null);
  assert.equal(store.getState().ui.containerOpen, false);
  store.dispatch({ type: "open-container", container: PAYLOAD });
  const state = store.getState();
  assert.equal(state.container.label, "Saari Cabinet");
  assert.equal(state.container.cards.length, 2);
  assert.equal(state.ui.containerOpen, true);
  store.dispatch({ type: "close-container" });
  assert.equal(store.getState().ui.containerOpen, false);
  assert.equal(store.getState().container, null);
});

test("closing the container clears a container-card selection", () => {
  const store = createStore();
  store.dispatch({
    type: "snapshot",
    room: { id: "bathroom", occupants: [], npcs: [], inventory: [], roomCards: [], props: [] },
  });
  store.dispatch({ type: "open-container", container: PAYLOAD });
  store.dispatch({ type: "select", selection: { kind: "container-card", id: "c1" } });
  store.dispatch({ type: "close-container" });
  assert.equal(store.getState().container, null);
  assert.equal(store.getState().selection.kind, "room");
});

test("command results store container contents without opening", () => {
  const store = createStore();
  store.dispatch({ type: "result", ok: true, message: "", payload: { container: PAYLOAD }, events: [] });
  const state = store.getState();
  assert.equal(state.container.instanceId, "cabinet");
  assert.equal(state.ui.containerOpen, false);
});

test("panel markup shows compact illustration tiles with labels", () => {
  const html = containerPanelMarkup(panelState());
  assert.match(html, /Saari Cabinet/);
  assert.match(html, /data-container-close/);
  assert.match(html, /data-stack-id="c1"/);
  assert.match(html, /data-stack-id="c2"/);
  assert.match(html, /card-illustration/);
  assert.match(html, /Poop.*×2/);
  assert.doesNotMatch(html, /<svg/);
});

test("panel markup marks the selected card and handles empties", () => {
  const selected = containerPanelMarkup(panelState({ selection: { kind: "container-card", id: "c2" } }));
  assert.match(selected, /data-stack-id="c2"[^>]*aria-pressed="true"|aria-pressed="true"[^>]*data-stack-id="c2"/);
  const empty = containerPanelMarkup(panelState({ container: normalizeContainer({ ...PAYLOAD, cards: [] }) }));
  assert.match(empty, /Empty\./);
});

test("selecting a container card offers Take actions", () => {
  const state = panelState({ selection: { kind: "container-card", id: "c1" } });
  const actions = selectionActions(state);
  assert.deepEqual(actions.map(action => action.label), ["Take 1", "Take all"]);
  assert.equal(actions[0].command, ".take @prop:cabinet @card:c1 1");
  assert.equal(actions[1].command, ".take @prop:cabinet @card:c1 2");
  const single = selectionActions(panelState({ selection: { kind: "container-card", id: "c2" } }));
  assert.deepEqual(single.map(action => action.label), ["Take 1"]);
  const missing = selectionActions(panelState({ selection: { kind: "container-card", id: "gone" } }));
  assert.deepEqual(missing, []);
});

test("container cards describe like other cards", () => {
  const description = describeSelection(panelState({ selection: { kind: "container-card", id: "c1" } }));
  assert.equal(description.title, "Poop");
  assert.equal(description.imageUrl, "/assets/poop-art.png");
});

function fakeRoot() {
  const listeners = {};
  const attrs = {};
  const root = {
    ownerDocument: { activeElement: null, addEventListener() {}, querySelector: () => null },
    hidden: true,
    focused: false,
    style: {},
    offsetWidth: 420,
    offsetHeight: 240,
    offsetParent: null,
    listeners,
    classList: { add() {} },
    setAttribute: (key, value) => { attrs[key] = value; },
    getAttribute: key => (key in attrs ? attrs[key] : null),
    hasAttribute: key => key in attrs,
    toggleAttribute: (key, force) => { if (force) attrs[key] = ""; else delete attrs[key]; },
    replaceChildren() { root.innerHTML = ""; },
    querySelector: () => null,
    querySelectorAll: () => [],
    contains: () => true,
    addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
    fire: (type, event) => { (listeners[type] || []).forEach(fn => fn(event)); },
    focus() { root.focused = true; },
    innerHTML: "",
  };
  return root;
}

function panelHarness({ projectPosition } = {}) {
  const holder = { state: panelState({ ui: { containerOpen: false } }) };
  const selected = [];
  const dispatched = [];
  const root = fakeRoot();
  const panel = createContainerPanel({
    root,
    store: { getState: () => holder.state, dispatch: action => { dispatched.push(action); } },
    onSelect: selection => { selected.push(selection); },
    projectPosition,
  });
  return { holder, selected, dispatched, root, panel };
}

test("panel sync toggles hidden and inert like the room picker", () => {
  const harness = panelHarness();
  harness.panel.sync(harness.holder.state);
  assert.equal(harness.root.hidden, true);
  assert.ok(harness.root.hasAttribute("inert"));
  harness.holder.state = panelState();
  harness.panel.sync(harness.holder.state);
  assert.equal(harness.root.hidden, false);
  assert.ok(!harness.root.hasAttribute("inert"));
  assert.match(harness.root.innerHTML, /Saari Cabinet/);
  assert.equal(harness.root.focused, true);
});

test("panel close button and Escape dispatch close-container", () => {
  const harness = panelHarness();
  harness.holder.state = panelState();
  harness.panel.sync(harness.holder.state);
  harness.root.fire("click", { target: { closest: selector => selector === "[data-container-close]" ? {} : null } });
  assert.deepEqual(harness.dispatched.at(-1), { type: "close-container" });
  let prevented = false;
  assert.equal(harness.panel.handleEscape({ key: "Escape", preventDefault: () => { prevented = true; } }), true);
  assert.ok(prevented);
  assert.deepEqual(harness.dispatched.at(-1), { type: "close-container" });
  assert.equal(harness.panel.handleEscape({ key: "Enter", preventDefault: () => {} }), false);
});

test("panel card clicks select container cards without closing", () => {
  const harness = panelHarness();
  harness.holder.state = panelState();
  harness.panel.sync(harness.holder.state);
  harness.root.fire("click", {
    target: { closest: selector => selector === "[data-stack-id]" ? { dataset: { stackId: "c1" } } : null },
  });
  assert.deepEqual(harness.selected, [{ kind: "container-card", id: "c1" }]);
  assert.ok(!harness.dispatched.some(action => action.type === "close-container"));
});

function fakeImage(naturalWidth = 100) {
  const classes = new Set();
  const parentClasses = new Set();
  return {
    tagName: "IMG",
    naturalWidth,
    classList: {
      toggle: (name, force) => { if (force) classes.add(name); else classes.delete(name); },
      remove: name => { classes.delete(name); },
    },
    parentElement: {
      classList: {
        toggle: (name, force) => { if (force) parentClasses.add(name); else parentClasses.delete(name); },
        remove: name => { parentClasses.delete(name); },
      },
    },
    classes,
    parentClasses,
  };
}

test("loaded card art becomes visible like room-picker tiles", () => {
  const harness = panelHarness();
  const image = fakeImage(120);
  harness.root.listeners.load.forEach(fn => fn({ target: image }));
  assert.ok(image.classes.has("room-picker-image-ready"));
  assert.ok(image.parentClasses.has("room-picker-has-image"));
  const broken = fakeImage(0);
  harness.root.listeners.load.forEach(fn => fn({ target: broken }));
  assert.ok(!broken.classes.has("room-picker-image-ready"));
  harness.root.listeners.error.forEach(fn => fn({ target: broken }));
  assert.ok(!broken.parentClasses.has("room-picker-has-image"));
});

test("panel opens next to its container prop", () => {
  const seen = [];
  const harness = panelHarness({ projectPosition: position => { seen.push(position); return { x: 500, y: 300 }; } });
  harness.root.offsetParent = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }) };
  harness.holder.state = panelState({
    room: { id: "bathroom", props: [{ id: "cabinet", position: [10, 20, 0] }] },
  });
  harness.panel.sync(harness.holder.state);
  assert.deepEqual(seen, [[10, 20, 0]]);
  assert.match(harness.root.style.left, /^\d+px$/);
  assert.match(harness.root.style.top, /^\d+px$/);
});

test("panel falls back to its default spot without a projectable prop", () => {
  const harness = panelHarness({ projectPosition: () => null });
  harness.root.offsetParent = { getBoundingClientRect: () => ({ left: 0, top: 0, width: 1200, height: 800 }) };
  harness.root.style.left = "10px";
  harness.holder.state = panelState();
  harness.panel.sync(harness.holder.state);
  assert.equal(harness.root.style.left, "");
  assert.equal(harness.root.style.top, "");
});
