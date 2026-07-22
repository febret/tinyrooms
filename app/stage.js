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

// ─── PixiJS globals ───────────────────────────────────────────────────────────

var pixiApp = null;
var pixiBgContainer = null;
var pixiPropsContainer = null;
var pixiEntitiesContainer = null;
var pixiTextureCache = new Map();
// Per-entity: key → { wrapper, sprite, animTicker, moveTicker, moveTween, displayJson, isSelf }
var pixiEntityNodes = new Map();
// Per-prop: propInstanceId → { sprite (wrapper Container), animTicker }
var pixiPropNodes = new Map();
// DOM overlay for editor prop controls (positioned above the PixiJS canvas)
var pixiEditorOverlay = null;

async function initPixiApp() {
  if (pixiApp) return;
  pixiApp = new PIXI.Application();
  await pixiApp.init({
    width: roomState.stage.width,
    height: getStageTotalHeight(roomState.stage, roomState.cameraFloorHeight),
    backgroundAlpha: 0,
    antialias: false,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
    autoStart: true,
    preference: "webgl",
  });
  roomCanvas.appendChild(pixiApp.canvas);

  pixiEditorOverlay = document.createElement("div");
  pixiEditorOverlay.id = "pixiEditorOverlay";
  pixiEditorOverlay.style.cssText = "position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:5;";
  roomCanvas.appendChild(pixiEditorOverlay);
  if (roomCanvas.dataset.contextMenuBound !== "1") {
    roomCanvas.dataset.contextMenuBound = "1";
    roomCanvas.addEventListener("contextmenu", (ev) => {
      ev.preventDefault();
    });
  }

  pixiApp.stage.sortableChildren = true;

  pixiBgContainer = new PIXI.Container();
  pixiBgContainer.zIndex = 0;
  pixiApp.stage.addChild(pixiBgContainer);

  pixiPropsContainer = new PIXI.Container();
  pixiPropsContainer.zIndex = 1;
  pixiPropsContainer.sortableChildren = true;
  pixiApp.stage.addChild(pixiPropsContainer);

  pixiEntitiesContainer = new PIXI.Container();
  pixiEntitiesContainer.zIndex = 2;
  pixiEntitiesContainer.sortableChildren = true;
  pixiApp.stage.addChild(pixiEntitiesContainer);

  pixiAttachStageClickToMove();
}

// ─── Texture utilities ────────────────────────────────────────────────────────

async function loadPixiTexture(url) {
  if (!url) return PIXI.Texture.EMPTY;
  if (pixiTextureCache.has(url)) return pixiTextureCache.get(url);
  try {
    const texture = await PIXI.Assets.load(url);
    pixiTextureCache.set(url, texture);
    return texture;
  } catch (err) {
    console.warn("PixiJS texture load failed:", url, err);
    return PIXI.Texture.EMPTY;
  }
}

function makeFrameTexture(baseTexture, frame) {
  return new PIXI.Texture({
    source: baseTexture.source,
    frame: new PIXI.Rectangle(
      frame.x || 0,
      frame.y || 0,
      frame.width || 32,
      frame.height || 32,
    ),
  });
}

// ─── Background rendering ─────────────────────────────────────────────────────

async function pixiRenderBackground(backgroundPath) {
  pixiBgContainer.removeChildren();

  const stage = roomState.stage;
  const totalH = getStageTotalHeight(stage, roomState.cameraFloorHeight);
  const stageW = stage.width;

  if (backgroundPath) {
    const bgUrl = resolveBackgroundUrl(backgroundPath);
    const bgTex = await loadPixiTexture(bgUrl);
    const bgH = stage.type === 'standard' ? stage.bg_height : totalH;

    if (stage.background_mode === 'stretch' || stage.type !== 'standard') {
      const bg = new PIXI.Sprite(bgTex);
      bg.width = stageW;
      bg.height = bgH;
      bg.x = 0;
      bg.y = 0;
      pixiBgContainer.addChild(bg);
    } else {
      const bg = new PIXI.TilingSprite({ texture: bgTex, width: stageW, height: bgH });
      bg.x = 0;
      bg.y = 0;
      pixiBgContainer.addChild(bg);
    }
  }

  if (stage.type === 'standard') {
    const floorY = stage.bg_height;
    const floorH = roomState.cameraFloorHeight;
    if (stage.floor_image) {
      const floorUrl = resolveBackgroundUrl(stage.floor_image);
      const floorTex = await loadPixiTexture(floorUrl);
      const floor = new PIXI.TilingSprite({ texture: floorTex, width: stageW, height: floorH });
      floor.x = 0;
      floor.y = floorY;
      pixiBgContainer.addChild(floor);
    } else {
      const floor = new PIXI.Graphics();
      floor.rect(0, floorY, stageW, floorH).fill({ color: 0x000000, alpha: 0 });
      pixiBgContainer.addChild(floor);
    }
  }
}

