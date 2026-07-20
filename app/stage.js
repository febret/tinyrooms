// ─── Stage math helpers ──────────────────────────────────────────────────────

function getStageTotalHeight(stage, cameraFloorHeight) {
  return stage.type === 'standard'
    ? (stage.bg_height + cameraFloorHeight)
    : stage.height;
}

// Depth-sort z-index for an entity on the standard stage floor.
function computeStandardZOrder(y, bgH, floorH) {
  return Math.round(Math.max(0, y - bgH) / Math.max(1, floorH) * 1000);
}

// ─── Background / floor element builders ─────────────────────────────────────

// Create a background <div> with the room background image applied.
// Returns null when backgroundPath is empty and alwaysCreate is false.
function createBackgroundDiv(backgroundPath, stage, height, alwaysCreate) {
  if (!backgroundPath && !alwaysCreate) return null;
  const bgDiv = document.createElement("div");
  bgDiv.className = "room-background";
  bgDiv.style.width = "100%";
  bgDiv.style.height = height;
  if (backgroundPath) {
    bgDiv.style.backgroundImage = `url("${resolveBackgroundUrl(backgroundPath)}")`;
    bgDiv.classList.add(stage.background_mode === 'stretch'
      ? "room-background-stretch"
      : "room-background-tile");
  }
  return bgDiv;
}

// ─── Sprite animation ─────────────────────────────────────────────────────────

function _stopSpriteAnimation(key) {
  const state = spriteAnimationState.get(key);
  if (state && state.timer) {
    clearInterval(state.timer);
  }
  spriteAnimationState.delete(key);
}

function _applyFrameToNode(frameNode, frame) {
  if (!frameNode || !frame) return;
  frameNode.style.width = `${frame.width || 32}px`;
  frameNode.style.height = `${frame.height || 32}px`;
  frameNode.style.backgroundPosition = `-${frame.x || 0}px -${frame.y || 0}px`;
}

function _renderEntityDisplay(node, entity, domKey) {
  const display = entity.display || {};
  const spriteMeta = display.sprite_meta || display.img_meta || null;
  const imageUrl = resolveAssetUrl(display.sprite || display.img || "");

  if (!spriteMeta || !spriteMeta.frame) {
    _stopSpriteAnimation(domKey);
    let img = node.querySelector("img");
    if (!img) {
      img = document.createElement("img");
      node.innerHTML = "";
      node.appendChild(img);
    }
    img.src = imageUrl;
    img.alt = entity.label || "";
    return;
  }

  let spriteNode = node.querySelector(".room-entity-sprite");
  if (!spriteNode) {
    spriteNode = document.createElement("div");
    spriteNode.className = "room-entity-sprite";
    node.innerHTML = "";
    node.appendChild(spriteNode);
  }
  spriteNode.style.backgroundImage = `url("${imageUrl}")`;
  spriteNode.style.backgroundRepeat = "no-repeat";
  _applyFrameToNode(spriteNode, spriteMeta.frame);

  const anim = spriteMeta.animation;
  if (!anim || !Array.isArray(anim.frames) || anim.frames.length <= 1) {
    _stopSpriteAnimation(domKey);
    return;
  }

  _stopSpriteAnimation(domKey);
  let index = 0;
  let direction = 1;
  const intervalMs = Math.max(40, Number(anim.speed || 0.5) * 1000);
  const timer = setInterval(() => {
    const frames = anim.frames;
    if (!frames.length) return;
    if (anim.type === "random") {
      index = Math.floor(Math.random() * frames.length);
    } else if (anim.type === "bounce") {
      index += direction;
      if (index >= frames.length) {
        index = Math.max(0, frames.length - 2);
        direction = -1;
      } else if (index < 0) {
        index = Math.min(frames.length - 1, 1);
        direction = 1;
      }
    } else {
      index = (index + 1) % frames.length;
    }
    _applyFrameToNode(spriteNode, frames[index]);
  }, intervalMs);
  spriteAnimationState.set(domKey, { timer });
}

// ─── Stage rendering ──────────────────────────────────────────────────────────

function renderRoomStage(backgroundPath) {
  spriteAnimationState.forEach((_value, key) => _stopSpriteAnimation(key));
  roomCanvas.innerHTML = "";

  const stage = roomState.stage;
  const isStandard = stage.type === 'standard';

  const stageLayer = document.createElement("div");
  stageLayer.className = "room-layer";

  if (isStandard) {
    stageLayer.classList.add("room-standard-stage");
    stageLayer.appendChild(createBackgroundDiv(backgroundPath, stage, `${stage.bg_height}px`, true));

    const floorDiv = document.createElement("div");
    floorDiv.className = "room-floor";
    floorDiv.style.width = "100%";
    floorDiv.style.height = `${roomState.cameraFloorHeight}px`;
    if (stage.floor_image) {
      floorDiv.style.backgroundImage = `url("${resolveBackgroundUrl(stage.floor_image)}")`;
    }
    stageLayer.appendChild(floorDiv);
  } else {
    const bgDiv = createBackgroundDiv(backgroundPath, stage, "100%", false);
    if (bgDiv) stageLayer.appendChild(bgDiv);
  }

  for (const prop of getEditableProps().values()) {
    stageLayer.appendChild(makePropNode(prop));
  }

  const fgLayer = document.createElement("div");
  fgLayer.className = "room-layer";
  fgLayer.id = "foregroundLayer";
  if (roomEditor.enabled) {
    fgLayer.style.pointerEvents = "none";
  }

  roomCanvas.appendChild(stageLayer);
  roomCanvas.appendChild(fgLayer);
  roomCanvas.ondragover = e => e.preventDefault();
  roomCanvas.ondrop = handleRoomDrop;

  if (!roomEditor.enabled) {
    for (const entity of roomState.entities.values()) {
      renderForegroundEntity(entity);
    }
  }
  renderRoomEditorActivity();
}

