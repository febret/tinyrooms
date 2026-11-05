import { gameHint } from "./minigames/index.js";
import { CANCELLED_MESSAGE, runMinigame } from "./minigames/runner.js";
import { themeFor } from "./minigames/skin.js";
import { YOU, createJobScene } from "./scene/index.js";
import {
  MAX_HELPERS,
  cycleLabel,
  formatNumber,
  jobStatusLabel,
  outcomeFor,
  signed,
  toggleHelper,
} from "./jobs-model.js";

const state = {
  board: null,
  job: null,
  selectedHelpers: [],
  run: null,
  pendingRun: null,
  pendingOutcome: null,
  lead: null,
  leads: [],
  arena: null,
  busy: false,
  booted: false,
  cycleEndsAt: 0,
  cycleSeconds: 0,
  screen: "board",
};

const shell = document.querySelector("#jobs-shell");
const connection = document.querySelector("#connection");
const screenTitle = document.querySelector("#screen-title");
const energyValue = document.querySelector("#energy-value");
const energyCost = document.querySelector("#energy-cost");
const boardDate = document.querySelector("#board-date");
const boardCount = document.querySelector("#board-count");
const boardCards = document.querySelector("#board-cards");
const resumeBanner = document.querySelector("#resume-banner");
const resumeTitle = document.querySelector("#resume-title");
const resumeGo = document.querySelector("#resume-go");
const resumeLeave = document.querySelector("#resume-leave");
const crewJob = document.querySelector("#crew-job");
const crewHelpers = document.querySelector("#crew-helpers");
const crewNote = document.querySelector("#crew-note");
const crewStart = document.querySelector("#crew-start");
const crewFineprint = document.querySelector("#crew-fineprint");
const crewBack = document.querySelector("#crew-back");
const runStage = document.querySelector("#run-stage");
const runPanel = document.querySelector("#run-panel");
const runCanvas = document.querySelector("#run-scene-canvas");
const runLive = document.querySelector("#run-live");
const runPips = document.querySelector("#run-pips");
const runStepLabel = document.querySelector("#run-step-label");
const runTitle = document.querySelector("#run-title");
const runTask = document.querySelector("#run-task");
const runPicker = document.querySelector("#run-picker");
const runPickLabel = document.querySelector("#run-pick-label");
const runLeadPick = document.querySelector("#run-lead-pick");
const runMeter = document.querySelector("#run-meter");
const runMeterPips = document.querySelector("#run-meter-pips");
const runMeterFit = document.querySelector("#run-meter-fit");
const runStart = document.querySelector("#run-start");
const runApproach = document.querySelector("#run-approach");
const runScore = document.querySelector("#run-score");
const runLog = document.querySelector("#run-log");
const runCrewStatus = document.querySelector("#run-crew-status");
const runGame = document.querySelector("#run-game");
const runGameName = document.querySelector("#run-game-name");
const runGameHint = document.querySelector("#run-game-hint");
const runGameStage = document.querySelector("#run-game-stage");
const runGameCancel = document.querySelector("#run-game-cancel");
const runResult = document.querySelector("#run-result");
const runStamp = document.querySelector("#run-stamp");
const runResultText = document.querySelector("#run-result-text");
const runContinue = document.querySelector("#run-continue");
const runLeave = document.querySelector("#run-leave");
const runQuit = document.querySelector("#run-quit");
const resultArt = document.querySelector("#result-art");
const resultStamp = document.querySelector("#result-stamp");
const resultKicker = document.querySelector("#result-kicker");
const resultTitle = document.querySelector("#result-title");
const resultCopy = document.querySelector("#result-copy");
const resultRewards = document.querySelector("#result-rewards");
const resultHelpers = document.querySelector("#result-helpers");
const resultBack = document.querySelector("#result-back");
const resultClockOut = document.querySelector("#result-clock-out");
const quitDialog = document.querySelector("#quit-dialog");

const escape = value => TinyActivity.escape(value);
const image = value => TinyActivity.image(value);

function errorMessage(error) {
  return error instanceof Error ? error.message : String(error);
}

function setConnection(text = "") {
  connection.textContent = text;
  connection.hidden = !text;
}