// ─── Orientation helper ───────────────────────────────────────────────────────

function orientationToRadians(orientation) {
  if (orientation === "right") return Math.PI / 2;
  if (orientation === "back")  return Math.PI;
  if (orientation === "left")  return 3 * Math.PI / 2;
  return 0;
}

// Scale a sprite down so it fits within maxW × maxH, preserving aspect ratio.
// Does not scale up sprites that are already smaller than the limit.
function clampSpriteSize(sprite, maxW, maxH) {
  const w = sprite.texture.width;
  const h = sprite.texture.height;
  if (!w || !h) return;
  const scale = Math.min(1, maxW / w, maxH / h);
  sprite.scale.set(scale);
}

const TARGET_LONG_TAP_MS = 550;
const TARGET_LONG_TAP_MOVE_THRESHOLD = 8;

function bindTargetInteractions(wrapper, getTarget) {
  let longTapTimer = null;
  let longTapTriggered = false;
  let startPoint = null;

  function cancelLongTap() {
    if (longTapTimer !== null) {
      clearTimeout(longTapTimer);
      longTapTimer = null;
    }
    startPoint = null;
  }

  function beginLongTap(ev) {
    cancelLongTap();
    longTapTriggered = false;
    if (roomEditor.enabled || ev.pointerType !== "touch") {
      return;
    }
    startPoint = { x: ev.global.x, y: ev.global.y };
    longTapTimer = setTimeout(() => {
      longTapTimer = null;
      longTapTriggered = true;
      const target = getTarget();
      if (target) {
        handleTargetLook(target);
      }
    }, TARGET_LONG_TAP_MS);
  }

  wrapper.on("pointerdown", (ev) => {
    beginLongTap(ev);
  });
  wrapper.on("pointerup", () => {
    cancelLongTap();
  });
  wrapper.on("pointerupoutside", () => {
    cancelLongTap();
  });
  wrapper.on("globalpointermove", (ev) => {
    if (longTapTimer === null || !startPoint) return;
    const dx = ev.global.x - startPoint.x;
    const dy = ev.global.y - startPoint.y;
    if (Math.sqrt(dx * dx + dy * dy) > TARGET_LONG_TAP_MOVE_THRESHOLD) {
      cancelLongTap();
    }
  });
  wrapper.on("pointertap", (ev) => {
    ev.stopPropagation();
    const target = getTarget();
    if (!target) return;
    if (roomEditor.enabled) {
      selectTarget(target, null);
      return;
    }
    if (longTapTriggered) {
      longTapTriggered = false;
      return;
    }
    handleTargetTap(target);
  });
  wrapper.on("rightclick", (ev) => {
    ev.stopPropagation();
    if (roomEditor.enabled) return;
    const target = getTarget();
    if (!target) return;
    handleTargetLook(target);
  });
}

// ─── Prop rendering ───────────────────────────────────────────────────────────

