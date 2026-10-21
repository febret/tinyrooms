// Shared, data-driven topic cutscene engine for Scammon Academia lessons.
//
// Every topic scene is a tiny module that imports this engine with a unique
// recipe (background, accent, glyph set, motion, and caption). The recipe
// drives distinct visuals and animation, so each card still gets its own
// cutscene while the animation plumbing lives in one trusted module.

import { beginCutscene, endCutscene, sprite, wait } from "../../app/js/cutscenes/stage.js";

const MOTIONS = new Set(["rise", "rain", "orbit", "pop", "sweep"]);

function el(tag, className, styles = {}) {
  const node = document.createElement(tag);
  node.className = className;
  Object.assign(node.style, styles);
  return node;
}

function floatingGlyphs(stage, recipe) {
  const layer = el("div", "topic-glyph-layer", {
    position: "absolute",
    inset: "0",
    overflow: "hidden",
    pointerEvents: "none",
  });
  const glyphs = Array.isArray(recipe.glyphs) && recipe.glyphs.length ? recipe.glyphs : [recipe.emoji || "★"];
  const count = 16;
  for (let index = 0; index < count; index += 1) {
    const glyph = el("span", "topic-glyph", {
      position: "absolute",
      fontSize: `${(1.4 + (index % 4) * 0.5).toFixed(2)}rem`,
      opacity: "0",
    });
    glyph.textContent = glyphs[index % glyphs.length];
    layer.append(glyph);

    const motion = MOTIONS.has(recipe.motion) ? recipe.motion : "rise";
    const delay = index * 90;
    const duration = 1500 + (index % 5) * 220;
    let keyframes;
    const jitter = () => 8 + Math.random() * 84;
    if (motion === "rain") {
      glyph.style.left = `${jitter()}%`;
      keyframes = [
        { transform: "translateY(-40px) rotate(0deg)", opacity: 0 },
        { transform: "translateY(52vh) rotate(180deg)", opacity: 0.9 },
      ];
    } else if (motion === "sweep") {
      glyph.style.top = `${jitter()}%`;
      keyframes = [
        { transform: "translateX(-60px)", opacity: 0 },
        { transform: "translateX(60vw)", opacity: 0.9 },
      ];
    } else if (motion === "pop") {
      glyph.style.left = `${jitter()}%`;
      glyph.style.top = `${jitter()}%`;
      keyframes = [
        { transform: "scale(0.2)", opacity: 0 },
        { transform: "scale(1.1)", opacity: 1, offset: 0.6 },
        { transform: "scale(0.9)", opacity: 0 },
      ];
    } else if (motion === "orbit") {
      glyph.style.left = "50%";
      glyph.style.top = "50%";
      const angle = (Math.PI * 2 * index) / count;
      keyframes = [
        { transform: `translate(-50%,-50%) rotate(0deg) translateX(0px)`, opacity: 0 },
        { transform: `translate(-50%,-50%) rotate(${angle}rad) translateX(24vmin)`, opacity: 0.95 },
      ];
    } else {
      glyph.style.left = `${jitter()}%`;
      glyph.style.bottom = "-20px";
      keyframes = [
        { transform: "translateY(0) scale(0.8)", opacity: 0 },
        { transform: "translateY(-58vh) scale(1.1)", opacity: 0.9 },
      ];
    }
    glyph.animate(keyframes, { duration, delay, easing: "ease-out", fill: "forwards" });
  }
  stage.append(layer);
}

function heroGlyph(layer, recipe) {
  const hero = el("div", "topic-hero", {
    position: "absolute",
    inset: "0",
    display: "grid",
    placeItems: "center",
    fontSize: "5.5rem",
    filter: "drop-shadow(0 10px 18px rgba(0,0,0,0.35))",
  });
  hero.textContent = recipe.emoji || "★";
  layer.append(hero);
  hero.animate(
    [
      { transform: "scale(0.3) rotate(-12deg)", opacity: 0 },
      { transform: "scale(1.18) rotate(6deg)", opacity: 1, offset: 0.55 },
      { transform: "scale(1) rotate(0deg)", opacity: 1 },
    ],
    { duration: 900, easing: "cubic-bezier(.2,1.4,.4,1)", fill: "forwards" },
  );
  return hero;
}

function framedSprite(className, art, styles) {
  const frame = el("div", className, {
    position: "absolute",
    display: "grid",
    placeItems: "center",
    overflow: "hidden",
    pointerEvents: "none",
    zIndex: "2",
    ...styles,
  });
  frame.append(art);
  return frame;
}