function setBusy(value) {
  state.busy = Boolean(value);
  if (state.screen === "crew") renderCrewSelection();
  else crewStart.disabled = state.busy;
  runStart.disabled = state.busy || !state.lead;
}

function show(screen) {
  state.screen = screen;
  shell.dataset.screen = screen;
  for (const name of ["board", "crew", "run", "result"]) {
    document.querySelector(`#screen-${name}`).hidden = name !== screen;
  }
  shell.scrollTop = 0;
  if (screen === "run") scene().start();
  else if (sceneInstance) sceneInstance.stop();
  const titles = {
    board: "Shift Board",
    crew: "Who's coming?",
    run: "On the clock",
    result: "Shift complete",
  };
  screenTitle.textContent = titles[screen] || titles.board;
}

function setArt(element, url) {
  element.onerror = () => { element.hidden = true; };
  if (url) element.src = image(url);
  else element.hidden = true;
}

function showBoardNotice(text) {
  const note = document.createElement("p");
  note.className = "jobs-empty";
  note.textContent = text;
  boardCards.replaceChildren(note);
}

function updateEnergy(value) {
  if (value === undefined || value === null) return;
  energyValue.textContent = formatNumber(Math.round(Number(value)));
}

function syncUser(response) {
  const user = response?.payload?.user || response?.state?.user;
  if (user) updateEnergy(user.shared_energy);
  return user;
}

function renderPips(run) {
  runPips.replaceChildren();
  const pips = run.pips || [];
  for (let index = 0; index < 4; index += 1) {
    const pip = document.createElement("span");
    pip.className = "jobs-pip";
    if (pips[index] === true) pip.classList.add("is-pass");
    else if (pips[index] === false) pip.classList.add("is-fail");
    if (index === run.step?.number - 1) pip.classList.add("is-current");
    pip.title = pips[index] === true ? "Passed" : pips[index] === false ? "Missed" : "Ahead";
    runPips.append(pip);
  }
}

function renderBoard(board) {
  state.board = board;
  show("board");
  updateEnergy(board.energy);
  energyCost.textContent = board.energy_cost ? `${board.energy_cost} per shift` : "No Energy cost";
  state.cycleSeconds = Number(board.cycle?.seconds) || 0;
  state.cycleEndsAt = state.cycleSeconds ? Date.now() + Number(board.cycle.remaining) * 1000 : 0;
  tickCycle();
  boardCount.textContent = `${board.completed_count} of ${board.offers.length} shifts filed`;
  boardCards.replaceChildren();

  resumeBanner.hidden = !board.active_run;
  if (board.active_run) {
    resumeTitle.textContent = board.active_run.job.title;
    resumeGo.onclick = () => resumeShift();
    resumeLeave.onclick = () => TinyActivity.close("cancel");
  }

  if (!board.offers.length) {
    showBoardNotice("The board is empty. The office is pretending this is a holiday.");
    return;
  }

  for (const offer of board.offers) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "jobs-card";
    card.style.setProperty("--accent", offer.accent || "#d7795c");
    card.disabled = offer.status !== "open";
    card.innerHTML = `
      <span class="jobs-card-art">
        <img alt="" loading="lazy" decoding="async">
        <span class="jobs-card-stamp" hidden></span>
      </span>
      <span class="jobs-card-body">
        <span class="jobs-card-profession">${escape(offer.profession)}</span>
        <span class="jobs-card-title">${escape(offer.title)}</span>
        <span class="jobs-card-blurb">${escape(offer.blurb)}</span>
        <span class="jobs-card-meta">4 scenes · 0–3 crew</span>
      </span>
    `;
    const img = card.querySelector("img");
    setArt(img, offer.preview_art);
    if (offer.status !== "open") {
      const stamp = card.querySelector(".jobs-card-stamp");
      stamp.hidden = false;
      stamp.textContent = jobStatusLabel(offer.status);
    }
    card.onclick = () => renderCrew(offer);
    boardCards.append(card);
  }
}

let refreshingForCycle = false;