async function pixiCreatePropSprite(prop) {
  const propDef = resolvePropLibraryDef(prop);
  const meta = propDef?.display?.prop_meta;
  let sprite;

  if (meta) {
    const imgUrl = resolveAssetUrl(meta.image_url || "");
    const baseTex = await loadPixiTexture(imgUrl);
    const frame = meta.frame || {};
    const frameTex = makeFrameTexture(baseTex, frame);
    sprite = new PIXI.Sprite(frameTex);
    sprite.rotation = orientationToRadians(prop.position?.orientation);

    if (meta.animation && meta.animation.speed > 0 &&
        Array.isArray(meta.animation.frames) && meta.animation.frames.length > 1) {
      const frames = meta.animation.frames.map(f => makeFrameTexture(baseTex, f));
      let frameIndex = 0;
      const intervalMs = meta.animation.speed * 1000;
      const animTicker = (ticker) => {
        animTicker._elapsed = (animTicker._elapsed || 0) + ticker.deltaMS;
        if (animTicker._elapsed >= intervalMs) {
          animTicker._elapsed = 0;
          frameIndex = (frameIndex + 1) % frames.length;
          sprite.texture = frames[frameIndex];
        }
      };
      pixiApp.ticker.add(animTicker);
      if (meta.offset_x || meta.offset_y) {
        sprite.x = meta.offset_x || 0;
        sprite.y = meta.offset_y || 0;
      }
      return { sprite, animTicker };
    }

    if (meta.offset_x || meta.offset_y) {
      sprite.x = meta.offset_x || 0;
      sprite.y = meta.offset_y || 0;
    }
  } else {
    const imgUrl = resolveAssetUrl(propDef?.display?.sprite || propDef?.display?.img || "");
    const tex = await loadPixiTexture(imgUrl);
    sprite = new PIXI.Sprite(tex);
    sprite.rotation = orientationToRadians(prop.position?.orientation);
    clampSpriteSize(sprite, 64, 64);
  }

  return { sprite, animTicker: null };
}

function _buildPropEditorControls(prop, wrapper) {
  if (!pixiEditorOverlay) return;
  const controlDiv = document.createElement("div");
  controlDiv.className = "room-prop-controls";
  controlDiv.style.pointerEvents = "auto";
  controlDiv.style.position = "absolute";
  controlDiv.style.left = `${(prop.position?.x || 0) + 2}px`;
  controlDiv.style.top = `${Math.max(0, (prop.position?.y || 0) - 14)}px`;

  const rotateBtn = document.createElement("button");
  rotateBtn.type = "button";
  rotateBtn.className = "room-prop-control-btn";
  rotateBtn.textContent = "↻";
  rotateBtn.title = "Rotate";
  rotateBtn.addEventListener("click", ev => {
    ev.preventDefault();
    ev.stopPropagation();
    rotateDraftProp(prop.prop_instance_id);
  });

  const exitBtn = document.createElement("button");
  exitBtn.type = "button";
  exitBtn.className = "room-prop-control-btn";
  exitBtn.textContent = "🚪";
  exitBtn.title = prop.exit_way_id
    ? `Exit: ${prop.exit_way_id} (click to change)`
    : "Assign exit (click to set)";
  exitBtn.addEventListener("click", ev => {
    ev.preventDefault();
    ev.stopPropagation();
    cycleExitAssignment(prop.prop_instance_id);
  });

  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "room-prop-control-btn";
  deleteBtn.textContent = "✕";
  deleteBtn.title = "Delete";
  deleteBtn.addEventListener("click", ev => {
    ev.preventDefault();
    ev.stopPropagation();
    deleteDraftProp(prop.prop_instance_id);
  });

  controlDiv.addEventListener("pointerdown", ev => ev.stopPropagation());
  controlDiv.appendChild(rotateBtn);
  controlDiv.appendChild(exitBtn);
  controlDiv.appendChild(deleteBtn);
  pixiEditorOverlay.appendChild(controlDiv);
}

