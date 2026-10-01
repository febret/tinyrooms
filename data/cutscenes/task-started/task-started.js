import {
  beginCutscene,
  endCutscene,
  wait,
} from "/app/js/cutscenes/stage.js";

const SPARK_COLORS = ["#7ad0c8", "#bff3ee", "#f7d774", "#a1e0ff", "#ffffff"];

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
    const distance = 40 + random() * 120;
    spark.style.setProperty("--spark-x", `${Math.cos(angle) * distance}px`);
    spark.style.setProperty("--spark-y", `${Math.sin(angle) * distance}px`);
    spark.style.setProperty("--spark-delay", `${Math.floor(random() * 260)}ms`);
    spark.style.background = SPARK_COLORS[index % SPARK_COLORS.length];
    host.append(spark);
    window.setTimeout(() => spark.remove(), 1100);
  }
}

export default async function (ctx) {
  const dom = beginCutscene("movie", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
    duration: 700,
  });
  if (!dom) return;

  const random = makeRandom(ctx.params.random);

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
  seal.className = "cutscene-task-seal";
  seal.textContent = "✦";

  const eyebrow = document.createElement("p");
  eyebrow.className = "cutscene-task-eyebrow";
  eyebrow.textContent = "New Journal Task";

  const title = document.createElement("h2");
  title.className = "cutscene-banner";
  title.textContent = String(ctx.params.task_title || ctx.title || "A new task");

  const hint = document.createElement("p");
  hint.className = "cutscene-task-hint";
  hint.textContent = "Added to your journal.";

  card.append(seal, eyebrow, title, hint);
  scene.append(card);
  dom.append(scene);

  card.classList.add("is-dropping");
  await wait(640);
  card.classList.remove("is-dropping");
  card.classList.add("is-landed");
  spawnSparks(scene, random, 18);
  await wait(400);
  card.classList.remove("is-landed");
  spawnSparks(scene, random, 10);
  await wait(1800);
  endCutscene();
}