// The board refreshes with the shared day-night cycle: keep its countdown live and
// pull a fresh board the moment the cycle rolls over.
function tickCycle() {
  if (!state.cycleSeconds) return;
  const remaining = (state.cycleEndsAt - Date.now()) / 1000;
  boardDate.textContent = cycleLabel(remaining, state.cycleSeconds);
  if (remaining > 0 || refreshingForCycle) return;
  if (state.screen === "board" || state.screen === "crew") {
    refreshingForCycle = true;
    if (state.screen === "crew") TinyActivity.toast("The board just refreshed with new shifts.", false);
    refreshBoard().finally(() => {
      refreshingForCycle = false;
    });
  }
}

window.setInterval(tickCycle, 1000);

function renderCrew(job) {
  state.job = job;
  state.selectedHelpers = [];
  show("crew");
  const crew = state.board?.helpers || [];
  crewJob.innerHTML = `
    <img alt="">
    <div class="jobs-crew-job-body">
      <p class="jobs-kicker">${escape(job.profession)}</p>
      <h2>${escape(job.title)}</h2>
      <p>${escape(job.blurb)}</p>
    </div>
  `;
  setArt(crewJob.querySelector("img"), job.preview_art);
  crewHelpers.replaceChildren();
  const condition = state.board?.player_condition;
  const conditionLine = condition
    ? `You: Energy ${condition.energy} · Health ${condition.health} · Clean ${condition.cleanliness}. `
    : "";
  crewNote.textContent = `${conditionLine}${crew.length
    ? "They have to actually like you. You will pick who steps up for each scene."
    : "No roommates are available. A solo shift is still a shift."}`;
  for (const helper of crew) {
    const willing = Boolean(helper.vibe?.willing);
    const label = document.createElement("label");
    label.className = `jobs-helper${willing ? "" : " is-disabled"}`;
    label.innerHTML = `
      <span class="jobs-helper-avatar"><img alt=""></span>
      <span class="jobs-helper-body">
        <span class="jobs-helper-name">${escape(helper.name)}</span>
        <span class="jobs-helper-traits">${escape((helper.traits || []).map(trait => trait.label).join(" · "))}</span>
        <span class="jobs-helper-condition">Energy ${escape(helper.condition?.energy || "—")} · Health ${escape(helper.condition?.health || "—")} · Clean ${escape(helper.condition?.cleanliness || "—")}</span>
      </span>
      <span class="jobs-helper-vibe">${escape(helper.vibe?.label || "Neutral")}${willing ? "" : "<br>Not today"}</span>
    `;
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = helper.id;
    input.disabled = !willing;
    input.setAttribute("aria-label", `Invite ${helper.name}`);
    input.onchange = () => {
      state.selectedHelpers = toggleHelper(state.selectedHelpers, helper.id, MAX_HELPERS);
      if (input.checked && !state.selectedHelpers.includes(helper.id)) {
        input.checked = false;
        TinyActivity.toast(`You can take at most ${MAX_HELPERS} helpers.`, true);
      }
      renderCrewSelection();
    };
    label.prepend(input);
    setArt(label.querySelector("img"), helper.avatar_url);
    crewHelpers.append(label);
  }
  crewStart.textContent = state.board?.energy_cost
    ? `Clock in — ${state.board.energy_cost} Energy`
    : "Clock in";
  crewFineprint.textContent = crew.length
    ? "A cold vibe is a real risk. A warm one is not a guarantee."
    : "Solo jobs are quieter. And cheaper on apologies.";
  renderCrewSelection();
}

function renderCrewSelection() {
  const cost = state.board?.energy_cost || 0;
  const energy = Number(state.board?.energy || 0);
  const tooTired = cost > 0 && energy < cost;
  crewStart.disabled = state.busy || tooTired;
  if (tooTired) {
    crewFineprint.textContent = `You need ${cost} Energy for a full shift. Rest up first.`;
  }
  for (const label of crewHelpers.querySelectorAll(".jobs-helper")) {
    const input = label.querySelector("input");
    if (!input || input.disabled) continue;
    label.classList.toggle("is-selected", input.checked);
  }
}

async function refreshBoard() {
  try {
    const response = await TinyActivity.command(".jobs board");
    const board = response.payload?.board;
    if (!board) throw new Error("The office did not send a board.");
    setConnection("");
    renderBoard(board);
  } catch (error) {
    setConnection(errorMessage(error));
    showBoardNotice("The board could not be read. Try closing and reopening the office.");
  }
}

