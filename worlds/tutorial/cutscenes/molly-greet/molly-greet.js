import {
  beginCutscene,
  captions,
  endCutscene,
  sprite,
  wait,
} from "/app/js/cutscenes/stage.js";

const HEART_GLYPHS = ["❤️", "💖", "💕", "💗", "💓", "💞"];
const DEFAULT_PEEP = "$peep:molly";

function burstHearts(dom, count = 20) {
  const burst = document.createElement("div");
  burst.className = "cutscene-hearts";
  for (let index = 0; index < count; index += 1) {
    const heart = document.createElement("span");
    heart.className = "cutscene-heart";
    heart.textContent = HEART_GLYPHS[index % HEART_GLYPHS.length];
    const angle = (Math.PI * 2 * index) / count - Math.PI / 2;
    const distance = 26 + (index % 4) * 7;
    heart.style.setProperty("--heart-x", `${(Math.cos(angle) * distance).toFixed(2)}vmin`);
    heart.style.setProperty("--heart-y", `${(Math.sin(angle) * distance).toFixed(2)}vmin`);
    heart.style.setProperty("--heart-delay", `${(index % 5) * 45}ms`);
    heart.style.setProperty("--heart-scale", `${(0.85 + (index % 4) * 0.2).toFixed(2)}`);
    heart.style.setProperty("--heart-rotate", `${(index % 2 ? 1 : -1) * 18}deg`);
    burst.append(heart);
  }
  dom.append(burst);
  return burst;
}

export default async function (ctx) {
  const dom = beginCutscene("movie", {
    background: ctx.params.stage_background,
    duration: 700,
  });

  const couple = document.createElement("div");
  couple.className = "cutscene-couple";

  const me = await sprite("$me");
  me.className = "cutscene-sprite cutscene-sprite-me";

  const peepRef = typeof ctx.params.peep === "string" ? ctx.params.peep : DEFAULT_PEEP;
  const peep = await sprite(peepRef, { label: "Molly" });
  peep.className = "cutscene-sprite cutscene-sprite-peep";

  couple.append(me, peep);
  dom.append(couple);

  const line = document.createElement("p");
  line.className = "cutscene-line";
  line.style.color = ctx.params.caption_color || "#f7f5ed";
  line.textContent = `${ctx.params.source_name || "Someone"} steps closer.`;
  dom.append(line);

  await wait(1200);
  line.remove();

  couple.classList.add("cutscene-couple-meet");
  await wait(760);
  burstHearts(dom);

  await captions(ctx.text);
  await wait(400);
  endCutscene();
}
