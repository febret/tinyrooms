import { checkSafecrack, generateSafecrack } from "./puzzle.js";

const sequenceRoot = document.querySelector("#sequence");
const padRoot = document.querySelector("#pad");
const timerBadge = document.querySelector("#timer");
const status = document.querySelector("#status");
const connection = document.querySelector("#connection");
const replayButton = document.querySelector("#replay");
const clearButton = document.querySelector("#clear");

let puzzle = generateSafecrack("tiny-vault", 2);
let timeLimit = 60;
let startedAt = Date.now();
let attempt = [];
let showing = false;
let finished = false;
let timer = 0;

function activityConfig() {
  const state = window.TinyActivity ? window.TinyActivity.state : null;
  return state?.activity?.config || {};
}

function resetFromConfig() {
  const config = activityConfig();
  puzzle = generateSafecrack(config.seed || "tiny-vault", config.difficulty || 2);
  timeLimit = Number(config.time_limit_seconds || 60);
  startedAt = Date.now();
  attempt = [];
  finished = false;
  render();
  void replay();
}

function elapsedSeconds() {
  return (Date.now() - startedAt) / 1000;
}

function render() {
  sequenceRoot.textContent = "";
  puzzle.sequence.forEach((symbol, index) => {
    const cell = document.createElement("div");
    cell.className = "crack-tumbler";
    cell.textContent = attempt[index] === symbol ? symbol : `${index + 1}`;
    if (attempt[index] === symbol) cell.classList.add("lit");
    sequenceRoot.append(cell);
  });
  padRoot.textContent = "";
  for (const symbol of puzzle.symbols) {
    const key = document.createElement("button");
    key.type = "button";
    key.className = "crack-tumbler";
    key.textContent = symbol;
    key.disabled = finished;
    key.onclick = () => press(symbol);
    padRoot.append(key);
  }
}

function sleep(ms) {
  return new Promise(resolve => window.setTimeout(resolve, ms));
}

async function replay() {
  if (!window.TinyActivity || showing || finished) return;
  showing = true;
  const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  for (const symbol of puzzle.sequence) {
    status.textContent = reduced ? `Next click: ${symbol}` : "Listen…";
    window.TinyActivity.sound("click");
    await sleep(reduced ? 650 : 420);
  }
  status.textContent = "Your turn. Repeat the clicks in order.";
  showing = false;
}

async function report(solved) {
  finished = true;
  render();
  if (!window.TinyActivity) return;
  try {
    const response = await window.TinyActivity.command(
      `.heist safecrack_result symbols=${attempt.join(",")} time=${elapsedSeconds().toFixed(1)}`
    );
    status.textContent = response?.message || "The vault decides.";
    if (solved) {
      window.TinyActivity.celebrate();
      window.TinyActivity.close("complete");
    }
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : String(error);
    finished = false;
    render();
  }
}

function press(symbol) {
  if (finished || showing) return;
  attempt.push(symbol);
  const check = checkSafecrack(puzzle.sequence, attempt);
  render();
  if (check.ok) {
    status.textContent = "Clicks aligned. Sending the result…";
    void report(true);
  } else if (attempt.length >= puzzle.sequence.length || check.placed < attempt.length) {
    status.textContent = "Wrong click. The tumblers reset.";
    window.TinyActivity?.toast("Wrong click. The tumblers reset.", true);
    attempt = [];
    render();
  }
}

replayButton.onclick = () => void replay();
clearButton.onclick = () => {
  attempt = [];
  render();
};

timer = window.setInterval(() => {
  const remaining = Math.max(0, timeLimit - elapsedSeconds());
  timerBadge.textContent = `${remaining.toFixed(0)}s left`;
  if (remaining <= 0 && !finished) {
    window.clearInterval(timer);
    status.textContent = "Out of time. The drill overheats.";
    void report(false);
  }
}, 250);

if (window.TinyActivity) {
  window.TinyActivity.subscribe(() => {
    if (connection.textContent) {
      connection.textContent = "";
      resetFromConfig();
    }
  });
  resetFromConfig();
} else {
  connection.textContent = "Open this activity from Tinyrooms.";
  render();
}
