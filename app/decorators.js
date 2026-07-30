/**
 * Create a ticker callback that renders a temporary floating text node above a sprite.
 * The ticker fades and rises the text over time, then removes/destroys it on completion.
 *
 * @param {PIXI.Container} wrapper Parent container that owns the floating text node.
 * @param {PIXI.Sprite} baseSprite Sprite used to derive local positioning.
 * @param {object} floatingText Floating text payload (text, duration, rise, style).
 * @param {Function|null} getFacingDirection Optional callback returning facing sign (<0 flips text).
 * @param {Function|null} onComplete Optional callback invoked with tickerFn when effect completes.
 * @returns {Function|null} Pixi ticker callback, or null when payload has no text.
 */
function createFloatingTextDecoratorTicker(
  wrapper,
  baseSprite,
  floatingText,
  getFacingDirection = null,
  onComplete = null,
) {
  const text = String(floatingText?.text || "").trim();
  if (!text) return null;

  const durationMs = clampNumber(
    floatingText?.duration_ms ?? floatingText?.durationMs ?? 1600,
    200,
    Number.POSITIVE_INFINITY,
    1600,
  );
  const risePx = clampNumber(
    floatingText?.rise_px ?? floatingText?.risePx ?? 18,
    0,
    Number.POSITIVE_INFINITY,
    18,
  );
  const fontSize = clampNumber(
    floatingText?.font_size ?? floatingText?.fontSize ?? 14,
    10,
    Number.POSITIVE_INFINITY,
    14,
  );
  const strokeWidth = clampNumber(
    floatingText?.stroke_width ?? floatingText?.strokeWidth ?? 3,
    0,
    Number.POSITIVE_INFINITY,
    3,
  );
  const color = parseHexColorInt(floatingText?.color, 0xffffff);
  const strokeColor = parseHexColorInt(
    floatingText?.stroke_color ?? floatingText?.strokeColor,
    0x000000,
  );

  const spriteBounds = baseSprite.getLocalBounds();
  const baseX = (spriteBounds.x || 0) + (spriteBounds.width || 0) / 2;
  const baseY = (spriteBounds.y || 0) - 6;

  const textNode = new PIXI.Text({
    text: text.slice(0, 64),
    style: new PIXI.TextStyle({
      fontSize,
      fill: color,
      fontWeight: "700",
      stroke: { color: strokeColor, width: strokeWidth },
      align: "center",
    }),
  });
  textNode.anchor.set(0.5, 1);
  textNode.x = baseX;
  textNode.y = baseY;
  wrapper.addChild(textNode);

  let elapsedMs = 0;
  const tickerFn = (ticker) => {
    elapsedMs += ticker.deltaMS;
    const progress = Math.min(1, elapsedMs / durationMs);
    textNode.x = baseX;
    textNode.y = baseY - risePx * progress;
    textNode.alpha = 1 - progress;
    if (typeof getFacingDirection === "function") {
      textNode.scale.x = getFacingDirection() < 0 ? -1 : 1;
    }
    if (progress < 1) return;
    if (textNode.parent) {
      textNode.parent.removeChild(textNode);
    }
    textNode.destroy();
    if (pixiApp) {
      pixiApp.ticker.remove(tickerFn);
    }
    if (typeof onComplete === "function") {
      onComplete(tickerFn);
    }
  };
  return tickerFn;
}

/**
 * Build a decorator overlay sprite (with optional frame animation) from server payload.
 *
 * @param {object} decoratorPayload Decorator payload containing `sprite_display`.
 * @returns {Promise<{sprite: PIXI.Sprite, animTicker: Function|null}|null>} Created sprite bundle or null.
 */
async function pixiCreateDecoratorSprite(decoratorPayload) {
  const spriteDisplay = decoratorPayload?.sprite_display;
  if (!spriteDisplay || typeof spriteDisplay !== "object") return null;

  const meta = spriteDisplay.sprite_meta || spriteDisplay.img_meta || null;
  const normalizedScale = clampNumber(meta?.scale, 0, Number.POSITIVE_INFINITY, 1) || 1;
  const imageUrl = resolveAssetUrl(spriteDisplay.sprite || spriteDisplay.img || "");
  if (!imageUrl) return null;

  const baseTex = await loadPixiTextureWithBgTransparency(imageUrl, meta);
  const frameTex = meta?.frame ? makeFrameTexture(baseTex, meta.frame) : baseTex;
  const sprite = new PIXI.Sprite(frameTex);
  if (!meta?.frame) {
    clampSpriteSize(sprite, 96, 128);
  }
  sprite.scale.set((sprite.scale?.x || 1) * normalizedScale, (sprite.scale?.y || 1) * normalizedScale);
  const origin = normalizeSpriteOrigin(meta);
  sprite.pivot.set(origin.x, origin.y);

  const frames = meta?.animation?.frames;
  if (!Array.isArray(frames) || frames.length <= 1) {
    return { sprite, animTicker: null };
  }
  const animFrames = frames.map((frame) => makeFrameTexture(baseTex, frame));
  const intervalMs = clampNumber((meta?.animation?.speed || 0.5) * 1000, 40, Number.POSITIVE_INFINITY, 500);
  const animTicker = createFrameAnimationTicker(
    sprite,
    animFrames,
    intervalMs,
    meta?.animation?.type || "loop",
  );
  return { sprite, animTicker };
}

