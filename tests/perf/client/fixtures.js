// Synthetic client state used by the performance benchmarks.
//
// The shapes mirror what the server actually sends, so a benchmark that
// regresses here would also regress against real traffic.

const CARD_IDS = ["juicy-drink", "toasty-toast", "seal-plushie", "house-key", "poop", "pooper-scooper"];

export function makeProp(index) {
  return {
    id: `prop-${index}`,
    prop_id: "plant",
    position: [10 + (index % 12) * 5, 12 + Math.floor(index / 12) * 5, 0],
    rotation: [0, 0, 0],
    scale: 0.7 + (index % 5) * 0.1,
    behavior: null,
    model_url: `/assets/world/tutorial/props/plant-${index % 3}.glb`,
    label: `Prop ${index}`,
    description: "Generated prop.",
    animation: "auto",
    quick_actions: index % 4 === 0 ? [{ label: "Look", command: ".look" }] : [],
    effect_sets: { idle: [{ kind: "particle", texture_url: "/assets/fx/spark.png" }] },
    active_effect: "idle",
  };
}

export function makeNpc(index) {
  return {
    id: `npc-${index}`,
    kind: "npc",
    label: `Npc ${index}`,
    label_source: `Npc ${index}`,
    image_url: `/assets/peeps/molly.png`,
    quick_actions: [{ label: "Chat", command: ".talk" }],
  };
}

export function makeOccupant(index) {
  return {
    id: `user-${index}`,
    username: `player${index}`,
    kind: "user",
    sticker_url: `/assets/stickers/s${(index % 9) + 1}.png`,
    statuses: [],
    counters: {
      health: 50,
      cleanliness: 50,
      energy: 5,
      counters: { health: 50, cleanliness: 50 },
      statuses: [],
      effects: [],
    },
    audio_enabled: false,
    quick_actions: [{ label: "Wave", command: ".wave" }],
  };
}

export function makeRoomCard(index) {
  return {
    stack_id: `room:card-${index}`,
    card_def_id: CARD_IDS[index % CARD_IDS.length],
    quantity: 1 + (index % 3),
    position: [8 + (index % 8) * 9, 10 + Math.floor(index / 8) * 9, 0],
    definition: {
      id: CARD_IDS[index % CARD_IDS.length],
      label: `Card ${index}`,
      description: "Generated card.",
      image_url: `/assets/world/tutorial/cards/${CARD_IDS[index % CARD_IDS.length]}.webp`,
    },
  };
}

export function makeChatEntry(index) {
  return {
    speaker_id: `user-${index % 8}`,
    speaker: `player${index % 8}`,
    style: "normal",
    text: `message number ${index}`,
  };
}

export function makeInventoryStack(index) {
  return {
    stack_id: `inv-${index}`,
    card_def_id: CARD_IDS[index % CARD_IDS.length],
    quantity: 1,
    equipped: index % 5 === 0,
    scope: "world",
    definition: {
      id: CARD_IDS[index % CARD_IDS.length],
      label: `Card ${index}`,
      description: "Generated card.",
      image_url: `/assets/world/tutorial/cards/${CARD_IDS[index % CARD_IDS.length]}.webp`,
    },
  };
}

export const DEFAULTS = {
  props: 120,
  npcs: 12,
  occupants: 20,
  roomCards: 20,
  chat: 50,
  inventory: 12,
};

export function makeRoomPayload(overrides = {}) {
  const scale = { ...DEFAULTS, ...overrides };
  const props = Array.from({ length: scale.props }, (_, index) => makeProp(index));
  const npcs = Array.from({ length: scale.npcs }, (_, index) => makeNpc(index));
  const occupants = Array.from({ length: scale.occupants }, (_, index) => makeOccupant(index));
  const roomCards = Array.from({ length: scale.roomCards }, (_, index) => makeRoomCard(index));
  const chatHistory = Array.from({ length: scale.chat }, (_, index) => makeChatEntry(index));
  const inventory = Array.from({ length: scale.inventory }, (_, index) => makeInventoryStack(index));
  return {
    id: "hub",
    label: "The Hub",
    description: "A synthetic room.",
    board: {
      type: "basic",
      image_url: "/assets/world/tutorial/rooms/hub.jpg",
      image_style: "stretch",
      palette: ["#ebcfaa", "#b97262", "#6faea4"],
      dark: false,
    },
    metadata: { note: "" },
    environment: { lighting: "normal", hidden_props: {}, disabled_exits: {}, disabled_actions: {} },
    environment_revision: 1,
    exits: [
      { id: "exit0", label: "Cross the portal", command: ".go @way:exit0" },
      { id: "exit1", label: "Back", command: ".go @way:exit1" },
    ],
    props,
    occupants,
    npcs,
    room_cards: roomCards,
    chat_history: chatHistory,
    inventory,
    editable: false,
    can_edit_room: false,
    layout_revision: 1,
    dialog: null,
    quick_actions: [{ label: "Cross the portal", command: ".go @way:exit0" }],
  };
}

export function makeUserPayload() {
  return {
    id: "user-0",
    username: "player0",
    username_display: "player0",
    level: 3,
    kudos: 40,
    bops: 25,
    energy: 5,
    max_energy: 10,
    health: 50,
    max_health: 50,
    cleanliness: 50,
    max_cleanliness: 50,
    status: "ok",
    statuses: [],
    counters: { health: 50, cleanliness: 50 },
    effects: [],
    initial_sticker: "s1.png",
    initial_sticker_complete: true,
    remembered_room: "hub",
    owned_rooms: [],
    inventory: [],
    skills: [],
    memories: [],
    packs: [],
    powers: [],
  };
}