async function startShift() {
  if (!state.job || state.busy) return;
  setBusy(true);
  try {
    const helpers = state.selectedHelpers.map(id => `@peep:${id}`).join(" ");
    const response = await TinyActivity.command(`.jobs start ${state.job.id}${helpers ? ` ${helpers}` : ""}`);
    syncUser(response);
    if (!response.payload?.run) throw new Error("The shift did not start.");
    state.pendingRun = null;
    state.pendingOutcome = null;
    renderRun(response.payload.run);
    TinyActivity.sound("jobClock");
  } catch (error) {
    TinyActivity.toast(errorMessage(error), true);
    setConnection(errorMessage(error));
  } finally {
    setBusy(false);
  }
}

let activeGame = null;
let sceneInstance = null;

function reducedMotion() {
  return Boolean(TinyActivity.state?.config?.reducedMotion)
    || Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

function scene() {
  if (!sceneInstance) {
    sceneInstance = createJobScene({
      canvas: runCanvas,
      reducedMotion: reducedMotion(),
      seed: Math.floor(Math.random() * 1e6) + 1,
      onPick: id => {
        const lead = state.leads.find(entry => entry.sceneId === id && !entry.used);
        if (lead && !state.busy && state.screen === "run") selectLead(lead);
      },
    });
  }
  return sceneInstance;
}

const sideBySide = window.matchMedia("(min-width: 701px) and (min-aspect-ratio: 6 / 5)");

// In the two-column layout the panel never outgrows the window: drop the
// timesheet first, then the story blurb, before it falls back to scrolling.
function fitPanel(reset = true) {
  const levels = ["is-tight", "is-tighter", "is-compact"];
  if (reset || state.screen !== "run" || !sideBySide.matches) runPanel.classList.remove(...levels);
  if (state.screen !== "run" || !sideBySide.matches) return;
  for (const level of levels) {
    if (runPanel.scrollHeight <= runPanel.clientHeight + 1) return;
    runPanel.classList.add(level);
  }
}

function setPhase(phase) {
  runStage.dataset.phase = phase;
  runLeadPick.hidden = phase !== "pick";
  runGame.hidden = phase !== "play";
  runResult.hidden = phase !== "result";
  fitPanel();
}

function cancelGame() {
  const handle = activeGame;
  activeGame = null;
  if (!handle) return;
  handle.cancel();
  runGameStage.replaceChildren();
  scene().model.reset();
  setPhase("pick");
}

function fitTone(fit) {
  if (!fit) return "";
  if (fit.label === "In their element") return "is-great";
  if (fit.label === "Out of their depth") return "is-hard";
  return "";
}

function renderMeter(fit) {
  runMeter.hidden = !fit;
  if (!fit) return;
  runMeterPips.replaceChildren();
  for (let index = 0; index < 5; index += 1) {
    const pip = document.createElement("i");
    if (index < fit.pips) pip.classList.add("is-on");
    runMeterPips.append(pip);
  }
  runMeterFit.textContent = fit.label;
}

function playerAvatar() {
  const url = TinyActivity.state?.user?.stickerUrl;
  return url ? image(url) : "";
}

function selectLead(lead) {
  state.lead = lead;
  for (const button of runPicker.querySelectorAll(".jobs-pick")) {
    button.setAttribute("aria-checked", String(button.dataset.lead === lead.sceneId));
  }
  scene().model.setLead(lead.sceneId, lead.fit?.label || "", lead.fatigue || 0);
  renderMeter(lead.fit);
  runStart.disabled = state.busy;
  runLive.textContent = `${lead.name} will take this scene.`;
  TinyActivity.sound("tap");
}

function pickCard(lead) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "jobs-pick";
  button.setAttribute("role", "radio");
  button.setAttribute("aria-checked", "false");
  button.dataset.lead = lead.sceneId;
  button.disabled = lead.used;
  if (!lead.used && lead.fatigue >= 0.5) button.classList.add("is-drained");
  const tone = lead.used ? "" : fitTone(lead.fit);
  const chip = lead.used ? "Done" : lead.fit?.label || "";
  button.innerHTML = `
    <span class="jobs-pick-avatar"><img alt=""></span>
    <span class="jobs-pick-body">
      <span class="jobs-pick-name">${escape(lead.name)}</span>
      <span class="jobs-pick-meta">${escape(lead.used ? "Already took a scene this shift" : lead.meta)}</span>
    </span>
    <span class="jobs-pick-fit ${tone}">${escape(chip)}</span>
  `;
  setArt(button.querySelector("img"), lead.avatarUrl);
  button.onclick = () => {
    if (!state.busy) selectLead(lead);
  };
  return button;
}