// ─── Entity rendering ─────────────────────────────────────────────────────────

function renderForegroundEntity(entity) {
  if (roomEditor.enabled) return;
  const layer = document.getElementById("foregroundLayer");
  if (!layer) return;

  const key = `${entity.entity_type}:${entity.entity_id}`;
  const domId = `room-${key.replace(":", "-")}`;
  let node = document.getElementById(domId);
  if (!node) {
    node = document.createElement("div");
    node.id = domId;
    node.className = "room-entity room-selectable";
    layer.appendChild(node);
  }

  const posY = entity.position?.y || 0;
  let zIndex = entity.position?.z_order || 0;
  if (roomState.stage.type === 'standard') {
    zIndex = computeStandardZOrder(posY, roomState.stage.bg_height, roomState.cameraFloorHeight);
  }

  node.className = "room-entity room-selectable" + (entity.is_self ? " self" : "");
  node.style.left = `${entity.position?.x || 0}px`;
  node.style.top = `${posY}px`;
  node.style.zIndex = `${zIndex}`;
  _renderEntityDisplay(node, entity, domId);

  node.onclick = () => selectTarget({
    type: entity.entity_type,
    id: entity.entity_id,
    label: entity.label || entity.entity_id,
    description: entity.description || "",
  }, node);

  configureDragHandlers(node, entity.entity_type, entity.entity_id, canDragEntity(entity));
}

function canDragEntity(entity) {
  if (roomEditor.enabled) return false;
  if (entity.entity_type === "object") return true;
  if (entity.entity_type === "peep") {
    return entity.owner_username === myUsername || roomState.canEditProps;
  }
  return false;
}

function resetRoomEntityState() {
  spriteAnimationState.forEach((_value, key) => _stopSpriteAnimation(key));
  roomState.entities.clear();
  selectedTarget = null;
  lookBox.textContent = "";
  document.querySelectorAll(".room-selected").forEach(el => el.classList.remove("room-selected"));
  const layer = document.getElementById("foregroundLayer");
  if (layer) layer.innerHTML = "";
}

// ─── Stage coordinate math ────────────────────────────────────────────────────

function getStagePoint(clientX, clientY, requireInside) {
  const rect = roomCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;

  const isInside = clientX >= rect.left && clientX <= rect.right
    && clientY >= rect.top && clientY <= rect.bottom;
  if (requireInside && !isInside) return null;

  const stage = roomState.stage;
  const totalHeight = getStageTotalHeight(stage, roomState.cameraFloorHeight);
  const x = Math.round((clientX - rect.left) * (stage.width / rect.width));
  const y = Math.round((clientY - rect.top) * (totalHeight / rect.height));
  const clampedX = Math.min(stage.width, Math.max(0, x));

  let clampedY;
  if (stage.type === 'standard') {
    const floorTop = stage.bg_height;
    const floorBottom = stage.bg_height + roomState.cameraFloorHeight;
    clampedY = Math.min(floorBottom, Math.max(floorTop, y));
  } else {
    clampedY = Math.min(totalHeight, Math.max(0, y));
  }
  return { x: clampedX, y: clampedY };
}

function submitMovePayload(payload, clientX, clientY, requireInside) {
  const point = getStagePoint(clientX, clientY, requireInside);
  if (!point) return;

  if (payload.entityType === "prop") {
    if (roomEditor.enabled) {
      const draft = roomEditor.draftProps.get(payload.entityId);
      if (!draft) return;
      draft.position = draft.position || {};
      draft.position.x = point.x;
      draft.position.y = point.y;
      draft.position.z_order = nextDraftZOrder();
      roomEditor.draftProps.set(payload.entityId, draft);
      renderRoomStage(roomState.backgroundPath);
      return;
    }
    socket.emit("room_edit_prop", { prop_instance_id: payload.entityId, x: point.x, y: point.y });
    return;
  }

  const moveEvent = {
    entity_type: payload.entityType,
    entity_id: payload.entityId,
    x: point.x,
    y: point.y,
  };
  if (roomState.stage.type === 'standard') {
    moveEvent.z_order = computeStandardZOrder(
      point.y, roomState.stage.bg_height, roomState.cameraFloorHeight
    );
  }
  socket.emit("room_move_entity", moveEvent);
}

