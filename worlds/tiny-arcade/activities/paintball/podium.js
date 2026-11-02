const RANKS = [
  { key: "second", place: "second", slot: 1, height: "5.4rem", medal: "2", color: "#c7d0d9" },
  { key: "first", place: "first", slot: 0, height: "8.2rem", medal: "1", color: "#ffd166" },
  { key: "third", place: "third", slot: 2, height: "3.8rem", medal: "3", color: "#e08a4a" },
];

export function renderPodium(root, { top = [], round = 0, seconds = 0, imageFor = () => "", reducedMotion = false } = {}) {
  if (!root) return;
  root.textContent = "";
  const minutes = Math.floor(Math.max(0, Number(seconds) || 0) / 60);
  const remainder = String(Math.max(0, Number(seconds) || 0) % 60).padStart(2, "0");

  const title = document.createElement("h2");
  title.className = "paintball-podium-title";
  title.textContent = `SPLATTER PODIUM — ROUND ${Number(round) || 0}`;
  root.append(title);

  const row = document.createElement("div");
  row.className = "paintball-podium-row";
  root.append(row);

  for (const rank of RANKS) {
    const entry = top.find(candidate => candidate && (candidate.place === rank.place || candidate.rank === rank.place)) || top[rank.slot] || null;
    const url = entry ? imageFor(entry) : "";
    const block = document.createElement("div");
    block.className = "paintball-podium-block";

    if (url) {
      const image = document.createElement("img");
      image.className = "paintball-podium-sprite";
      image.src = url;
      image.alt = entry?.name ? String(entry.name) : rank.medal;
      image.addEventListener("error", () => {
        const placeholder = document.createElement("div");
        placeholder.className = "paintball-podium-empty";
        placeholder.textContent = "?";
        image.replaceWith(placeholder);
      });
      block.append(image);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "paintball-podium-empty";
      placeholder.textContent = "?";
      block.append(placeholder);
    }

    const nameplate = document.createElement("div");
    nameplate.className = "paintball-podium-name";
    nameplate.textContent = entry?.name ? String(entry.name) : "—";
    nameplate.style.color = rank.color;
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
    const hits = Number(entry?.hits || 0);
    score.textContent = `${hits} hit${hits === 1 ? "" : "s"}`;
    step.append(medal, score);
    block.append(step);
    row.append(block);
  }

  const message = document.createElement("p");
  message.className = "paintball-podium-message";
  message.textContent = `Next round in ${minutes}:${remainder}.`;
  root.append(message);

  if (!reducedMotion) {
    const layer = document.createElement("div");
    layer.className = "paintball-confetti";
    layer.setAttribute("aria-hidden", "true");
    for (let index = 0; index < 34; index += 1) {
      const piece = document.createElement("span");
      piece.className = "paintball-confetti-piece";
      piece.style.left = `${(index * 37) % 100}%`;
      piece.style.animationDelay = `${(index % 12) * 90}ms`;
      piece.style.background = ["#ff4d6d", "#4ea8ff", "#5cf29a", "#ffe066", "#c77dff"][index % 5];
      piece.style.setProperty("--drift", `${((index % 7) - 3) * 1.6}rem`);
      layer.append(piece);
    }
    root.append(layer);
  }
}