/**
 * Prepare walk-animation runtime state for a decorated base sprite.
 * Also initializes the base sprite to its idle frame.
 *
 * @param {PIXI.Sprite} baseSprite Sprite to animate.
 * @param {object|null} decoratorOptions Decorator context (display meta/image).
 * @returns {Promise<object|null>} Walk state object or null when walk animation is unavailable.
 */
async function loadWalkAnimationStateForDecorator(baseSprite, decoratorOptions) {
  const displayMeta = decoratorOptions?.displayMeta;
  const walkAnim = displayMeta?.animations?.walk;
  const walkFrames = walkAnim?.frames;
  if (!Array.isArray(walkFrames) || walkFrames.length <= 1) return null;

  const imageUrl = resolveAssetUrl(decoratorOptions?.displayImage || "");
  if (!imageUrl) return null;

  const baseTex = await loadPixiTextureWithBgTransparency(imageUrl, displayMeta);
  const textures = walkFrames.map((frame) => makeFrameTexture(baseTex, frame));
  if (textures.length <= 1) return null;

  let idleFrameRect = displayMeta?.animations?.front?.frames?.[0] || null;
  if (!idleFrameRect && displayMeta?.animations && typeof displayMeta.animations === "object") {
    const firstAnim = Object.values(displayMeta.animations).find(
      (anim) => Array.isArray(anim?.frames) && anim.frames.length > 0,
    );
    idleFrameRect = firstAnim?.frames?.[0] || null;
  }
  const idleFrame = idleFrameRect
    ? makeFrameTexture(baseTex, idleFrameRect)
    : (displayMeta?.frame ? makeFrameTexture(baseTex, displayMeta.frame) : baseSprite.texture);
  baseSprite.texture = idleFrame;

  return {
    walkFrames: textures,
    idleFrame,
    intervalMs: clampNumber((walkAnim.speed || 0.5) * 1000, 40, Number.POSITIVE_INFINITY, 500),
    elapsedMs: 0,
    frameIndex: 0,
    wasMoving: false,
  };
}

/**
 * Apply decorator effects to a wrapper/sprite pair and return a composed ticker.
 * Supports floating text, sprite overlays, glow, and animation modes.
 *
 * @param {PIXI.Container} wrapper Entity/prop wrapper container.
 * @param {PIXI.Sprite} baseSprite Base sprite to decorate.
 * @param {Array<object>} decorators Raw decorators list.
 * @param {number|null} orientationRadians Optional overlay rotation.
 * @param {object|null} decoratorOptions Optional context for decorator behavior.
 * @returns {Promise<Function|null>} Combined ticker callback or null if no active effect ticker is needed.
 */