async function pixiRenderProps() {
  for (const { sprite, animTicker } of pixiPropNodes.values()) {
    if (animTicker) pixiApp.ticker.remove(animTicker);
    sprite.destroy({ children: true });
  }
  pixiPropNodes.clear();
  pixiPropsContainer.removeChildren();
  if (pixiEditorOverlay) pixiEditorOverlay.innerHTML = "";

  for (const prop of getEditableProps().values()) {
    const { sprite, animTicker } = await pixiCreatePropSprite(prop);
    const propDef = resolvePropLibraryDef(prop);
    const exitDef = prop.exit_way_id
      ? (roomState.exits.find(e => e.id === prop.exit_way_id) || null)
      : null;

    const wrapper = new PIXI.Container();
    wrapper.x = prop.position?.x || 0;
    wrapper.y = prop.position?.y || 0;
    wrapper.zIndex = prop.position?.z_order || 0;
    wrapper.eventMode = "static";
    wrapper.cursor = "pointer";
    wrapper.addChild(sprite);

    if (roomEditor.enabled) {
      const bounds = sprite.getLocalBounds();
      const outline = new PIXI.Graphics();
      outline.rect(
        (sprite.x || 0) - 2,
        (sprite.y || 0) - 2,
        (bounds.width || 32) + 4,
        (bounds.height || 32) + 4,
      ).stroke({ color: 0xffce6a, width: 2, alignment: 0 });
      wrapper.addChild(outline);
    }

    if (exitDef) {
      const badge = new PIXI.Text({
        text: `→ ${exitDef.label || prop.exit_way_id}`,
        style: new PIXI.TextStyle({
          fontSize: 10,
          fill: 0xffffee,
          stroke: { color: 0x000000, width: 2 },
        }),
      });
      badge.anchor.set(0.5, 0);
      const bounds = sprite.getLocalBounds();
      badge.x = (sprite.x || 0) + (bounds.width || 32) / 2;
      badge.y = (sprite.y || 0) + (bounds.height || 32) + 4;
      wrapper.addChild(badge);
    }

    bindTargetInteractions(wrapper, () => {
      if (exitDef) {
        return {
          type: "prop",
          id: prop.prop_instance_id,
          label: exitDef.label || propDef?.label || prop.prop_id || "exit",
          description: `Exit to ${exitDef.label || prop.exit_way_id}`,
          exit_way_id: prop.exit_way_id,
          exit_label: exitDef.label || prop.exit_way_id,
        };
      }
      return {
        type: "prop",
        id: prop.prop_instance_id,
        label: propDef?.label || prop.prop_id || "prop",
        description: propDef?.description || "",
      };
    });

    if (roomState.canEditProps && roomEditor.enabled) {
      pixiAttachPropDrag(wrapper, prop.prop_instance_id);
      _buildPropEditorControls(prop, wrapper);
    }

    pixiPropsContainer.addChild(wrapper);
    pixiPropNodes.set(prop.prop_instance_id, { sprite: wrapper, animTicker });
  }
}

function pixiAttachPropDrag(wrapper, propInstanceId) {
  let dragging = false;
  wrapper.on("pointerdown", (ev) => {
    dragging = true;
    ev.stopPropagation();
  });
  wrapper.on("pointerup", () => { dragging = false; });
  wrapper.on("pointerupoutside", () => { dragging = false; });
  wrapper.on("globalpointermove", (ev) => {
    if (!dragging) return;
    const point = getStagePointFromPixi(ev.global.x, ev.global.y);
    if (!point) return;
    const draft = roomEditor.draftProps.get(propInstanceId);
    if (!draft) return;
    draft.position.x = point.x;
    draft.position.y = point.y;
    draft.position.z_order = nextDraftZOrder();
    wrapper.x = point.x;
    wrapper.y = point.y;
    wrapper.zIndex = draft.position.z_order;
  });
}

// ─── Entity rendering ─────────────────────────────────────────────────────────

