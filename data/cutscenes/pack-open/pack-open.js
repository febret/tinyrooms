import {
  beginCutscene,
  endCutscene,
  sprite,
  wait,
} from "/app/js/cutscenes/stage.js";

const RARITY_CLASS = {
  common: "is-common",
  uncommon: "is-uncommon",
  rare: "is-rare",
  epic: "is-epic",
  legendary: "is-legendary",
};

const SPARK_COLORS = ["#f7d774", "#fff2c2", "#f2a1ff", "#8ac4db", "#7de07d"];
const RARITY_RANK = { common: 0, uncommon: 1, rare: 2, epic: 3, legendary: 4 };

function makeRandom(seed) {
  let state = (Number(seed) || 1) >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function rarityClass(rarity) {
  return RARITY_CLASS[String(rarity || "").toLowerCase()] || RARITY_CLASS.common;
}

function spawnSparks(host, random, count) {
  for (let index = 0; index < count; index += 1) {
    const spark = document.createElement("span");
    spark.className = "cutscene-pack-spark";
    const angle = random() * Math.PI * 2;
    const distance = 40 + random() * 90;
    spark.style.setProperty("--spark-x", `${Math.cos(angle) * distance}px`);
    spark.style.setProperty("--spark-y", `${Math.sin(angle) * distance}px`);
    spark.style.setProperty("--spark-delay", `${Math.floor(random() * 260)}ms`);
    spark.style.background = SPARK_COLORS[index % SPARK_COLORS.length];
    host.append(spark);
    window.setTimeout(() => spark.remove(), 1000);
  }
}

export default async function (ctx) {
  const dom = beginCutscene("movie", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
  });

  const random = makeRandom(ctx.params.random);
  const scene = document.createElement("div");
  scene.className = "cutscene-pack-scene";
  dom.append(scene);

  const title = document.createElement("h2");
  title.className = "cutscene-pack-title";
  title.textContent = String(ctx.params.pack_label || "Card Pack");
  scene.append(title);

  const burst = document.createElement("div");
  burst.className = "cutscene-pack-burst";
  scene.append(burst);

  const pack = document.createElement("div");
  pack.className = "cutscene-pack";
  const packRef = typeof ctx.params.pack_art === "string" ? ctx.params.pack_art : "";
  const packArt = packRef ? await sprite(packRef, { label: "Card pack" }) : null;
  if (packArt) {
    packArt.className = "cutscene-pack-face";
    pack.append(packArt);
  }
  const seam = document.createElement("span");
  seam.className = "cutscene-pack-seam";
  pack.append(seam);
  scene.append(pack);

  const cards = document.createElement("div");
  cards.className = "cutscene-pack-cards";
  scene.append(cards);

  const draws = [];
  for (let index = 1; index <= 3; index += 1) {
    const ref = ctx.params[`card${index}`];
    if (typeof ref !== "string") continue;
    draws.push({ ref, rarity: String(ctx.params[`rarity${index}`] || "Common") });
  }
  // Reveal lowest rarity first so the best pull lands last.
  draws.sort((left, right) => (RARITY_RANK[left.rarity.toLowerCase()] ?? 0) - (RARITY_RANK[right.rarity.toLowerCase()] ?? 0));

  const slots = [];
  for (let index = 0; index < draws.length; index += 1) {
    const { ref, rarity } = draws[index];
    const slot = document.createElement("div");
    slot.className = `cutscene-pack-slot ${rarityClass(rarity)}`;
    slot.style.setProperty("--slot-index", String(index));
    const flipper = document.createElement("div");
    flipper.className = "cutscene-pack-flipper";
    const back = document.createElement("div");
    back.className = "cutscene-pack-card-back";
    const front = document.createElement("div");
    front.className = "cutscene-pack-card-front";
    const cardSprite = await sprite(ref, { label: rarity });
    if (cardSprite) front.append(cardSprite);
    flipper.append(back, front);
    slot.append(flipper);
    const label = document.createElement("span");
    label.className = "cutscene-pack-rarity";
    label.textContent = rarity;
    slot.append(label);
    cards.append(slot);
    slots.push(slot);
  }

  pack.classList.add("is-dropping");
  await wait(640);
  pack.classList.remove("is-dropping");
  pack.classList.add("is-shaking");
  await wait(900);
  pack.classList.remove("is-shaking");
  pack.classList.add("is-tearing");
  burst.classList.add("is-active");
  await wait(620);

  pack.classList.add("is-gone");
  scene.classList.add("is-open");
  for (const slot of slots) {
    slot.classList.add("is-dealt");
    await wait(200);
  }
  await wait(360);
  for (const slot of slots) {
    slot.classList.add("is-flipped");
    const legendary = slot.classList.contains("is-legendary");
    const epic = slot.classList.contains("is-epic");
    if (legendary) spawnSparks(slot, random, 22);
    else if (epic) spawnSparks(slot, random, 12);
    else if (slot.classList.contains("is-rare")) spawnSparks(slot, random, 6);
    await wait(legendary ? 900 : 640);
  }
  await wait(1500);
  endCutscene();
}