async function pixiApplyDecoratorsToWrapper(
  wrapper,
  baseSprite,
  decorators,
  orientationRadians = null,
  decoratorOptions = null,
) {
  const normalized = normalizeObjectArray(decorators);
  const walkWhileMoving = decoratorOptions?.walkWhileMoving === true;
  if (normalized.length === 0 && !walkWhileMoving) return null;

  const spriteDecorators = [];
  const floatingTextDecorators = [];
  let glowConfig = null;
  let animationName = "";

  for (const decorator of normalized) {
    if (decorator.glow && typeof decorator.glow === "object") glowConfig = decorator.glow;
    if (typeof decorator.animation === "string" && decorator.animation.trim()) {
      animationName = decorator.animation.trim().toLowerCase();
    }
    if (decorator.sprite_display && typeof decorator.sprite_display === "object") {
      spriteDecorators.push(decorator);
    }
    if (decorator.floating_text && typeof decorator.floating_text === "object") {
      floatingTextDecorators.push(decorator.floating_text);
    }
  }

  if (floatingTextDecorators.length > 0 && pixiApp) {
    for (const floatingText of floatingTextDecorators) {
      const floatingTextTicker = createFloatingTextDecoratorTicker(
        wrapper,
        baseSprite,
        floatingText,
        () => (wrapper.scale?.x || 1),
      );
      if (floatingTextTicker) pixiApp.ticker.add(floatingTextTicker);
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
    overlay.scale.set(
      (baseSprite.scale?.x || 1) * (overlay.scale?.x || 1),
      (baseSprite.scale?.y || 1) * (overlay.scale?.y || 1),
    );
    if (typeof orientationRadians === "number") {
      overlay.rotation = orientationRadians;
    }
    wrapper.addChild(overlay);
    overlaySprites.push(overlay);
    if (created.animTicker) tickers.push(created.animTicker);
  }

  let glowSprite = null;
  const glowIntensity = clampNumber(glowConfig?.intensity, 0, 1, 0);
  if (glowIntensity > 0) {
    glowSprite = new PIXI.Sprite(baseSprite.texture);
    glowSprite.x = baseSprite.x || 0;
    glowSprite.y = baseSprite.y || 0;
    glowSprite.anchor.set(baseSprite.anchor?.x || 0, baseSprite.anchor?.y || 0);
    glowSprite.rotation = baseSprite.rotation || 0;
    glowSprite.scale.set((baseSprite.scale?.x || 1) * 1.12, (baseSprite.scale?.y || 1) * 1.12);
    glowSprite.tint = parseHexColorInt(glowConfig?.color, 0xffffff);
    glowSprite.alpha = Math.min(0.9, 0.15 + glowIntensity * 0.6);
    glowSprite.blendMode = PIXI.BLEND_MODES.ADD;
    wrapper.addChildAt(glowSprite, 0);
  }

  const baseRotation = baseSprite.rotation || 0;
  const baseScaleX = baseSprite.scale?.x || 1;
  const baseScaleY = baseSprite.scale?.y || 1;
  const animateWalk = walkWhileMoving;
  const animateWobble = animationName === "wobble";
  const animateSpin = animationName === "spin";
  const animatePulse = animationName === "pulse";
  const walkAnimationState = animateWalk
    ? await loadWalkAnimationStateForDecorator(baseSprite, decoratorOptions)
    : null;
  const isMoving = typeof decoratorOptions?.isMoving === "function" ? decoratorOptions.isMoving : () => false;

  if (glowSprite || animateWalk || animateWobble || animateSpin || animatePulse || overlaySprites.length > 0) {
    let elapsed = 0;
    tickers.push((ticker) => {
      elapsed += ticker.deltaMS;
      if (glowSprite) glowSprite.texture = baseSprite.texture;

      if (animateSpin) {
        baseSprite.rotation = baseRotation + ((elapsed * 0.006) % (Math.PI * 2));
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

      if (walkAnimationState) {
        if (!isMoving()) {
          if (walkAnimationState.wasMoving) {
            walkAnimationState.frameIndex = 0;
            walkAnimationState.elapsedMs = 0;
            baseSprite.texture = walkAnimationState.idleFrame;
          }
          walkAnimationState.wasMoving = false;
        } else {
          walkAnimationState.elapsedMs += ticker.deltaMS;
          if (walkAnimationState.elapsedMs >= walkAnimationState.intervalMs) {
            walkAnimationState.elapsedMs = 0;
            walkAnimationState.frameIndex = (walkAnimationState.frameIndex + 1) % walkAnimationState.walkFrames.length;
            baseSprite.texture = walkAnimationState.walkFrames[walkAnimationState.frameIndex];
          } else if (!walkAnimationState.wasMoving) {
            baseSprite.texture = walkAnimationState.walkFrames[walkAnimationState.frameIndex];
          }
          walkAnimationState.wasMoving = true;
        }
      }

      for (const overlay of overlaySprites) {
        overlay.x = baseSprite.x || 0;
        overlay.y = baseSprite.y || 0;
      }
    });
  }

  if (tickers.length === 0) return null;
  return (ticker) => {
    for (const fn of tickers) fn(ticker);
  };
}

/**
 * Attach a transient floating text decorator to an existing rendered entity.
 *
 * @param {"peep"|"object"|"prop"|string} entityType Target entity type.
 * @param {string|number} entityId Target entity id.
 * @param {string} text Floating text content.
 * @param {object|null} options Optional effect config overrides.
 * @returns {boolean} True when a ticker was added; false when target/text/app is unavailable.
 */
function pixiAddFloatingTextToEntity(entityType, entityId, text, options = null) {
  if (!pixiApp) return false;
  const record = pixiEntityNodes.get(`${entityType}:${entityId}`);
  if (!record) return false;
  const message = String(text || "").trim();
  if (!message) return false;

  const tickerFn = createFloatingTextDecoratorTicker(
    record.wrapper,
    record.sprite,
    {
      text: message,
      duration_ms: options?.duration_ms ?? options?.durationMs ?? 1700,
      rise_px: options?.rise_px ?? options?.risePx ?? 20,
      font_size: options?.font_size ?? options?.fontSize ?? 14,
    },
    () => (record.wrapper.scale?.x || 1),
    (completed) => {
      record.transientTickers?.delete(completed);
    },
  );
  if (!tickerFn) return false;

  if (!record.transientTickers) {
    record.transientTickers = new Set();
  }
  record.transientTickers.add(tickerFn);
  pixiApp.ticker.add(tickerFn);
  return true;
}
