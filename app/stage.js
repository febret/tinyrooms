// ─── Stage math helpers ──────────────────────────────────────────────────────

function getStageTotalHeight(stage, cameraFloorHeight) {
  if (stage.type === 'standard') {
    return getStageBackgroundHeight(stage) + getStageFloorHeight(cameraFloorHeight);
  }
  return Math.max(1, toStageNumber(stage.height, 1));
}

// Depth-sort z-index for an entity on the standard stage floor.
function computeStandardZOrder(y, bgH, floorH) {
  return Math.round(Math.max(0, y - bgH) / Math.max(1, floorH) * 1000);
}

function toStageNumber(value, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function getStageWidth(stage) {
  return Math.max(1, toStageNumber(stage?.width, 1));
}

function getStageBackgroundHeight(stage) {
  return Math.max(0, toStageNumber(stage?.bg_height, 0));
}

function getStageFloorHeight(cameraFloorHeight) {
  return Math.max(0, toStageNumber(cameraFloorHeight, 0));
}

// ─── PixiJS globals ───────────────────────────────────────────────────────────

var pixiApp = null;
var pixiBgContainer = null;
var pixiPropsContainer = null;
var pixiEntitiesContainer = null;
var pixiTextureCache = new Map();
// Per-entity: key → { wrapper, sprite, animTicker, decoratorTicker, moveTicker, moveTween, renderJson, isSelf }
var pixiEntityNodes = new Map();
// Per-prop: propInstanceId → { sprite (wrapper Container), animTicker }
var pixiPropNodes = new Map();
// DOM overlay for editor prop controls (positioned above the PixiJS canvas)
var pixiEditorOverlay = null;
var roomPanelResizeObserver = null;
var roomPanelResizeBound = false;

function computeRoomCanvasFitSize(stageW, stageH) {
  const viewPanel = document.getElementById("viewPanel");
  if (!viewPanel || stageW <= 0 || stageH <= 0) {
    return { width: Math.max(1, stageW || 1), height: Math.max(1, stageH || 1) };
  }
  const style = window.getComputedStyle(viewPanel);
  const paddingX = (parseFloat(style.paddingLeft) || 0) + (parseFloat(style.paddingRight) || 0);
  const paddingY = (parseFloat(style.paddingTop) || 0) + (parseFloat(style.paddingBottom) || 0);
  const availableW = viewPanel.clientWidth - paddingX;
  const availableH = viewPanel.clientHeight - paddingY;
  if (!Number.isFinite(availableW) || !Number.isFinite(availableH) || availableW <= 0 || availableH <= 0) {
    return { width: Math.max(1, stageW), height: Math.max(1, stageH) };
  }
  const scale = Math.min(availableW / stageW, availableH / stageH);
  if (!Number.isFinite(scale) || scale <= 0) {
    return { width: Math.max(1, stageW), height: Math.max(1, stageH) };
  }
  const fittedW = Math.min(availableW, stageW * scale);
  const fittedH = Math.min(availableH, stageH * scale);
  return {
    width: Math.max(1, Number(fittedW.toFixed(3))),
    height: Math.max(1, Number(fittedH.toFixed(3))),
  };
}

function updateEditorOverlayControlPositions() {
  if (!pixiEditorOverlay || !roomState.stage) return;
  const stageW = getStageWidth(roomState.stage);
  const stageH = getStageTotalHeight(roomState.stage, roomState.cameraFloorHeight) || 1;
  const scaleX = roomCanvas.clientWidth / stageW;
  const scaleY = roomCanvas.clientHeight / stageH;
  if (!Number.isFinite(scaleX) || !Number.isFinite(scaleY) || scaleX <= 0 || scaleY <= 0) return;
  const controls = pixiEditorOverlay.querySelectorAll(".room-prop-controls");
  for (const control of controls) {
    const stageX = Number.parseFloat(control.dataset.stageX || "0");
    const stageY = Number.parseFloat(control.dataset.stageY || "0");
    control.style.left = `${Math.round((stageX + 2) * scaleX)}px`;
    control.style.top = `${Math.round(Math.max(0, stageY - 14) * scaleY)}px`;
  }
}

function fitRoomCanvasToViewPanel() {
  if (!roomCanvas || !roomState.stage) return;
  // const stageW = getStageWidth(roomState.stage);
  // const stageH = getStageTotalHeight(roomState.stage, roomState.cameraFloorHeight) || 1;
  // const fit = computeRoomCanvasFitSize(stageW, stageH);
  // roomCanvas.style.width = `${fit.width}px`;
  // roomCanvas.style.height = `${fit.height}px`;
  roomCanvas.style.width = "100%";
  roomCanvas.style.height = "100%";
  updateEditorOverlayControlPositions();
}

function bindRoomCanvasAutoFit() {
  if (roomPanelResizeBound) return;
  roomPanelResizeBound = true;
  window.addEventListener("resize", fitRoomCanvasToViewPanel);
  const viewPanel = document.getElementById("viewPanel");
  if (viewPanel && typeof ResizeObserver === "function") {
    roomPanelResizeObserver = new ResizeObserver(() => {
      fitRoomCanvasToViewPanel();
    });
    roomPanelResizeObserver.observe(viewPanel);
  }
}

async function initPixiApp() {
  if (pixiApp) return;
  pixiApp = new PIXI.Application();
  await pixiApp.init({
    width: getStageWidth(roomState.stage),
    height: getStageTotalHeight(roomState.stage, roomState.cameraFloorHeight),
    backgroundAlpha: 0,
    antialias: false,
    autoDensity: true,
    resolution: window.devicePixelRatio || 1,
    autoStart: true,
    preference: "webgl"
    });
  pixiApp.canvas.style.cssText = "width:100%;height:100%;";
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
  bindRoomCanvasAutoFit();
  fitRoomCanvasToViewPanel();
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
  const stageW = getStageWidth(stage);

  if (backgroundPath) {
    const bgUrl = resolveBackgroundUrl(backgroundPath);
    const bgTex = await loadPixiTexture(bgUrl);
    const bgH = stage.type === 'standard' ? getStageBackgroundHeight(stage) : totalH;

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
    const floorY = getStageBackgroundHeight(stage);
    const floorH = getStageFloorHeight(roomState.cameraFloorHeight);
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

function createFrameAnimationTicker(sprite, frameTextures, intervalMs, animationType = "loop") {
  let elapsedMs = 0;
  let frameIndex = 0;
  let direction = 1;
  return (ticker) => {
    elapsedMs += ticker.deltaMS;
    if (elapsedMs < intervalMs) return;
    elapsedMs = 0;

    if (animationType === "random") {
      frameIndex = Math.floor(Math.random() * frameTextures.length);
    } else if (animationType === "bounce") {
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
}

function normalizeDecoratorPayloads(rawDecorators) {
  if (!Array.isArray(rawDecorators)) return [];
  return rawDecorators.filter((item) => item && typeof item === "object");
}

function parseDecoratorColor(value, fallback = 0xffffff) {
  if (typeof value !== "string") return fallback;
  const raw = value.trim();
  if (!raw) return fallback;
  if (raw.startsWith("#")) {
    const hex = raw.slice(1);
    if (/^[0-9a-fA-F]{6}$/.test(hex)) {
      return Number.parseInt(hex, 16);
    }
  }
  return fallback;
}

function clampDecoratorIntensity(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

async function pixiCreateDecoratorSprite(decoratorPayload) {
  const spriteDisplay = decoratorPayload?.sprite_display;
  if (!spriteDisplay || typeof spriteDisplay !== "object") return null;
  const meta = spriteDisplay.sprite_meta || spriteDisplay.img_meta || null;
  const imageUrl = resolveAssetUrl(spriteDisplay.sprite || spriteDisplay.img || "");
  if (!imageUrl) return null;

  if (!meta || !meta.frame) {
    const tex = await loadPixiTexture(imageUrl);
    const sprite = new PIXI.Sprite(tex);
    clampSpriteSize(sprite, 96, 128);
    return { sprite, animTicker: null };
  }

  const baseTex = await loadPixiTexture(imageUrl);
  const frameTex = makeFrameTexture(baseTex, meta.frame || {});
  const sprite = new PIXI.Sprite(frameTex);
  const anim = meta.animation;
  if (!anim || !Array.isArray(anim.frames) || anim.frames.length <= 1) {
    return { sprite, animTicker: null };
  }
  const frames = anim.frames.map((frame) => makeFrameTexture(baseTex, frame));
  const intervalMs = Math.max(40, Number(anim.speed || 0.5) * 1000);
  const animTicker = createFrameAnimationTicker(sprite, frames, intervalMs, anim.type || "loop");
  return { sprite, animTicker };
}

async function pixiApplyDecoratorsToWrapper(wrapper, baseSprite, decorators, orientationRadians = null) {
  const normalized = normalizeDecoratorPayloads(decorators);
  if (normalized.length === 0) {
    return null;
  }

  let glowConfig = null;
  let animationName = "";
  const spriteDecorators = [];
  for (const decorator of normalized) {
    if (decorator.glow && typeof decorator.glow === "object") {
      glowConfig = decorator.glow;
    }
    if (typeof decorator.animation === "string" && decorator.animation.trim()) {
      animationName = decorator.animation.trim().toLowerCase();
    }
    if (decorator.sprite_display && typeof decorator.sprite_display === "object") {
      spriteDecorators.push(decorator);
    }
  }

  const tickers = [];
  const overlaySprites = [];
  for (const decorator of spriteDecorators) {
    const created = await pixiCreateDecoratorSprite(decorator);
    if (!created) continue;
    const overlay = created.sprite;
    overlay.x = baseSprite.x || 0;
    overlay.y = baseSprite.y || 0;
    overlay.anchor.set(baseSprite.anchor?.x || 0, baseSprite.anchor?.y || 0);
    overlay.scale.set(baseSprite.scale?.x || 1, baseSprite.scale?.y || 1);
    if (typeof orientationRadians === "number") {
      overlay.rotation = orientationRadians;
    }
    wrapper.addChild(overlay);
    overlaySprites.push(overlay);
    if (created.animTicker) {
      tickers.push(created.animTicker);
    }
  }

  let glowSprite = null;
  if (glowConfig) {
    const intensity = clampDecoratorIntensity(glowConfig.intensity);
    if (intensity > 0) {
      glowSprite = new PIXI.Sprite(baseSprite.texture);
      glowSprite.x = baseSprite.x || 0;
      glowSprite.y = baseSprite.y || 0;
      glowSprite.anchor.set(baseSprite.anchor?.x || 0, baseSprite.anchor?.y || 0);
      glowSprite.rotation = baseSprite.rotation || 0;
      glowSprite.scale.set((baseSprite.scale?.x || 1) * 1.12, (baseSprite.scale?.y || 1) * 1.12);
      glowSprite.tint = parseDecoratorColor(glowConfig.color, 0xffffff);
      glowSprite.alpha = Math.min(0.9, 0.15 + intensity * 0.6);
      glowSprite.blendMode = PIXI.BLEND_MODES.ADD;
      wrapper.addChildAt(glowSprite, 0);
    }
  }

  const baseRotation = baseSprite.rotation || 0;
  const baseScaleX = baseSprite.scale?.x || 1;
  const baseScaleY = baseSprite.scale?.y || 1;
  const animateWobble = animationName === "wobble";
  const animateSpin = animationName === "spin";
  const animatePulse = animationName === "pulse";

  if (glowSprite || animateWobble || animateSpin || animatePulse) {
    let elapsed = 0;
    tickers.push((ticker) => {
      elapsed += ticker.deltaMS;
      if (glowSprite) {
        glowSprite.texture = baseSprite.texture;
      }
      if (animateSpin) {
        const spin = ((elapsed * 0.006) % (Math.PI * 2));
        baseSprite.rotation = baseRotation + spin;
      } else if (animateWobble) {
        baseSprite.rotation = baseRotation + Math.sin(elapsed * 0.012) * 0.12;
      } else {
        baseSprite.rotation = baseRotation;
      }
      if (animatePulse) {
        const pulseScale = 1 + (Math.sin(elapsed * 0.01) * 0.09);
        baseSprite.scale.set(baseScaleX * pulseScale, baseScaleY * pulseScale);
      } else {
        baseSprite.scale.set(baseScaleX, baseScaleY);
      }
      for (const overlaySprite of overlaySprites) {
        overlaySprite.x = baseSprite.x || 0;
        overlaySprite.y = baseSprite.y || 0;
      }
    });
  }

  if (tickers.length === 0) {
    return null;
  }
  return (ticker) => {
    for (const fn of tickers) {
      fn(ticker);
    }
  };
}

function pointInBox(point, box) {
  if (!point || !box) return false;
  return (
    point.x >= box.left &&
    point.x <= box.right &&
    point.y >= box.top &&
    point.y <= box.bottom
  );
}

function toLeftTopRightBottom(box) {
  return {
    left: box.x,
    top: box.y,
    right: box.x + box.width,
    bottom: box.y + box.height,
  };
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
      selectTarget(target);
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
      const intervalMs = meta.animation.speed * 1000;
      const animTicker = createFrameAnimationTicker(sprite, frames, intervalMs, "loop");
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
  controlDiv.dataset.stageX = String(prop.position?.x || 0);
  controlDiv.dataset.stageY = String(prop.position?.y || 0);
  controlDiv.style.pointerEvents = "auto";
  controlDiv.style.position = "absolute";
  controlDiv.style.left = "0px";
  controlDiv.style.top = "0px";

  function makePropControlButton(icon, title, onClick) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "room-prop-control-btn";
    button.textContent = icon;
    button.title = title;
    button.addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      onClick();
    });
    return button;
  }

  const rotateBtn = makePropControlButton("↻", "Rotate", () => {
    rotateDraftProp(prop.prop_instance_id);
  });
  const exitBtn = makePropControlButton(
    "🚪",
    prop.exit_way_id
      ? `Exit: ${prop.exit_way_id} (click to change)`
      : "Assign exit (click to set)",
    () => {
      cycleExitAssignment(prop.prop_instance_id);
    },
  );
  const deleteBtn = makePropControlButton("✕", "Delete", () => {
    deleteDraftProp(prop.prop_instance_id);
  });

  controlDiv.addEventListener("pointerdown", ev => ev.stopPropagation());
  controlDiv.appendChild(rotateBtn);
  controlDiv.appendChild(exitBtn);
  controlDiv.appendChild(deleteBtn);
  pixiEditorOverlay.appendChild(controlDiv);
  updateEditorOverlayControlPositions();
}

async function pixiRenderProps() {
  for (const { sprite, animTicker, decoratorTicker } of pixiPropNodes.values()) {
    if (animTicker) pixiApp.ticker.remove(animTicker);
    if (decoratorTicker) pixiApp.ticker.remove(decoratorTicker);
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
    const decoratorTicker = await pixiApplyDecoratorsToWrapper(
      wrapper,
      sprite,
      prop.decorators || [],
      orientationToRadians(prop.position?.orientation),
    );
    if (decoratorTicker) {
      pixiApp.ticker.add(decoratorTicker);
    }

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
    pixiPropNodes.set(prop.prop_instance_id, { sprite: wrapper, animTicker, decoratorTicker });
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
  const intervalMs = Math.max(40, Number(anim.speed || 0.5) * 1000);
  const animTicker = createFrameAnimationTicker(
    sprite,
    frameTextures,
    intervalMs,
    anim.type || "loop",
  );

  return { sprite, animTicker };
}

async function pixiRenderForegroundEntity(entity) {
  if (roomEditor.enabled) return;

  const key = `${entity.entity_type}:${entity.entity_id}`;
  const posY = entity.position?.y || 0;
  let zIndex = entity.position?.z_order || 0;
  if (roomState.stage.type === 'standard') {
    zIndex = computeStandardZOrder(
      posY,
      getStageBackgroundHeight(roomState.stage),
      getStageFloorHeight(roomState.cameraFloorHeight),
    );
  }

  let record = pixiEntityNodes.get(key);
  const nextRenderJson = JSON.stringify({
    display: entity.display || {},
    decorators: entity.decorators || [],
  });

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
      decoratorTicker: null,
      renderJson: nextRenderJson,
      isSelf: entity.is_self,
    };
    const decoratorTicker = await pixiApplyDecoratorsToWrapper(
      wrapper,
      sprite,
      entity.decorators || [],
    );
    if (decoratorTicker) {
      pixiApp.ticker.add(decoratorTicker);
      record.decoratorTicker = decoratorTicker;
    }
    pixiEntityNodes.set(key, record);

    if (canDragEntity(entity)) {
      pixiAttachEntityDrag(wrapper, entity.entity_type, entity.entity_id);
    }
  }

  const wrapper = record.wrapper;

  if (record.renderJson !== nextRenderJson) {
    record.renderJson = nextRenderJson;
    if (record.animTicker) pixiApp.ticker.remove(record.animTicker);
    if (record.decoratorTicker) pixiApp.ticker.remove(record.decoratorTicker);
    wrapper.removeChildren();
    const { sprite, animTicker } = await pixiCreateEntitySprite(entity);
    if (animTicker) pixiApp.ticker.add(animTicker);
    wrapper.addChild(sprite);
    record.sprite = sprite;
    record.animTicker = animTicker;
    const decoratorTicker = await pixiApplyDecoratorsToWrapper(
      wrapper,
      sprite,
      entity.decorators || [],
    );
    record.decoratorTicker = decoratorTicker;
    if (decoratorTicker) {
      pixiApp.ticker.add(decoratorTicker);
    }
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
  if (record.decoratorTicker) pixiApp.ticker.remove(record.decoratorTicker);
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
  const x = Math.round((clientX - rect.left) * (getStageWidth(stage) / rect.width));
  const y = Math.round((clientY - rect.top) * (totalHeight / rect.height));
  return clampStagePoint(x, y, stage, totalHeight);
}

// Convert PixiJS global canvas coordinates to room-space coordinates.
function getStagePointFromPixi(pixiX, pixiY) {
  const stage = roomState.stage;
  const totalHeight = getStageTotalHeight(stage, roomState.cameraFloorHeight);
  const canvasW = pixiApp.canvas.clientWidth;
  const canvasH = pixiApp.canvas.clientHeight;

  const x = Math.round(pixiX * (getStageWidth(stage) / canvasW));
  const y = Math.round(pixiY * (totalHeight / canvasH));
  return clampStagePoint(x, y, stage, totalHeight);
}

function clampStagePoint(x, y, stage, totalHeight) {
  const clampedX = Math.min(getStageWidth(stage), Math.max(0, x));
  let clampedY = Math.min(totalHeight, Math.max(0, y));
  if (stage.type === 'standard') {
    const floorTop = getStageBackgroundHeight(stage);
    const floorBottom = floorTop + getStageFloorHeight(roomState.cameraFloorHeight);
    clampedY = Math.min(floorBottom, Math.max(floorTop, clampedY));
  }
  return { x: clampedX, y: clampedY };
}

function getClientPointFromPixi(pixiX, pixiY) {
  const rect = roomCanvas.getBoundingClientRect();
  const canvasW = pixiApp.canvas.clientWidth;
  const canvasH = pixiApp.canvas.clientHeight;
  if (!rect.width || !rect.height || !canvasW || !canvasH) return null;
  return {
    x: rect.left + (pixiX * rect.width / canvasW),
    y: rect.top + (pixiY * rect.height / canvasH),
  };
}

// ─── Click-to-move ────────────────────────────────────────────────────────────

function pixiAttachStageClickToMove() {
  pixiApp.stage.eventMode = "static";
  pixiApp.stage.hitArea = new PIXI.Rectangle(
    0, 0,
    getStageWidth(roomState.stage),
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
  let latestGlobalPointer = null;
  let latestClientPointer = null;
  let windowPointerUpHandler = null;
  let windowPointerCancelHandler = null;

  function updatePointer(pixiX, pixiY) {
    latestGlobalPointer = { x: pixiX, y: pixiY };
    latestClientPointer = getClientPointFromPixi(pixiX, pixiY);
  }

  function resetDragState() {
    dragging = false;
    latestGlobalPointer = null;
    latestClientPointer = null;
  }

  function unbindWindowPointerEnd() {
    if (windowPointerUpHandler) {
      window.removeEventListener("pointerup", windowPointerUpHandler, true);
      windowPointerUpHandler = null;
    }
    if (windowPointerCancelHandler) {
      window.removeEventListener("pointercancel", windowPointerCancelHandler, true);
      windowPointerCancelHandler = null;
    }
  }

  function bindWindowPointerEnd() {
    if (windowPointerUpHandler || windowPointerCancelHandler) return;
    windowPointerUpHandler = (ev) => {
      if (!dragging) return;
      if (typeof ev.clientX === "number" && typeof ev.clientY === "number") {
        latestClientPointer = { x: ev.clientX, y: ev.clientY };
      }
      finalizeDrag();
    };
    windowPointerCancelHandler = () => {
      if (!dragging) return;
      finalizeDrag();
    };
    window.addEventListener("pointerup", windowPointerUpHandler, true);
    window.addEventListener("pointercancel", windowPointerCancelHandler, true);
  }

  function finalizeDrag(ev) {
    unbindWindowPointerEnd();
    if (dragging && entityType === "object" && myUsername) {
      const inventoryPanel = document.getElementById("inventoryPanel");
      if (inventoryPanel && latestClientPointer) {
        if (pointInBox(latestClientPointer, inventoryPanel.getBoundingClientRect())) {
          socket.emit("message", { text: `:pick @obj:${entityId}` });
          resetDragState();
          return;
        }
      }
      // Check if dropped onto own peep (pick up)
      const myKey = `peep:${myUsername}`;
      const myRecord = pixiEntityNodes.get(myKey);
      const eventPoint = ev?.global || latestGlobalPointer;
      if (myRecord && eventPoint) {
        if (pointInBox(eventPoint, toLeftTopRightBottom(myRecord.wrapper.getBounds()))) {
          socket.emit("message", { text: `:pick @obj:${entityId}` });
          resetDragState();
          return;
        }
      }
    }
    resetDragState();
  }

  wrapper.on("pointerdown", (ev) => {
    dragging = true;
    updatePointer(ev.global.x, ev.global.y);
    bindWindowPointerEnd();
    ev.stopPropagation();
  });
  wrapper.on("pointerup", (ev) => {
    updatePointer(ev.global.x, ev.global.y);
    finalizeDrag(ev);
  });
  wrapper.on("pointerupoutside", (ev) => {
    if (ev?.global) {
      updatePointer(ev.global.x, ev.global.y);
    }
    finalizeDrag(ev);
  });
  wrapper.on("globalpointermove", (ev) => {
    if (!dragging) return;
    updatePointer(ev.global.x, ev.global.y);
    const point = getStagePointFromPixi(ev.global.x, ev.global.y);
    if (!point) return;
    _submitPixiMovePayload(entityType, entityId, point.x, point.y);
  });
}

function _submitPixiMovePayload(entityType, entityId, x, y) {
  socket.emit("room_move_entity", _buildMoveEvent(entityType, entityId, x, y));
}

function _buildMoveEvent(entityType, entityId, x, y) {
  const moveEvent = { entity_type: entityType, entity_id: entityId, x, y };
  if (roomState.stage.type === "standard") {
    moveEvent.z_order = computeStandardZOrder(
      y,
      getStageBackgroundHeight(roomState.stage),
      getStageFloorHeight(roomState.cameraFloorHeight),
    );
  }
  return moveEvent;
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
  const moveEvent = _buildMoveEvent("peep", myUsername, x, y);

  if (myEntity && myEntity.position) {
    myEntity.position.x = x;
    myEntity.position.y = y;
    if (moveEvent.z_order !== undefined) {
      myEntity.position.z_order = moveEvent.z_order;
    }
    // Optimistic update: trigger smooth movement tween in PixiJS
    pixiRenderForegroundEntity(myEntity);
  }

  socket.emit("room_move_entity", moveEvent);
}

// ─── Floor height / camera ────────────────────────────────────────────────────

function setCameraFloorHeight(newFloorHeight) {
  const stage = roomState.stage;
  if (stage.type !== 'standard') return;
  const oldFloorH = getStageFloorHeight(roomState.cameraFloorHeight);
  const nextFloorH = getStageFloorHeight(newFloorHeight);
  if (oldFloorH === nextFloorH) return;

  const bgH = getStageBackgroundHeight(stage);
  for (const entity of roomState.entities.values()) {
    if (!entity.position) continue;
    const relY = Math.max(0, entity.position.y - bgH);
    const ratio = oldFloorH > 0 ? relY / oldFloorH : 0;
    entity.position.y = bgH + Math.round(ratio * nextFloorH);
  }
  roomState.cameraFloorHeight = nextFloorH;

  const totalH = bgH + nextFloorH;
  if (pixiApp) pixiApp.renderer.resize(getStageWidth(stage), totalH);
  fitRoomCanvasToViewPanel();

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
      if (record.decoratorTicker) pixiApp.ticker.remove(record.decoratorTicker);
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
  const stageW = getStageWidth(stage);
  const totalH = getStageTotalHeight(stage, roomState.cameraFloorHeight);

  pixiApp.renderer.resize(stageW, totalH);
  pixiApp.stage.hitArea = new PIXI.Rectangle(0, 0, stageW, totalH);
  fitRoomCanvasToViewPanel();

  await pixiRenderBackground(backgroundPath);
  await pixiRenderProps();

  if (!roomEditor.enabled) {
    for (const entity of roomState.entities.values()) {
      await pixiRenderForegroundEntity(entity);
    }
  }

  renderRoomEditorActivity();
}
