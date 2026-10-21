import {
  beginCutscene,
  endCutscene,
  registerCutsceneFrame,
  sprite,
  wait,
} from "../../app/js/cutscenes/stage.js";

registerCutsceneFrame("paintball-podium", {
  cssClass: "cutscene-frame-paintball-podium",
  introMs: 560,
  outroMs: 380,
});

const RANKS = [
  { key: "second", step: "second", height: "5.4rem", medal: "2", color: "#c7d0d9" },
  { key: "first", step: "first", height: "8.2rem", medal: "1", color: "#ffd166" },
  { key: "third", step: "third", height: "3.8rem", medal: "3", color: "#e08a4a" },
];

function confetti(stage, count = 34) {
  const layer = document.createElement("div");
  layer.className = "paintball-confetti";
  for (let index = 0; index < count; index += 1) {
    const piece = document.createElement("span");
    piece.className = "paintball-confetti-piece";
    piece.style.left = `${(index * 37) % 100}%`;
    piece.style.animationDelay = `${(index % 12) * 90}ms`;
    piece.style.background = ["#ff4d6d", "#4ea8ff", "#5cf29a", "#ffe066", "#c77dff"][index % 5];
    piece.style.setProperty("--drift", `${((index % 7) - 3) * 1.6}rem`);
    layer.append(piece);
  }
  stage.append(layer);
}

export default async function (ctx) {
  const dom = beginCutscene("paintball-podium", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
  });

  const title = document.createElement("h2");
  title.className = "paintball-podium-title";
  title.textContent = "SPLATTER PODIUM";
  dom.append(title);

  const row = document.createElement("div");
  row.className = "paintball-podium-row";
  dom.append(row);

  for (const rank of RANKS) {
    const token = ctx.params[rank.key];
    const name = ctx.params[`${rank.key}_name`];
    const hits = Number(ctx.params[`${rank.key}_hits`] || 0);

    const block = document.createElement("div");
    block.className = "paintball-podium-block";

    const nameplate = document.createElement("div");
    nameplate.className = "paintball-podium-name";
    nameplate.textContent = name || "—";
    nameplate.style.color = rank.color;

    if (token) {
      const sticker = await sprite(token, { label: name || rank.medal });
      sticker.className = "paintball-podium-sprite";
      block.append(sticker);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "paintball-podium-empty";
      placeholder.textContent = "?";
      block.append(placeholder);
    }

    block.append(nameplate);

    const step = document.createElement("div");
    step.className = "paintball-podium-step";
    step.style.height = rank.height;
    step.style.borderColor = rank.color;
    const medal = document.createElement("span");
    medal.className = "paintball-podium-medal";
    medal.textContent = rank.medal;
    medal.style.color = rank.color;
    const score = document.createElement("span");
    score.className = "paintball-podium-score";
    score.textContent = `${hits} hit${hits === 1 ? "" : "s"}`;
    step.append(medal, score);
    block.append(step);

    row.append(block);
  }

  confetti(dom);
  await wait(4200);
  endCutscene();
}