// ─── Camera control ───────────────────────────────────────────────────────────

function setCameraFloorHeight(newFloorHeight) {
  const stage = roomState.stage;
  if (stage.type !== 'standard') return;
  const oldFloorH = roomState.cameraFloorHeight;
  if (oldFloorH === newFloorHeight) return;

  // Proportionally reposition sprites to track the new floor height (client-side only)
  const bgH = stage.bg_height;
  for (const entity of roomState.entities.values()) {
    if (!entity.position) continue;
    const relY = Math.max(0, entity.position.y - bgH);
    const ratio = oldFloorH > 0 ? relY / oldFloorH : 0;
    entity.position.y = bgH + Math.round(ratio * newFloorHeight);
  }
  roomState.cameraFloorHeight = newFloorHeight;
  roomCanvas.style.height = `${bgH + newFloorHeight}px`;
  renderRoomStage(roomState.backgroundPath);
}

// ─── Mouse / desktop drag ─────────────────────────────────────────────────────

function beginDrag(ev, entityType, entityId) {
  if (ev.target instanceof Element && ev.target.closest(".room-prop-controls")) {
    ev.preventDefault();
    return;
  }
  const dragSource = ev.currentTarget instanceof HTMLElement ? ev.currentTarget : ev.target;
  const ghost = dragSource.cloneNode(true);
  ghost.style.opacity = "0.45";
  ghost.style.position = "absolute";
  ghost.style.top = "-1000px";
  document.body.appendChild(ghost);
  ev.dataTransfer.setDragImage(ghost, ghost.clientWidth / 2, ghost.clientHeight / 2);
  setTimeout(() => ghost.remove(), 0);
  ev.dataTransfer.setData("text/plain", JSON.stringify({ entityType, entityId }));
}

function handleRoomDrop(ev) {
  ev.preventDefault();
  const raw = ev.dataTransfer.getData("text/plain");
  if (!raw) return;
  const payload = JSON.parse(raw);
  submitMovePayload(payload, ev.clientX, ev.clientY, false);
}

// ─── Touch drag ───────────────────────────────────────────────────────────────

function beginTouchDrag(ev, entityType, entityId) {
  if (ev.pointerType !== "touch") return;
  ev.preventDefault();
  if (activeTouchDrag) cleanupTouchDrag();
  const node = ev.currentTarget;
  activeTouchDrag = {
    pointerId: ev.pointerId,
    startX: ev.clientX,
    startY: ev.clientY,
    entityType,
    entityId,
    node,
    moved: false,
    ghost: null,
  };
  if (node.setPointerCapture) node.setPointerCapture(ev.pointerId);
  document.addEventListener("pointermove", handleTouchDragMove, { passive: false });
  document.addEventListener("pointerup", handleTouchDragEnd, { passive: false });
  document.addEventListener("pointercancel", handleTouchDragCancel, { passive: false });
}

function ensureTouchDragGhost() {
  if (!activeTouchDrag || activeTouchDrag.ghost) return;
  const ghost = activeTouchDrag.node.cloneNode(true);
  ghost.style.position = "fixed";
  ghost.style.pointerEvents = "none";
  ghost.style.zIndex = "5000";
  ghost.style.opacity = "0.75";
  ghost.style.transform = "translate(-50%, -50%)";
  document.body.appendChild(ghost);
  activeTouchDrag.ghost = ghost;
}

function handleTouchDragMove(ev) {
  if (!activeTouchDrag || ev.pointerId !== activeTouchDrag.pointerId) return;
  ev.preventDefault();
  const movedDistance = Math.hypot(
    ev.clientX - activeTouchDrag.startX,
    ev.clientY - activeTouchDrag.startY
  );
  if (movedDistance >= TOUCH_DRAG_THRESHOLD_PX) {
    activeTouchDrag.moved = true;
    ensureTouchDragGhost();
  }
  if (activeTouchDrag.ghost) {
    activeTouchDrag.ghost.style.left = `${ev.clientX}px`;
    activeTouchDrag.ghost.style.top = `${ev.clientY}px`;
  }
}

function handleTouchDragEnd(ev) {
  if (!activeTouchDrag || ev.pointerId !== activeTouchDrag.pointerId) return;
  ev.preventDefault();
  const drag = activeTouchDrag;
  cleanupTouchDrag();
  if (drag.moved) {
    submitMovePayload({ entityType: drag.entityType, entityId: drag.entityId }, ev.clientX, ev.clientY, true);
    return;
  }
  drag.node.click();
}

function handleTouchDragCancel(ev) {
  if (!activeTouchDrag || ev.pointerId !== activeTouchDrag.pointerId) return;
  ev.preventDefault();
  cleanupTouchDrag();
}

function cleanupTouchDrag() {
  document.removeEventListener("pointermove", handleTouchDragMove);
  document.removeEventListener("pointerup", handleTouchDragEnd);
  document.removeEventListener("pointercancel", handleTouchDragCancel);
  if (activeTouchDrag?.ghost) activeTouchDrag.ghost.remove();
  activeTouchDrag = null;
}
