/**
 * Animate buttons appearing in or leaving a toolbar.
 *
 * Toolbar views commonly replace their innerHTML on state changes, so callers
 * capture the current buttons first and replay the difference afterwards.
 * Removed buttons are cloned into a fixed-position ghost so their exit
 * animation can finish after the source node has been replaced.
 */

/** Return a stable key for one direct toolbar button. */
export function toolbarButtonKey(element, index = -1) {
  const dataset = element?.dataset || {};
  if (dataset.topAction) return `action:${dataset.topAction}`;
  if (dataset.coreId) return `core:${dataset.coreId}`;
  if (element?.id) return `id:${element.id}`;
  if (dataset.editProp) return `edit-prop:${dataset.editProp}`;
  if (dataset.editRoom !== undefined) return "edit-room";
  if (dataset.openMultiverse !== undefined) return "multiverse";
  if (dataset.openCutsceneCatalog !== undefined) return "cutscene-catalog";
  const classes = String(element?.className || "").split(/\s+/).filter(Boolean).sort().join(" ");
  return `button:${classes}:${index >= 0 ? index : ""}`;
}

/** Render updated markup with toolbar enter/leave animation. */
export function updateWithToolbarAnimation(root, markup) {
  const previous = captureToolbarButtons(root);
  root.innerHTML = markup;
  return animateToolbarButtons(root, previous);
}

function toolbarButtons(root) {
  if (!root?.children) return [];
  return [...root.children].filter(element => element?.tagName === "BUTTON");
}

/** Snapshot the current buttons and their on-screen boxes before a re-render. */
export function captureToolbarButtons(root) {
  const captured = new Map();
  toolbarButtons(root).forEach((element, index) => {
    captured.set(toolbarButtonKey(element, index), {
      element,
      rect: element.getBoundingClientRect?.() || null,
    });
  });
  return captured;
}

function scheduleAfter(documentRef, callback, delay) {
  const timer = documentRef?.defaultView?.setTimeout || setTimeout;
  timer(callback, delay);
}

function markAdded(element, documentRef) {
  element.classList?.add("toolbar-button-entering");
  const clear = () => element.classList?.remove("toolbar-button-entering");
  element.addEventListener?.("animationend", clear, { once: true });
  scheduleAfter(documentRef, clear, 1400);
}

function ghostRemoved(element, rect, documentRef) {
  const owner = element.ownerDocument || documentRef;
  const body = owner?.body;
  if (!body || !rect || rect.width <= 0 || !element.cloneNode) return;
  const ghost = element.cloneNode(true);
  ghost.removeAttribute?.("id");
  ghost.querySelectorAll?.("[id]").forEach(node => node.removeAttribute("id"));
  ghost.classList?.add("toolbar-button-leaving");
  ghost.setAttribute?.("aria-hidden", "true");
  ghost.setAttribute?.("inert", "");
  const style = ghost.style;
  if (style) {
    style.position = "fixed";
    style.left = `${rect.left}px`;
    style.top = `${rect.top}px`;
    style.width = `${rect.width}px`;
    style.height = `${rect.height}px`;
    style.margin = "0";
    style.pointerEvents = "none";
    style.zIndex = "95";
  }
  body.append(ghost);
  const remove = () => ghost.remove();
  ghost.addEventListener?.("animationend", remove, { once: true });
  scheduleAfter(owner, remove, 800);
}

/**
 * Animate the difference between a captured toolbar and its current children.
 * Added buttons get an entrance class; removed buttons get a ghost exit.
 */
export function animateToolbarButtons(root, previous) {
  const current = new Map(
    toolbarButtons(root).map((element, index) => [toolbarButtonKey(element, index), element])
  );
  const added = [];
  const removed = [];
  if (previous) {
    const documentRef = root?.ownerDocument;
    for (const [key, item] of previous) {
      if (current.has(key)) continue;
      removed.push(key);
      ghostRemoved(item.element, item.rect, documentRef);
    }
    for (const [key, element] of current) {
      if (previous.has(key)) continue;
      added.push(element);
      markAdded(element, documentRef);
    }
  }
  return { added, removed };
}
