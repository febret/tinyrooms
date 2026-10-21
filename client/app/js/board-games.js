import * as THREE from "three";
import { createGridRenderer } from "./board-games/grid.js";

const DEFAULT_RENDERERS = {
  grid: createGridRenderer,
};

/**
 * Host a world-authored room game.
 *
 * The host owns renderer selection and lifecycle. Renderers interpret
 * `board.game.config`, `board.game.assets`, `board.game.models`, and the opaque
 * `board.state` payload. Game status and the reset action are surfaced through
 * the room description and room quick actions, not a board overlay.
 */
export function createBoardGames({
  loader,
  textureLoader,
  screenToBoardPosition,
  pixelScale,
  invalidate,
  renderers = DEFAULT_RENDERERS,
}) {
  const root = new THREE.Group();
  root.visible = false;
  let parent = null;
  let game = null;
  let state = null;
  let roomDark = false;
  let reducedMotion = false;
  let renderer = null;
  let rendererName = "";
  let onAction = null;

  const context = {
    root,
    loader,
    textureLoader,
    screenToBoardPosition,
    pixelScale,
    invalidate,
    action(action) {
      onAction?.(action);
    },
    get game() {
      return game;
    },
    get state() {
      return state;
    },
    get roomDark() {
      return roomDark;
    },
    get reducedMotion() {
      return reducedMotion;
    },
  };

  function setActionHandler(handler) {
    onAction = handler;
  }

  function ensureRenderer(name) {
    if (renderer && rendererName === name) return renderer;
    renderer?.dispose?.();
    renderer = null;
    rendererName = "";
    const factory = renderers[name];
    if (!factory) return null;
    renderer = factory(context);
    rendererName = name;
    return renderer;
  }

  function active() {
    return Boolean(game && !roomDark);
  }

  function sync(nextParent, room, { dark = false, reducedMotion: reduced = false } = {}) {
    parent = nextParent;
    if (parent && root.parent !== parent) parent.add(root);
    roomDark = Boolean(dark);
    reducedMotion = Boolean(reduced);
    game = room.board?.game || null;
    state = room.board?.state || null;
    root.visible = active();
    if (!active()) {
      renderer?.clear?.();
      invalidate();
      return;
    }
    const nextRenderer = ensureRenderer(game.renderer);
    if (!nextRenderer) {
      root.visible = false;
      renderer?.clear?.();
      invalidate();
      return;
    }
    nextRenderer.sync({ game, state, room, dark: roomDark, reducedMotion });
    invalidate();
  }

  function pointerUp(clientX, clientY) {
    if (!root.visible || !renderer) return false;
    return Boolean(renderer.pointerUp?.(clientX, clientY));
  }

  function advance(delta) {
    if (root.visible) renderer?.advance?.(delta);
  }

  function isAnimating() {
    return root.visible && Boolean(renderer?.isAnimating?.());
  }

  function pieceCount() {
    return renderer?.itemCount?.() || 0;
  }

  function clear() {
    renderer?.clear?.();
    game = null;
    state = null;
    roomDark = false;
    root.visible = false;
    invalidate();
  }

  function dispose() {
    renderer?.dispose?.();
    renderer = null;
    rendererName = "";
    clear();
    root.removeFromParent();
  }

  return {
    group: root,
    setActionHandler,
    sync,
    pointerUp,
    advance,
    isAnimating,
    pieceCount,
    clear,
    dispose,
  };
}