async function pixiCreateEntitySprite(entity) {
  const display = entity.display || {};
  const spriteMeta = display.sprite_meta || display.img_meta || null;
  const imageUrl = resolveAssetUrl(display.sprite || display.img || "");

  if (!spriteMeta || !spriteMeta.frame) {
    const tex = await loadPixiTexture(imageUrl);
    const sprite = new PIXI.Sprite(tex);
    sprite.anchor.set(0, 0);
    clampSpriteSize(sprite, 64, 128);
    return { sprite, animTicker: null };
  }

  const baseTex = await loadPixiTexture(imageUrl);
  const frame = spriteMeta.frame;
  const frameTex = makeFrameTexture(baseTex, frame);
  const sprite = new PIXI.Sprite(frameTex);
  sprite.anchor.set(0, 0);

  const anim = spriteMeta.animation;
  if (!anim || !Array.isArray(anim.frames) || anim.frames.length <= 1) {
    return { sprite, animTicker: null };
  }

  const frameTextures = anim.frames.map(f => makeFrameTexture(baseTex, f));
  let frameIndex = 0;
  let direction = 1;
  const intervalMs = Math.max(40, Number(anim.speed || 0.5) * 1000);

  const animTicker = (ticker) => {
    animTicker._elapsed = (animTicker._elapsed || 0) + ticker.deltaMS;
    if (animTicker._elapsed < intervalMs) return;
    animTicker._elapsed = 0;

    if (anim.type === "random") {
      frameIndex = Math.floor(Math.random() * frameTextures.length);
    } else if (anim.type === "bounce") {
      frameIndex += direction;
      if (frameIndex >= frameTextures.length) {
        frameIndex = Math.max(0, frameTextures.length - 2);
        direction = -1;
      } else if (frameIndex < 0) {
        frameIndex = Math.min(frameTextures.length - 1, 1);
        direction = 1;
      }
    } else {
      frameIndex = (frameIndex + 1) % frameTextures.length;
    }
    sprite.texture = frameTextures[frameIndex];
  };

  return { sprite, animTicker };
}

async function pixiRenderForegroundEntity(entity) {
  if (roomEditor.enabled) return;

  const key = `${entity.entity_type}:${entity.entity_id}`;
  const posY = entity.position?.y || 0;
  let zIndex = entity.position?.z_order || 0;
  if (roomState.stage.type === 'standard') {
    zIndex = computeStandardZOrder(posY, roomState.stage.bg_height, roomState.cameraFloorHeight);
  }

  let record = pixiEntityNodes.get(key);
  const nextDisplayJson = JSON.stringify(entity.display || {});

  if (!record) {
    const { sprite, animTicker } = await pixiCreateEntitySprite(entity);
    const wrapper = new PIXI.Container();
    wrapper.eventMode = "static";
    wrapper.cursor = "pointer";
    if (animTicker) pixiApp.ticker.add(animTicker);
    wrapper.addChild(sprite);

    bindTargetInteractions(wrapper, () => ({
      type: entity.entity_type,
      id: entity.entity_id,
      label: entity.label || entity.entity_id,
      description: entity.description || "",
    }));

    pixiEntitiesContainer.addChild(wrapper);
    record = {
      wrapper,
      sprite,
      animTicker,
      moveTicker: null,
      moveTween: null,
      displayJson: nextDisplayJson,
      isSelf: entity.is_self,
    };
    pixiEntityNodes.set(key, record);

    if (canDragEntity(entity)) {
      pixiAttachEntityDrag(wrapper, entity.entity_type, entity.entity_id);
    }
  }

  const wrapper = record.wrapper;

  if (record.displayJson !== nextDisplayJson) {
    record.displayJson = nextDisplayJson;
    if (record.animTicker) pixiApp.ticker.remove(record.animTicker);
    wrapper.removeChildren();
    const { sprite, animTicker } = await pixiCreateEntitySprite(entity);
    if (animTicker) pixiApp.ticker.add(animTicker);
    wrapper.addChild(sprite);
    record.sprite = sprite;
    record.animTicker = animTicker;
  }

  wrapper.zIndex = zIndex;

  const targetX = entity.position?.x || 0;
  const targetY = posY;
  const MOVE_DURATION_MS = 180;

  if (Math.abs(wrapper.x - targetX) > 0.5 || Math.abs(wrapper.y - targetY) > 0.5) {
    record.moveTween = {
      fromX: wrapper.x,
      fromY: wrapper.y,
      targetX,
      targetY,
      elapsed: 0,
      duration: MOVE_DURATION_MS,
    };
    if (!record.moveTicker) {
      record.moveTicker = (ticker) => {
        const t = record.moveTween;
        if (!t) return;
        t.elapsed += ticker.deltaMS;
        const progress = Math.min(1, t.elapsed / t.duration);
        wrapper.x = t.fromX + (t.targetX - t.fromX) * progress;
        wrapper.y = t.fromY + (t.targetY - t.fromY) * progress;
        if (progress >= 1) {
          record.moveTween = null;
          pixiApp.ticker.remove(record.moveTicker);
          record.moveTicker = null;
        }
      };
      pixiApp.ticker.add(record.moveTicker);
    }
  } else {
    wrapper.x = targetX;
    wrapper.y = targetY;
  }
}

