import {
  beginCutscene,
  endCutscene,
  wait,
} from "/app/js/cutscenes/stage.js";

const CONFETTI_COLORS = ["#f0b429", "#ffe9a8", "#ff8f6b", "#7de07d", "#a1e0ff", "#f2a1ff"];

function makeRandom(seed) {
  let state = (Number(seed) || 1) >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function spawnSparks(host, random, count) {
  for (let index = 0; index < count; index += 1) {
    const spark = document.createElement("span");
    spark.className = "cutscene-pack-spark";
    const angle = random() * Math.PI * 2;
    const distance = 36 + random() * 90;
    spark.style.setProperty("--spark-x", `${Math.cos(angle) * distance}px`);
    spark.style.setProperty("--spark-y", `${Math.sin(angle) * distance}px`);
    spark.style.setProperty("--spark-delay", `${Math.floor(random() * 260)}ms`);
    spark.style.background = CONFETTI_COLORS[index % CONFETTI_COLORS.length];
    host.append(spark);
    window.setTimeout(() => spark.remove(), 1200);
  }
}

export default async function (ctx) {
  const stage = beginCutscene("plain", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
  });
  if (!stage) return;
  stage.classList.add("cutscene-task-toast");

  const random = makeRandom(ctx.params.random);
  const wholeTask = ctx.params.task_complete === true;

  const scene = document.createElement("div");
  scene.className = "cutscene-task-scene";

  const rays = document.createElement("div");
  rays.className = "cutscene-task-rays";
  const halo = document.createElement("div");
  halo.className = "cutscene-task-halo";
  scene.append(rays, halo);

  const card = document.createElement("div");
  card.className = "cutscene-task-card";

  const seal = document.createElement("div");
  seal.className = "cutscene-task-seal is-complete";
  seal.textContent = "✓";

  const body = document.createElement("div");
  body.className = "cutscene-task-body";

  const eyebrow = document.createElement("p");
  eyebrow.className = "cutscene-task-eyebrow";
  eyebrow.textContent = wholeTask ? "Task Complete!" : "Step Complete!";

  const title = document.createElement("h2");
  title.className = "cutscene-task-title";
  const label = wholeTask ? ctx.params.task_title : (ctx.params.step_title || ctx.params.task_title);
  title.textContent = String(label || "");

  const hint = document.createElement("p");
  hint.className = "cutscene-task-hint";
  hint.textContent = "Nice work!";

  body.append(eyebrow, title, hint);
  card.append(seal, body);
  scene.append(card);
  stage.append(scene);

  spawnSparks(scene, random, 18);
  await wait(460);
  card.classList.add("is-landed");
  spawnSparks(scene, random, 10);
  await wait(1500);
  endCutscene();
}