function leadsFor(run) {
  const leads = (run.helpers || []).map(helper => {
    const traits = (helper.traits || []).map(trait => trait.label).join(" · ");
    return {
      id: helper.id,
      sceneId: helper.id,
      name: helper.name,
      avatarUrl: image(helper.avatar_url),
      fit: helper.fit,
      fatigue: Number(helper.fatigue) || 0,
      used: Boolean(helper.used),
      meta: `${traits} · Energy ${helper.condition?.energy || "—"} · ${helper.vibe?.label || ""}`,
    };
  });
  leads.push({
    id: "",
    sceneId: YOU,
    name: run.player_name || "You",
    avatarUrl: playerAvatar(),
    fit: run.step.you_fit,
    fatigue: Number(run.step.you_fatigue) || 0,
    used: false,
    you: true,
    meta: run.helpers?.length ? "Lead it yourself · no one to blame" : "Lead it yourself",
  });
  return leads;
}

function logRow(index, entry, current) {
  const row = document.createElement("li");
  row.className = "jobs-log-row";
  if (entry) {
    row.classList.add(entry.passed ? "is-pass" : "is-fail");
    row.innerHTML = `
      <span class="jobs-log-num">${index + 1}</span>
      <span class="jobs-log-title">${escape(entry.title)}</span>
      <span class="jobs-log-lead">${escape(entry.lead)}</span>
      <span class="jobs-log-mark" aria-label="${entry.passed ? "Passed" : "Missed"}">${entry.passed ? "✓" : "✗"}</span>
    `;
    return row;
  }
  row.classList.add(current ? "is-current" : "is-ahead");
  row.innerHTML = `
    <span class="jobs-log-num">${index + 1}</span>
    <span class="jobs-log-title">${current ? "On the clock" : "Not yet filed"}</span>
    <span class="jobs-log-lead"></span>
    <span class="jobs-log-mark"></span>
  `;
  return row;
}

function renderLog(run) {
  runLog.replaceChildren();
  const filed = run.log || [];
  for (let index = 0; index < 4; index += 1) {
    runLog.append(logRow(index, filed[index], index === run.step.index));
  }
}

function fileLogRow(result) {
  const index = Number(result.step_index);
  const row = runLog.children[index];
  if (!row || !state.run) return;
  row.replaceWith(logRow(index, {
    title: state.run.step.title,
    passed: Boolean(result.passed),
    lead: result.lead_name || "",
  }));
}

function renderRun(run) {
  cancelGame();
  state.run = run;
  state.lead = null;
  show("run");
  runStepLabel.textContent = `Scene ${run.step.number} of 4 · ${run.job.profession}`;
  runTitle.textContent = run.step.title;
  runTask.textContent = run.step.task;
  renderPips(run);
  renderLog(run);
  setPhase("pick");
  runMeter.hidden = true;
  runStart.disabled = true;
  runLive.textContent = "";
  state.leads = leadsFor(run);
  state.arena = new Image();
  state.arena.src = image(run.step.arena_url);
  const stage = scene();
  stage.setStep({
    artUrl: image(run.step.art_url),
    spriteUrl: image(run.step.sprite_url),
    accent: run.job.accent,
  });
  stage.model.setLead(null);
  stage.setCrew(state.leads.map(lead => ({
    id: lead.sceneId,
    name: lead.name,
    avatarUrl: lead.avatarUrl,
    used: lead.used,
    you: Boolean(lead.you),
  })));
  runPicker.replaceChildren();
  const available = state.leads.filter(lead => !lead.used);
  runPickLabel.textContent = available.length > 1
    ? "Who takes this one?"
    : "Everyone else has had a turn. This one is on you.";
  for (const lead of state.leads) runPicker.append(pickCard(lead));
  if (available.length === 1) selectLead(available[0]);
  fitPanel();
}

