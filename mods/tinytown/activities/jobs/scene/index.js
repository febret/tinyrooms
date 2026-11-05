import { drawScene } from "./draw.js";
import { YOU, createSceneModel } from "./model.js";

export { YOU };

const MAX_FRAME_SECONDS = 0.05;

function loadImage(url, onLoad) {
  const image = new Image();
  image.decoding = "async";
  image.onload = () => onLoad(image);
  if (url) image.src = url;
  return image;
}

/**
 * Own the scene canvas: size it, load its pictures, animate the model, and
 * forward pointer picks. Call start() when the run screen is visible.
 */
export function createJobScene({ canvas, reducedMotion = false, seed = 1, onPick = () => {} }) {
  const ctx = canvas.getContext("2d");
  const model = createSceneModel({ seed, reducedMotion });
  const assets = { art: null, sprite: null, figures: new Map(), accent: "#d7795c" };
  const view = { width: 0, height: 0, dpr: 1 };
  let frame = 0;
  let last = 0;
  let running = false;
  let observer = null;

  function measure() {
    const bounds = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.round(bounds.width));
    const height = Math.max(1, Math.round(bounds.height));
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (width === view.width && height === view.height && dpr === view.dpr) return;
    view.width = width;
    view.height = height;
    view.dpr = dpr;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    model.resize(width, height);
  }

  function render() {
    if (!view.width) return;
    drawScene(ctx, model, assets, view);
  }

  function tick(now) {
    if (!running) return;
    const dt = last ? Math.min(MAX_FRAME_SECONDS, (now - last) / 1000) : 0;
    last = now;
    measure();
    model.update(dt);
    render();
    frame = requestAnimationFrame(tick);
  }

  function pointFor(event) {
    const bounds = canvas.getBoundingClientRect();
    return { x: event.clientX - bounds.left, y: event.clientY - bounds.top };
  }

  function onPointerMove(event) {
    const point = pointFor(event);
    const target = model.phase === "pick" ? model.figureAt(point.x, point.y) : null;
    canvas.style.cursor = target ? "pointer" : "";
  }

  function onPointerDown(event) {
    if (model.phase !== "pick") return;
    const point = pointFor(event);
    const target = model.figureAt(point.x, point.y);
    if (target) onPick(target.id);
  }

  canvas.addEventListener("pointermove", onPointerMove);
  canvas.addEventListener("pointerdown", onPointerDown);
  if (typeof ResizeObserver === "function") {
    observer = new ResizeObserver(() => {
      measure();
      render();
    });
    observer.observe(canvas);
  }

  return {
    model,
    start() {
      if (running) return;
      running = true;
      last = 0;
      frame = requestAnimationFrame(tick);
    },
    stop() {
      running = false;
      cancelAnimationFrame(frame);
    },
    destroy() {
      this.stop();
      observer?.disconnect();
      canvas.removeEventListener("pointermove", onPointerMove);
      canvas.removeEventListener("pointerdown", onPointerDown);
    },
    setStep({ artUrl, spriteUrl, accent }) {
      assets.accent = accent || "#d7795c";
      assets.art = loadImage(artUrl, () => render());
      assets.sprite = loadImage(spriteUrl, () => render());
      model.reset();
    },
    // crew: [{ id, name, avatarUrl, used, you }]; the player's id is YOU.
    setCrew(crew) {
      for (const member of crew) {
        if (assets.figures.has(member.id) && assets.figures.get(member.id).dataset.src === member.avatarUrl) continue;
        const image = loadImage(member.avatarUrl, loaded => {
          if (loaded.naturalWidth) model.setAspect(member.id, loaded.naturalWidth / loaded.naturalHeight, loaded.naturalHeight);
          render();
        });
        image.dataset.src = member.avatarUrl || "";
        assets.figures.set(member.id, image);
      }
      model.setCrew(crew);
    },
    get sprite() {
      return assets.sprite;
    },
    render,
  };
}
