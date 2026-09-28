import {
  beginCutscene,
  captions,
  endCutscene,
  sprite,
  wait,
} from "/app/js/cutscenes/stage.js";

const FIREWORK_COLORS = ["#7de07d", "#f7d774", "#8ac4db", "#f28f6b", "#d59cff"];

function makeRandom(seed) {
  let state = (Number(seed) || 1) >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function spawnFireworks(scene, random) {
  const layer = document.createElement("div");
  layer.className = "cutscene-fireworks";
  for (let index = 0; index < 26; index += 1) {
    const spark = document.createElement("span");
    spark.className = "cutscene-firework";
    const angle = random() * Math.PI * 2;
    const distance = 90 + random() * 300;
    spark.style.left = `${10 + random() * 80}%`;
    spark.style.top = `${8 + random() * 60}%`;
    spark.style.setProperty("--fw-x", `${Math.cos(angle) * distance}px`);
    spark.style.setProperty("--fw-y", `${Math.sin(angle) * distance}px`);
    spark.style.setProperty("--fw-delay", `${Math.floor(random() * 900)}ms`);
    spark.style.background = FIREWORK_COLORS[index % FIREWORK_COLORS.length];
    layer.append(spark);
  }
  scene.append(layer);
  return layer;
}

export default async function (ctx) {
  const dom = beginCutscene("letterbox", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
    duration: 520,
  });

  const scene = document.createElement("div");
  scene.className = "cutscene-vacuum-scene";
  dom.append(scene);

  const bugsRef = typeof ctx.params.prop === "string" ? ctx.params.prop : "$prop:bugs0";
  const bugs = await sprite(bugsRef, { label: "House Centipedes" });
  bugs.className = "cutscene-centipede";
  scene.append(bugs);

  const cardRef = typeof ctx.params.card === "string" ? ctx.params.card : "$card:vacuum-cleaner";
  const vacuum = await sprite(cardRef, { label: "Vacuum Cleaner" });
  vacuum.className = "cutscene-vacuum-rig";
  scene.append(vacuum);

  captions(ctx.text);
  await wait(1700);
  scene.classList.add("cutscene-vacuuming");
  await wait(900);
  bugs.classList.add("cutscene-centipede-gone");
  await wait(320);

  const random = makeRandom(ctx.params.random);
  spawnFireworks(scene, random);
  const mission = document.createElement("h2");
  mission.className = "cutscene-mission";
  mission.textContent = "MISSION ACCOMPLISHED";
  scene.append(mission);

  await wait(2400);
  endCutscene();
}