function pixiRemoveEntity(key) {
  const record = pixiEntityNodes.get(key);
  if (!record) return;
  if (record.animTicker) pixiApp.ticker.remove(record.animTicker);
  if (record.moveTicker) pixiApp.ticker.remove(record.moveTicker);
  record.wrapper.destroy({ children: true });
  pixiEntityNodes.delete(key);
}

// ─── Selection highlight ──────────────────────────────────────────────────────

function pixiSetEntitySelected(key, isSelected) {
  const record = pixiEntityNodes.get(key);
  if (!record) return;
  const wrapper = record.wrapper;
  const old = wrapper.getChildByLabel("selectionOutline");
  if (old) old.destroy();
  if (isSelected) {
    const bounds = record.sprite.getLocalBounds();
    const outline = new PIXI.Graphics({ label: "selectionOutline" });
    outline.rect(-2, -2, (bounds.width || 32) + 4, (bounds.height || 32) + 4)
           .stroke({ color: 0x3c8cff, width: 2 });
    wrapper.addChild(outline);
  }
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

// Convert PixiJS global canvas coordinates to room-space coordinates.
function getStagePointFromPixi(pixiX, pixiY) {
  const stage = roomState.stage;
  const totalHeight = getStageTotalHeight(stage, roomState.cameraFloorHeight);
  const canvasW = pixiApp.canvas.clientWidth;
  const canvasH = pixiApp.canvas.clientHeight;

  const x = Math.round(pixiX * (stage.width / canvasW));
  const y = Math.round(pixiY * (totalHeight / canvasH));

  const clampedX = Math.min(stage.width, Math.max(0, x));
  let clampedY;
  if (stage.type === 'standard') {
    clampedY = Math.min(
      stage.bg_height + roomState.cameraFloorHeight,
      Math.max(stage.bg_height, y),
    );
  } else {
    clampedY = Math.min(totalHeight, Math.max(0, y));
  }
  return { x: clampedX, y: clampedY };
}

// ─── Click-to-move ────────────────────────────────────────────────────────────

function pixiAttachStageClickToMove() {
  pixiApp.stage.eventMode = "static";
  pixiApp.stage.hitArea = new PIXI.Rectangle(
    0, 0,
    roomState.stage.width,
    getStageTotalHeight(roomState.stage, roomState.cameraFloorHeight),
  );
  pixiApp.stage.on("pointertap", (ev) => {
    if (roomEditor.enabled) return;
    if (!myUsername) return;
    const point = getStagePointFromPixi(ev.global.x, ev.global.y);
    if (!point) return;
    _moveOwnPeepTo(point.x, point.y);
  });
}

// ─── Entity drag ─────────────────────────────────────────────────────────────

function pixiAttachEntityDrag(wrapper, entityType, entityId) {
  let dragging = false;

  wrapper.on("pointerdown", (ev) => {
    dragging = true;
    ev.stopPropagation();
  });
  wrapper.on("pointerup", (ev) => {
    if (dragging && entityType === "object" && myUsername) {
      // Check if dropped onto own peep (pick up)
      const myKey = `peep:${myUsername}`;
      const myRecord = pixiEntityNodes.get(myKey);
      if (myRecord) {
        const peepBounds = myRecord.wrapper.getBounds();
        if (ev.global.x >= peepBounds.x && ev.global.x <= peepBounds.x + peepBounds.width &&
            ev.global.y >= peepBounds.y && ev.global.y <= peepBounds.y + peepBounds.height) {
          socket.emit("message", { text: `:pick @obj:${entityId}` });
          dragging = false;
          return;
        }
      }
    }
    dragging = false;
  });
  wrapper.on("pointerupoutside", () => { dragging = false; });
  wrapper.on("globalpointermove", (ev) => {
    if (!dragging) return;
    const point = getStagePointFromPixi(ev.global.x, ev.global.y);
    if (!point) return;
    _submitPixiMovePayload(entityType, entityId, point.x, point.y);
  });
}

function _submitPixiMovePayload(entityType, entityId, x, y) {
  const moveEvent = { entity_type: entityType, entity_id: entityId, x, y };
  if (roomState.stage.type === 'standard') {
    moveEvent.z_order = computeStandardZOrder(
      y, roomState.stage.bg_height, roomState.cameraFloorHeight
    );
  }
  socket.emit("room_move_entity", moveEvent);
}

function canDragEntity(entity) {
  if (roomEditor.enabled) return false;
  if (entity.entity_type === "object") return true;
  if (entity.entity_type === "peep") {
    return entity.owner_username !== myUsername && roomState.canEditProps;
  }
  return false;
}

// ─── Move own peep ────────────────────────────────────────────────────────────

function _moveOwnPeepTo(x, y) {
  const myKey = `peep:${myUsername}`;
  const myEntity = roomState.entities.get(myKey);

  if (myEntity && myEntity.position) {
    myEntity.position.x = x;
    myEntity.position.y = y;
    if (roomState.stage.type === "standard") {
      myEntity.position.z_order = computeStandardZOrder(
        y, roomState.stage.bg_height, roomState.cameraFloorHeight
      );
    }
    // Optimistic update: trigger smooth movement tween in PixiJS
    pixiRenderForegroundEntity(myEntity);
  }

  const moveEvent = { entity_type: "peep", entity_id: myUsername, x, y };
  if (roomState.stage.type === "standard") {
    moveEvent.z_order = computeStandardZOrder(
      y, roomState.stage.bg_height, roomState.cameraFloorHeight
    );
  }
  socket.emit("room_move_entity", moveEvent);
}

// ─── Floor height / camera ────────────────────────────────────────────────────

function setCameraFloorHeight(newFloorHeight) {
  const stage = roomState.stage;
  if (stage.type !== 'standard') return;
  const oldFloorH = roomState.cameraFloorHeight;
  if (oldFloorH === newFloorHeight) return;

  const bgH = stage.bg_height;
  for (const entity of roomState.entities.values()) {
    if (!entity.position) continue;
    const relY = Math.max(0, entity.position.y - bgH);
    const ratio = oldFloorH > 0 ? relY / oldFloorH : 0;
    entity.position.y = bgH + Math.round(ratio * newFloorHeight);
  }
  roomState.cameraFloorHeight = newFloorHeight;

  const totalH = bgH + newFloorHeight;
  roomCanvas.style.height = `${totalH}px`;
  if (pixiApp) pixiApp.renderer.resize(stage.width, totalH);

  pixiRenderBackground(roomState.backgroundPath);
  for (const entity of roomState.entities.values()) {
    pixiRenderForegroundEntity(entity);
  }
}

// ─── Entity state reset ───────────────────────────────────────────────────────

function resetRoomEntityState() {
  if (pixiApp) {
    for (const record of pixiEntityNodes.values()) {
      if (record.animTicker) pixiApp.ticker.remove(record.animTicker);
      if (record.moveTicker) pixiApp.ticker.remove(record.moveTicker);
      record.wrapper.destroy({ children: true });
    }
  }
  pixiEntityNodes.clear();
  roomState.entities.clear();
  selectedTarget = null;
  lookBox.textContent = "";
  clearRoomSelection();
}

// ─── Stage rendering orchestrator ────────────────────────────────────────────

async function renderRoomStage(backgroundPath) {
  await initPixiApp();

  const stage = roomState.stage;
  const totalH = getStageTotalHeight(stage, roomState.cameraFloorHeight);

  pixiApp.renderer.resize(stage.width, totalH);
  pixiApp.stage.hitArea = new PIXI.Rectangle(0, 0, stage.width, totalH);

  await pixiRenderBackground(backgroundPath);
  await pixiRenderProps();

  if (!roomEditor.enabled) {
    for (const entity of roomState.entities.values()) {
      await pixiRenderForegroundEntity(entity);
    }
  }

  renderRoomEditorActivity();
}
