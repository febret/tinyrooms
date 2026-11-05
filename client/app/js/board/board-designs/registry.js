// Generic diorama-board design registry.
//
// Core board plumbing only knows `board.type === "diorama"` plus a
// `board.design` slug (e.g. "galaxy-vortex"). Specific looks live
// in enabled mods and register here through their declared `boards` modules.

import { withBase } from "../../base-path.js";

export const DIORAMA_BOARD_TYPE = "diorama";

const designs = new Map();
const loadedModules = new Map();

export function registerBoardDesign(name, factory) {
  const key = String(name || "").trim();
  if (!key) throw new Error("registerBoardDesign requires a non-empty name");
  if (typeof factory !== "function") throw new Error(`board design '${key}' factory must be a function`);
  designs.set(key, factory);
}

/**
 * Import every enabled mod's declared board module once.
 *
 * Modules register themselves as an import side effect. Failures are logged
 * and skipped so one broken mod cannot stop the board from rendering.
 */
export function loadBoardDesigns(entries) {
  const list = Array.isArray(entries) ? entries : [];
  return Promise.all(list.map(entry => {
    const moduleUrl = String(entry?.module_url || "").trim();
    if (!moduleUrl) return null;
    const url = withBase(moduleUrl);
    if (!loadedModules.has(url)) {
      loadedModules.set(url, import(url).catch(error => {
        console.error(`[board-designs] failed to load ${entry?.name || url}`, error);
        return null;
      }));
    }
    return loadedModules.get(url);
  }));
}

export function getBoardDesign(name) {
  return designs.get(String(name || "").trim()) || null;
}

/**
 * Pick the design for a room. An explicit room/world design wins, then a mod
 * may supply one through its diorama environment payload, then the first
 * registered design keeps legacy rooms rendering.
 */
export function resolveBoardDesign(board, environment) {
  const candidates = [
    board?.design,
    environment?.diorama?.design,
  ];
  for (const candidate of candidates) {
    const key = String(candidate || "").trim();
    if (key && designs.has(key)) return key;
  }
  return designs.keys().next().value || "";
}