async function startChallenge() {
  if (!state.lead || state.busy) return;
  state.busy = true;
  runStart.disabled = true;
  try {
    const response = await TinyActivity.command(
      `.jobs challenge${state.lead.id ? ` @peep:${state.lead.id}` : ""}`,
    );
    const challenge = response.payload?.challenge;
    if (!challenge) throw new Error("The challenge could not start.");
    await playChallenge(challenge);
  } catch (error) {
    if (errorMessage(error) !== CANCELLED_MESSAGE) {
      TinyActivity.toast(errorMessage(error), true);
      scene().model.reset();
      setPhase("pick");
    }
    runStart.disabled = false;
  } finally {
    state.busy = false;
  }
}

async function playChallenge(challenge) {
  const stage = scene();
  const params = challenge.params;
  setPhase("play");
  runGameName.textContent = `${challenge.lead.name} steps up`;
  runGameHint.textContent = gameHint(challenge.game);
  const theme = themeFor(state.run?.job?.id);
  runGame.style.setProperty("--game-good", theme.good);
  runGame.style.setProperty("--game-deep", theme.deep);
  stage.model.begin({
    required: params.required,
    total: params.max_score,
    difficulty: params.difficulty,
    fatigue: params.fatigue,
  });
  runGame.scrollIntoView({ block: "nearest" });
  if (stage.sprite?.decode) await stage.sprite.decode().catch(() => {});
  if (state.arena?.decode) await state.arena.decode().catch(() => {});
  const handle = runMinigame({
    host: runGameStage,
    gameId: challenge.game,
    params,
    sprite: stage.sprite,
    theme,
    arena: state.arena,
    reducedMotion: reducedMotion(),
    onResult: result => {
      TinyActivity.sound(result === "hit" ? "coin" : "error");
      if (result === "hit") stage.model.hit();
      else stage.model.miss();
    },
    onPhase: (name, detail) => {
      if (name === "play") stage.model.go();
      else if (name === "done") stage.model.finish(detail.score >= params.required);
    },
  });
  activeGame = handle;
  const outcome = await handle.promise;
  activeGame = null;
  const response = await TinyActivity.command(
    `.jobs resolve ${challenge.id} ${outcome.score} ${Math.max(1, outcome.elapsedMs)}`,
  );
  syncUser(response);
  showStepResult(response.payload || {});
}

function renderCrewStatus(run) {
  runCrewStatus.replaceChildren();
  for (const helper of run?.helpers || []) {
    const chip = document.createElement("span");
    chip.className = `jobs-crew-chip${helper.used ? " is-done" : ""}`;
    chip.innerHTML = `
      <img alt="">
      <span>${escape(helper.name)}<small>${escape(helper.used ? "Done" : "Ready")} · Energy ${escape(helper.condition?.energy || "—")}</small></span>
    `;
    setArt(chip.querySelector("img"), helper.avatar_url);
    runCrewStatus.append(chip);
  }
}

function showStepResult(payload) {
  const result = payload.result || {};
  const stage = scene();
  state.pendingRun = payload.run || null;
  state.pendingOutcome = payload.outcome || null;
  runGameStage.replaceChildren();
  setPhase("result");
  if (stage.model.phase !== (result.passed ? "win" : "lose")) stage.model.finish(Boolean(result.passed));
  fileLogRow(result);
  renderCrewStatus(payload.run);
  runStamp.classList.toggle("is-fail", !result.passed);
  runStamp.textContent = result.passed ? "Nailed it" : "Fumbled";
  runScore.textContent = Number.isFinite(result.score)
    ? `${result.score} of ${result.total || result.required} · needed ${result.required}`
    : "";
  runApproach.textContent = result.lead_name && result.approach
    ? `How ${result.lead_name} tackled it: ${result.approach}`
    : "";
  runResultText.textContent = result.text || "The office is not saying.";
  runLive.textContent = `${result.passed ? "Nailed it" : "Fumbled"}. ${result.text || ""}`;
  runContinue.textContent = state.pendingOutcome ? "See the damage" : "Continue";
  fitPanel();
  TinyActivity.sound(result.passed ? "jobPass" : "jobFail");
}

function continueRun() {
  if (state.pendingOutcome) {
    showOutcome(state.pendingOutcome);
    return;
  }
  if (state.pendingRun) {
    renderRun(state.pendingRun);
    return;
  }
  refreshBoard();
}

