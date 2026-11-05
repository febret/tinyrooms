import { createDropCatch } from "./drop-catch.js";
import { createHoldMeter } from "./hold-meter.js";
import { createPopWhack } from "./pop-whack.js";
import { createRhythmLane } from "./rhythm-lane.js";
import { createRingMatch } from "./ring-match.js";
import { createSweepStop } from "./sweep-stop.js";

export const GAMES = {
  "drop-catch": {
    create: createDropCatch,
    hint: "Tap when a falling token is inside the marked band.",
  },
  "sweep-stop": {
    create: createSweepStop,
    hint: "Tap to stop the needle inside a marked arc. Three stops.",
  },
  "ring-match": {
    create: createRingMatch,
    hint: "Tap each circle as it grows to fill its marked outline.",
  },
  "rhythm-lane": {
    create: createRhythmLane,
    hint: "Tap as each token reaches the glowing line.",
  },
  "pop-whack": {
    create: createPopWhack,
    hint: "Tap the good ones before they hide. Leave the red-crossed ones alone.",
  },
  "hold-meter": {
    create: createHoldMeter,
    hint: "Press and hold to fill the meter, then let go inside the marked zone.",
  },
};

export function gameHint(id) {
  return GAMES[id]?.hint || "Tap when it feels right.";
}

export function createGame(id, params) {
  const entry = GAMES[id];
  if (!entry) throw new Error(`Unknown minigame '${id}'.`);
  return entry.create(params);
}