async function featuredCast(scene, recipe) {
  const teacherRef = typeof recipe.teacher === "string" ? recipe.teacher : "";
  const cardRef = typeof recipe.topic_card === "string" ? recipe.topic_card : "";
  if (!teacherRef && !cardRef) return;

  const accent = recipe.accent || "#f4c430";
  const [teacherArt, cardArt] = await Promise.all([
    teacherRef ? sprite(teacherRef, { label: "Teacher" }) : null,
    cardRef ? sprite(cardRef, { label: recipe.title || "Lesson topic" }) : null,
  ]);

  if (teacherArt) {
    const badge = framedSprite("topic-teacher", teacherArt, {
      top: "clamp(12px, 4vmin, 40px)",
      left: "clamp(12px, 4vmin, 40px)",
      width: "clamp(72px, 15vmin, 132px)",
      aspectRatio: "1",
      padding: "clamp(5px, 1.2vmin, 10px)",
      border: `4px solid ${accent}`,
      borderRadius: "50%",
      background: "rgba(255,255,255,0.94)",
      boxShadow: "0 14px 32px rgba(0,0,0,0.4)",
      transform: "rotate(-6deg)",
    });
    scene.append(badge);
    badge.animate(
      [
        { transform: "translateX(-150%) rotate(-18deg)", opacity: 0 },
        { transform: "translateX(0) rotate(-6deg)", opacity: 1 },
      ],
      { duration: 620, delay: 180, easing: "cubic-bezier(.2,1.35,.4,1)", fill: "forwards" },
    );
  }

  if (cardArt) {
    const panel = framedSprite("topic-card-art", cardArt, {
      right: "clamp(12px, 4vmin, 44px)",
      top: "50%",
      width: "clamp(110px, 24vmin, 220px)",
      aspectRatio: "1",
      padding: "clamp(5px, 1.2vmin, 10px)",
      border: `3px solid ${accent}`,
      borderRadius: "16px",
      background: "rgba(255,255,255,0.96)",
      boxShadow: "0 18px 38px rgba(0,0,0,0.42)",
      transform: "translateY(-50%) rotate(5deg)",
    });
    scene.append(panel);
    panel.animate(
      [
        { transform: "translate(140%, -50%) rotate(16deg)", opacity: 0 },
        { transform: "translate(0, -50%) rotate(5deg)", opacity: 1 },
      ],
      { duration: 680, delay: 320, easing: "cubic-bezier(.2,1.3,.4,1)", fill: "forwards" },
    );
  }
}

export async function runTopicScene(ctx, recipe) {
  const safe = recipe || {};
  const duration = Math.min(5000, Math.max(2000, Number(safe.duration) || 3000));
  const stage = beginCutscene("movie", {
    background: safe.bg || "#0b2545",
    accent: safe.accent || "#f4c430",
    duration: 650,
  });

  const scene = el("div", "topic-scene", {
    position: "absolute",
    inset: "0",
    background: `radial-gradient(circle at 50% 35%, ${safe.accent || "#f4c430"}22, ${safe.bg || "#0b2545"} 70%)`,
  });
  stage.append(scene);

  floatingGlyphs(scene, safe);
  const hero = heroGlyph(scene, safe);
  await featuredCast(scene, safe);

  const caption = el("p", "topic-caption", {
    position: "absolute",
    left: "50%",
    bottom: "10%",
    transform: "translateX(-50%)",
    margin: "0",
    padding: "0.35rem 0.9rem",
    borderRadius: "999px",
    background: "rgba(0,0,0,0.45)",
    color: safe.accent || "#f4c430",
    font: "600 1.05rem/1.4 system-ui, sans-serif",
    letterSpacing: "0.01em",
    textAlign: "center",
    maxWidth: "86%",
    opacity: "0",
    zIndex: "3",
  });
  caption.textContent = safe.line || "";
  scene.append(caption);
  caption.animate(
    [{ opacity: 0, transform: "translateX(-50%) translateY(10px)" }, { opacity: 1, transform: "translateX(-50%) translateY(0)" }],
    { duration: 420, delay: 350, easing: "ease-out", fill: "forwards" },
  );

  // A short hero flourish near the end keeps every scene lively.
  await wait(Math.max(400, duration - 1100));
  hero.animate(
    [
      { transform: "scale(1) rotate(0deg)" },
      { transform: "scale(1.3) rotate(10deg)", offset: 0.5 },
      { transform: "scale(1.05) rotate(-4deg)" },
    ],
    { duration: 700, easing: "ease-in-out", fill: "forwards" },
  );
  await wait(700);
  endCutscene();
}