async function resumeShift() {
  try {
    const response = await TinyActivity.command(".jobs resume");
    if (!response.payload?.run) throw new Error("That shift could not be resumed.");
    renderRun(response.payload.run);
    TinyActivity.sound("jobPage");
  } catch (error) {
    TinyActivity.toast(errorMessage(error), true);
    refreshBoard();
  }
}

function showOutcome(outcome) {
  show("result");
  const band = outcomeFor(outcome.steps_passed);
  resultKicker.textContent = `${outcome.job?.title || "Shift"} · ${outcome.abandoned ? "abandoned" : "complete"}`;
  resultStamp.textContent = band.stamp;
  resultTitle.textContent = band.label;
  resultCopy.textContent = outcome.ending;
  setArt(resultArt, outcome.art_url);
  resultRewards.replaceChildren();
  const bops = Number(outcome.bops || 0);
  const vibe = Number(outcome.vibe_delta || 0);
  const rewards = [
    { label: "Bops", value: signed(bops), negative: bops < 0 },
    { label: "Scenes passed", value: `${outcome.steps_passed} / 4`, negative: false },
  ];
  if (outcome.helpers?.length) {
    rewards.splice(1, 0, {
      label: "Vibes each",
      value: vibe === 0 ? "No change" : signed(vibe),
      negative: vibe < 0,
    });
  }
  for (const entry of rewards) {
    const box = document.createElement("div");
    box.className = `jobs-reward${entry.negative ? " is-negative" : ""}`;
    box.innerHTML = `<span>${escape(entry.label)}</span><strong>${escape(entry.value)}</strong>`;
    resultRewards.append(box);
  }
  resultHelpers.replaceChildren();
  for (const helper of outcome.helpers || []) {
    const row = document.createElement("div");
    row.className = "jobs-result-helper";
    row.innerHTML = `
      <img alt="">
      <span><strong>${escape(helper.name)}</strong> · ${escape(helper.vibe_label)} · ${escape(signed(helper.vibe_delta))} vibes</span>
    `;
    setArt(row.querySelector("img"), helper.avatar_url);
    resultHelpers.append(row);
  }
  if (!outcome.helpers?.length) {
    const row = document.createElement("div");
    row.className = "jobs-result-helper";
    row.textContent = "No roommates came along. The office filed a solo report.";
    resultHelpers.append(row);
  }
  TinyActivity.sound("jobStamp");
  window.setTimeout(() => {
    TinyActivity.sound(outcome.steps_passed > 0 ? "jobWin" : "jobLose");
    if (outcome.bops > 0) TinyActivity.sound("jobPay");
  }, 260);
}

async function quitShift() {
  cancelGame();
  try {
    const response = await TinyActivity.command(".jobs quit");
    syncUser(response);
    const outcome = response.payload?.outcome;
    if (!outcome) throw new Error("The shift could not be closed.");
    showOutcome(outcome);
  } catch (error) {
    TinyActivity.toast(errorMessage(error), true);
  }
}

if (typeof ResizeObserver === "function") {
  new ResizeObserver(() => fitPanel()).observe(runStage);
  new ResizeObserver(() => fitPanel(false)).observe(runGame);
}

crewBack.onclick = () => refreshBoard();
crewStart.onclick = () => startShift();
runStart.onclick = () => startChallenge();
runGameCancel.onclick = () => cancelGame();
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && activeGame) cancelGame();
});
runLeave.onclick = () => {
  cancelGame();
  refreshBoard();
};
runContinue.onclick = () => continueRun();
resultBack.onclick = () => refreshBoard();
resultClockOut.onclick = () => TinyActivity.close("complete");
runQuit.onclick = () => {
  cancelGame();
  if (typeof quitDialog.showModal === "function") quitDialog.showModal();
  else if (window.confirm("Quit this shift and lock in the current result?")) quitShift();
};
quitDialog.addEventListener("close", () => {
  if (quitDialog.returnValue === "quit") quitShift();
});

function boot() {
  if (state.booted) return;
  state.booted = true;
  void refreshBoard();
}

TinyActivity.subscribe(host => {
  if (host?.user) updateEnergy(host.user.shared_energy);
  boot();
});

window.setTimeout(boot, 900);
