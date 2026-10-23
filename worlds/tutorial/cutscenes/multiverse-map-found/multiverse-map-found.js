import {
  beginCutscene,
  cardFace,
  captions,
  endCutscene,
  registerCutsceneFrame,
  sound,
  sprite,
  wait,
} from "../../app/js/cutscenes/stage.js";

registerCutsceneFrame("item-get", {
  cssClass: "cutscene-frame-item-get",
  introMs: 600,
  outroMs: 600,
});

const SPARK_COLORS = ["#ffd76a", "#fff3bf", "#f7b267", "#c9a7ff", "#8ac4db"];

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
    spark.className = "cutscene-map-spark";
    const angle = random() * Math.PI * 2;
    const distance = 70 + random() * 190;
    spark.style.setProperty("--spark-x", `${Math.cos(angle) * distance}px`);
    spark.style.setProperty("--spark-y", `${Math.sin(angle) * distance}px`);
    spark.style.setProperty("--spark-delay", `${Math.floor(random() * 520)}ms`);
    spark.style.setProperty("--spark-size", `${6 + Math.floor(random() * 7)}px`);
    spark.style.background = SPARK_COLORS[index % SPARK_COLORS.length];
    host.append(spark);
    window.setTimeout(() => spark.remove(), 1500);
  }
}

function spawnDebris(host, random, count) {
  const layer = document.createElement("div");
  layer.className = "cutscene-map-debris";
  for (let index = 0; index < count; index += 1) {
    const piece = document.createElement("span");
    piece.className = "cutscene-map-debris-piece";
    piece.style.setProperty("--debris-x", `${-90 + random() * 180}px`);
    piece.style.setProperty("--debris-y", `${-150 - random() * 110}px`);
    piece.style.setProperty("--debris-spin", `${-220 + random() * 440}deg`);
    piece.style.setProperty("--debris-delay", `${Math.floor(random() * 180)}ms`);
    piece.style.background = SPARK_COLORS[index % SPARK_COLORS.length];
    layer.append(piece);
  }
  host.append(layer);
  window.setTimeout(() => layer.remove(), 1600);
}

export default async function (ctx) {
  const dom = beginCutscene("item-get", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
    duration: 520,
  });

  const random = makeRandom(ctx.params.random);
  const scene = document.createElement("div");
  scene.className = "cutscene-map-scene";
  dom.append(scene);

  const rays = document.createElement("div");
  rays.className = "cutscene-item-rays";
  scene.append(rays);

  const rummage = document.createElement("div");
  rummage.className = "cutscene-map-rummage";
  scene.append(rummage);

  const heroRef = typeof ctx.params.me === "string" ? ctx.params.me : "$me";
  const hero = await sprite(heroRef, { label: "You" });
  hero.className = "cutscene-sprite cutscene-map-hero";
  rummage.append(hero);

  const propRef = typeof ctx.params.prop === "string" ? ctx.params.prop : "$prop:garden-trashcan";
  const trashcan = await sprite(propRef, { label: "Trashcan" });
  trashcan.className = "cutscene-sprite cutscene-map-trashcan";
  rummage.append(trashcan);

  const clang = document.createElement("div");
  clang.className = "cutscene-map-clang";
  clang.textContent = "CLANG!";
  scene.append(clang);

  const reveal = document.createElement("div");
  reveal.className = "cutscene-map-reveal";
  scene.append(reveal);

  const glow = document.createElement("div");
  glow.className = "cutscene-item-glow";
  reveal.append(glow);

  const cardRef = typeof ctx.params.card === "string" ? ctx.params.card : "$card:multiverse-map";
  const map = await cardFace(cardRef, { label: "Multiverse Map" });
  map.classList.add("cutscene-map-card");
  reveal.append(map);

  const title = document.createElement("h2");
  title.className = "cutscene-item-title";
  title.innerHTML = "YOU GOT THE<br><span>MULTIVERSE MAP!</span>";
  reveal.append(title);

  const subtitle = document.createElement("p");
  subtitle.className = "cutscene-item-subtitle";
  subtitle.textContent = "Every world. Every door. Try not to lose it.";
  reveal.append(subtitle);

  captions(ctx.text).catch(() => {});

  sound("crunch1.wav");
  await wait(700);
  rummage.classList.add("is-rummaging");
  sound("open-metal.wav");
  await wait(800);
  rummage.classList.add("is-rattling");
  sound("bang-low.wav");
  await wait(500);
  spawnDebris(scene, random, 14);
  clang.classList.add("is-visible");
  sound("gong.wav");
  await wait(400);

  rummage.classList.add("is-done");
  scene.classList.add("is-revealing");
  sound("ring.wav");
  await wait(450);

  sound("task-complete.wav");
  reveal.classList.add("is-revealed");
  spawnSparks(scene, random, 28);
  await wait(1200);

  title.classList.add("is-visible");
  await wait(600);
  subtitle.classList.add("is-visible");
  spawnSparks(scene, random, 18);
  await wait(4150);

  endCutscene();
}
