// Hacker Collective controller: boot, megacorp board, blueprint, netmap,
// maths nodes, and the reused reflex minigames.

import { blipClass, createFx, scrambleTo, typeLines } from "./fx.js";
import { createAudio } from "./audio.js";
import { createBlueprint } from "./blueprint.js";
import { createNetmap } from "./netmap.js";
import { renderEduScreen } from "./edu.js";
import { createHackSkin, drawCrtOverlay } from "./hack-skin.js";
import { tokenPainter } from "./tokens.js";
import { CANCELLED_MESSAGE, runMinigame } from "../jobs/minigames/runner.js";
import { gameHint } from "../jobs/minigames/index.js";
import {
  answerPairs,
  formatClock,
  nextOpenIndex,
  nodeKindLabel,
  paletteStyle,
  pickLine,
  screenState,
} from "./hacker-model.js";

const $ = id => document.getElementById(id);

const ui = {
  shell: $("hack-shell"),
  connection: $("connection"),
  topPath: $("top-path"),
  statusCorp: $("status-corp"),
  statusTimer: $("status-timer"),
  statusBops: $("status-bops"),
  screens: {
    boot: $("screen-boot"),
    corps: $("screen-corps"),
    floors: $("screen-floors"),
    map: $("screen-map"),
    node: $("screen-node"),
    result: $("screen-result"),
  },
  bootLog: $("boot-log"),
  bootGo: $("boot-go"),
  bootHint: $("boot-hint"),
  corpsGrid: $("corp-grid"),
  corpsNote: $("corps-note"),
  resumeBanner: $("resume-banner"),
  resumeTitle: $("resume-title"),
  resumeGo: $("resume-go"),
  resumeAbandon: $("resume-abandon"),
  floorsBack: $("floors-back"),
  floorsCorp: $("floors-corp"),
  floorsTitle: $("floors-title"),
  floorsNote: $("floors-note"),
  floorCanvas: $("floor-canvas"),
  floorList: $("floor-list"),
  crewHelpers: $("crew-helpers"),
  crewNote: $("crew-note"),
  crewStart: $("crew-start"),
  crewFineprint: $("crew-fineprint"),
  mapCanvas: $("map-canvas"),
  mapFloor: $("map-floor"),
  mapTitle: $("map-title"),
  mapCount: $("map-count"),
  mapLive: $("map-live"),
  mapBrief: $("map-brief"),
  mapNodes: $("map-nodes"),
  mapHelper: $("map-helper"),
  mapLeave: $("map-leave"),
  mapAbandon: $("map-abandon"),
  nodeKind: $("node-kind"),
  nodeTitle: $("node-title"),
  nodeStepper: $("node-stepper"),
  nodeFeedback: $("node-feedback"),
  nodeExit: $("node-exit"),
  nodeComments: $("node-comments"),
  nodeCommentAvatar: $("node-comment-avatar"),
  nodeCommentName: $("node-comment-name"),
  nodeCommentText: $("node-comment-text"),
  eduStage: $("edu-stage"),
  gameStage: $("game-stage"),
  resultKicker: $("result-kicker"),
  resultTitle: $("result-title"),
  resultText: $("result-text"),
  resultStats: $("result-stats"),
  resultProps: $("result-props"),
  resultHelper: $("result-helper"),
  resultAgain: $("result-again"),
  resultClose: $("result-close"),
  fx: $("fx-canvas"),
};

const state = {
  board: null,
  corp: null,
  floorLevel: 1,
  helperId: "",
  run: null,
  screenHandle: null,
  gameHandle: null,
  nodeId: "",
  clock: 0,
  deadline: 0,
  lineSeed: 0,
  streak: 0,
  lowtime: false,
  drained: false,
  tipTimer: 0,
  tipIndex: 0,
  isBusy: false,
  audio: null,
  fx: null,
  netmap: null,
  blueprint: null,
  booted: false,
};

const prefersReduced = () =>
  Boolean(TinyActivity.state?.config?.reducedMotion) ||
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ||
  false;

const soundEnabled = () => TinyActivity.state?.config?.soundEnabled !== false;

function setupEffects() {
  state.audio = createAudio(soundEnabled);
  state.fx = createFx(ui.fx, { reducedMotion: prefersReduced() });
  state.netmap = createNetmap({
    canvas: ui.mapCanvas,
    reducedMotion: prefersReduced(),
    onPick: id => openNode(id),
  });
  state.blueprint = createBlueprint({ canvas: ui.floorCanvas, reducedMotion: prefersReduced() });
}

// -- shared UI helpers ------------------------------------------------------

function make(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function image(url, alt) {
  const node = new Image();
  const source = TinyActivity.image(url);
  if (source) node.src = source;
  node.alt = alt || "";
  node.loading = "lazy";
  return node;
}

function show(name) {
  for (const [key, section] of Object.entries(ui.screens)) {
    section.hidden = key !== name;
  }
  const paths = {
    boot: "/ access terminal",
    corps: "/ target board",
    floors: "/ building blueprint",
    map: "/ netmap",
    node: "/ node intrusion",
    result: "/ connection closed",
  };
  ui.topPath.textContent = paths[name] || "";
  if (name !== "map") state.netmap.stop();
  if (name !== "floors") state.blueprint.stop();
}

function setStatus({ corp = null, timer = null, bops = null }) {
  if (corp !== null) ui.statusCorp.textContent = corp || "NO TARGET";
  if (timer !== null) {
    ui.statusTimer.hidden = timer === "";
    if (timer !== "") ui.statusTimer.textContent = timer;
  }
  if (bops !== null) {
    ui.statusBops.hidden = bops === "";
    if (bops !== "") ui.statusBops.textContent = `${bops} BOPS`;
  }
}

function setPalette(corp) {
  if (!corp?.palette) return;
  const style = paletteStyle(corp.palette);
  for (const [key, value] of Object.entries(style)) {
    document.documentElement.style.setProperty(key, value);
  }
  const backdrop = corp.background_url ? TinyActivity.image(corp.background_url) : "";
  document.documentElement.style.setProperty("--corp-bg", backdrop ? `url("${backdrop}")` : "none");
}

function feedback(text, error = false) {
  ui.nodeFeedback.textContent = text;
  ui.nodeFeedback.classList.toggle("error", error);
}

function showComment(text, { tip = false } = {}) {
  if (!state.run?.helper) return;
  ui.nodeComments.hidden = false;
  ui.nodeComments.classList.toggle("tip", tip);
  ui.nodeCommentName.textContent = tip ? `${state.run.helper.name} · TIP` : state.run.helper.name;
  ui.nodeCommentText.textContent = text;
}

function say(event) {
  const line = pickLine(state.run?.banter, event, state.lineSeed);
  state.lineSeed += 1;
  if (line) showComment(line);
  return line;
}

function stopTips() {
  window.clearInterval(state.tipTimer);
  state.tipTimer = 0;
  state.tipIndex = 0;
}

function startTips(active) {
  stopTips();
  const tips = active?.tips || [];
  if (!state.run?.helper || !tips.length) return;
  state.tipTimer = window.setInterval(() => {
    if (!state.run?.helper) return;
    const tip = tips[state.tipIndex % tips.length];
    state.tipIndex += 1;
    showComment(tip, { tip: true });
  }, 8_000);
}

function renderComments(run) {
  stopTips();
  ui.nodeComments.classList.remove("tip");
  if (!run.helper) {
    ui.nodeComments.hidden = true;
    return;
  }
  const source = TinyActivity.image(run.helper.avatar_url);
  if (source) {
    ui.nodeCommentAvatar.src = source;
    ui.nodeCommentAvatar.hidden = false;
  } else {
    ui.nodeCommentAvatar.hidden = true;
  }
  ui.nodeComments.hidden = false;
  ui.nodeCommentName.textContent = run.helper.name;
  ui.nodeCommentText.textContent = pickLine(run.banter, "greet", state.lineSeed) || "Let's go.";
  state.lineSeed += 1;
}

// -- clock ------------------------------------------------------------------

function startClock(remainingMs) {
  stopClock();
  state.deadline = performance.now() + Math.max(0, Number(remainingMs) || 0);
  const tick = () => {
    const remaining = state.deadline - performance.now();
    const text = formatClock(remaining);
    setStatus({ timer: text });
    ui.statusTimer.classList.toggle("urgent", remaining <= 5 * 60 * 1000);
    if (!state.lowtime && remaining <= 5 * 60 * 1000) {
      state.lowtime = true;
      const line = pickLine(state.run?.banter, "lowtime", state.lineSeed);
      state.lineSeed += 1;
      if (line) TinyActivity.toast(line);
    }
    if (remaining <= 0) {
      stopClock();
      setStatus({ timer: "00:00" });
      ui.mapLive.textContent = "CONNECTION LOST. The tower has closed.";
      state.clock = 0;
      TinyActivity.toast("Thirty minutes are up. The tower closed the connection.", true);
      window.setTimeout(() => {
        if (state.run) void leaveToCorps();
      }, 1500);
    }
  };
  state.clock = window.setInterval(tick, 250);
  tick();
}

function stopClock() {
  window.clearInterval(state.clock);
  state.clock = 0;
  ui.statusTimer.classList.remove("urgent");
}

// -- boot -------------------------------------------------------------------

const BOOT_LINES = [
  "relay handshake ................ ok",
  "quantum checksum ............... ok",
  "scanning local towers .......... 5 found",
  "grade 01 link: NIBBLE INDUSTRIES // open",
  "grade 05 link: TERAFORGE CORP // open",
  "grades 02-04 ................... sealed",
  "HACKER COLLECTIVE online",
];

async function bootSequence() {
  ui.bootGo.disabled = false;
  const done = typeLines(ui.bootLog, BOOT_LINES, { speed: 14, reducedMotion: prefersReduced() });
  done.then(() => {
    ui.bootHint.textContent = "Press connect to continue.";
  });
}

async function finishBoot() {
  if (state.booted) return;
  state.booted = true;
  state.audio?.blip("open");
  try {
    await refreshBoard();
  } catch (error) {
    ui.connection.textContent = error.message || "Could not reach the target board.";
  }
  show("corps");
}

async function refreshBoard() {
  const response = await TinyActivity.command(".hack board");
  state.board = response.payload.board;
  renderCorps();
  renderResume();
  return state.board;
}

function renderResume() {
  const active = state.board?.active_run;
  ui.resumeBanner.hidden = !active;
  if (!active) return;
  const corp = state.board.corps.find(entry => entry.id === active.corp_id);
  ui.resumeTitle.textContent = `${corp?.title || active.corp_id} — floor ${active.floor} — ${active.cleared} nodes clean — ${formatClock(active.remaining_ms)} left`;
}

function renderCorps() {
  ui.corpsGrid.replaceChildren();
  for (const corp of state.board?.corps || []) {
    const card = make("button", `corp-card${corp.playable ? "" : " sealed"}`);
    card.type = "button";
    card.style.setProperty("--ph", corp.palette.phosphor);
    card.style.setProperty("--ph-soft", `${corp.palette.phosphor}33`);
    card.style.setProperty("--ph-line", `${corp.palette.phosphor}66`);
    card.style.setProperty("--accent", corp.palette.accent);
    const cardBackdrop = TinyActivity.image(corp.background_url);
    if (cardBackdrop) card.style.setProperty("--card-bg", `url("${cardBackdrop}")`);
    card.setAttribute("aria-disabled", String(!corp.playable));
    card.setAttribute("aria-label", `${corp.title}, grade ${corp.grade}, ${corp.playable ? "open" : "sealed"}`);
    const logo = image(corp.logo_url, `${corp.title} logo`);
    logo.className = "corp-logo";
    card.append(logo);
    card.append(make("span", "corp-grade", `GRADE ${corp.grade}`));
    card.append(make("h2", "corp-title", corp.title));
    card.append(make("p", "corp-tagline", corp.tagline));
    card.append(make("p", "corp-topic", corp.topic));
    const foot = make("div", "corp-foot");
    const openFloors = corp.floors.filter(floor => !floor.locked).map(floor => floor.level);
    const open = openFloors.length ? `FLOOR ${openFloors.join("/")} OPEN` : "SEALED";
    foot.append(make("span", "", open));
    const floors = make("div", "corp-floors");
    for (const floor of corp.floors) {
      const bar = make("span", "corp-floor");
      if (!floor.locked) bar.classList.add("lit");
      floors.append(bar);
    }
    foot.append(floors);
    card.append(foot);
    card.addEventListener("click", () => {
      if (!corp.playable) {
        state.audio?.blip("bad");
        state.fx?.glitch(corp.palette.phosphor, 1.2);
        blipClass(card);
        ui.corpsNote.textContent = `${corp.title} answers only after grade ${corp.grade} is unlocked.`;
        return;
      }
      state.audio?.blip("open");
      selectCorp(corp);
    });
    ui.corpsGrid.append(card);
  }
}

function selectedFloor() {
  return state.corp?.floors.find(floor => floor.level === state.floorLevel)
    || state.corp?.open_floor
    || null;
}

function selectCorp(corp) {
  state.corp = corp;
  state.helperId = "";
  state.floorLevel = corp.open_floor?.level || 1;
  setPalette(corp);
  setStatus({ corp: corp.title, timer: "", bops: "" });
  ui.floorsCorp.textContent = `GRADE ${corp.grade} — ${corp.title}`;
  ui.floorsTitle.textContent = corp.open_floor?.title || "Blueprint";
  ui.floorsNote.textContent = corp.blurb;
  state.blueprint.setCorp(corp);
  state.blueprint.setFloor(state.floorLevel);
  renderFloorList();
  renderHelpers();
  show("floors");
  state.blueprint.start();
}

function renderFloorList() {
  ui.floorList.replaceChildren();
  for (const floor of state.corp?.floors || []) {
    const row = make("button", "floor-row");
    row.type = "button";
    row.disabled = Boolean(floor.locked);
    row.classList.toggle("selected", floor.level === state.floorLevel);
    row.append(make("span", "fr-level", `F${String(floor.level).padStart(2, "0")}`));
    const copy = make("span");
    copy.append(make("span", "fr-title", floor.title));
    copy.append(make("span", "fr-sub", floor.topic));
    row.append(copy);
    row.append(make("span", "fr-state", floor.available ? `OPEN · ${floor.nodes}N` : "LOCKED"));
    row.addEventListener("click", () => {
      if (floor.locked) return;
      state.floorLevel = floor.level;
      state.audio?.blip("key");
      state.blueprint.setFloor(floor.level);
      ui.floorsTitle.textContent = floor.title;
      ui.floorsNote.textContent = `${floor.topic}. ${floor.nodes} nodes.`;
      for (const entry of ui.floorList.querySelectorAll(".floor-row")) entry.classList.remove("selected");
      row.classList.add("selected");
      renderHelpers();
    });
    ui.floorList.append(row);
  }
}

function renderHelpers() {
  ui.crewHelpers.replaceChildren();
  const solo = make("button", "helper-card solo-card");
  solo.type = "button";
  solo.classList.toggle("selected", state.helperId === "");
  const soloBody = make("div", "helper-body");
  soloBody.append(make("span", "helper-name", "GO ALONE"));
  soloBody.append(make("span", "helper-meta", "No support. The reflex challenges stay exactly as they are."));
  solo.append(soloBody);
  solo.addEventListener("click", () => {
    state.helperId = "";
    renderHelpers();
    state.audio?.blip("key");
  });
  ui.crewHelpers.append(solo);

  for (const helper of state.board?.helpers || []) {
    const card = make("button", "helper-card");
    card.type = "button";
    card.classList.toggle("selected", state.helperId === helper.id);
    card.append(image(helper.avatar_url, helper.name));
    const body = make("div", "helper-body");
    body.append(make("span", "helper-name", helper.name));
    const traits = (helper.traits || []).slice(0, 2).map(trait => trait.label).join(", ");
    body.append(make("span", "helper-meta", traits || "No strong leanings"));
    body.append(make("span", "helper-meta", `Energy: ${helper.condition.energy}`));
    body.append(make("span", "helper-meta", `Vibe: ${helper.vibe.label}${helper.vibe.willing ? "" : " (unwilling)"}`));
    card.append(body);
    card.addEventListener("click", () => {
      state.helperId = helper.id;
      renderHelpers();
      state.audio?.blip("key");
      ui.crewFineprint.textContent = helper.vibe.willing
        ? `${helper.name} will shift the reflex challenges only. The maths never changes.`
        : `${helper.name} is not willing right now. They may refuse to join.`;
    });
    ui.crewHelpers.append(card);
  }

  const floor = selectedFloor();
  ui.crewStart.textContent = floor ? `JACK IN — FLOOR ${floor.level} · ${floor.nodes} NODES` : "JACK IN";
  ui.crewFineprint.textContent = state.helperId
    ? "A roommate shifts reflex difficulty, reaction lines, and end-of-floor vibes."
    : "Solo runs are always allowed. Nothing is lost.";
}

async function jackIn() {
  if (!state.corp || state.isBusy) return;
  state.isBusy = true;
  ui.crewStart.disabled = true;
  ui.crewStart.textContent = "CONNECTING...";
  let started = null;
  try {
    const suffix = state.helperId ? ` @peep:${state.helperId}` : "";
    const response = await TinyActivity.command(`.hack start ${state.corp.id} ${state.floorLevel}${suffix}`);
    started = response.payload.run;
    state.audio?.blip("open");
    state.fx?.glitch(state.corp.palette.phosphor, 0.6);
  } catch (error) {
    TinyActivity.toast(error.message || "Could not start that hack.", true);
    state.audio?.blip("bad");
  } finally {
    state.isBusy = false;
    ui.crewStart.disabled = false;
    renderHelpers();
  }
  if (started) applyRun(started);
}

// -- map --------------------------------------------------------------------

function applyRun(run) {
  if (!run) return;
  if (run.run_id !== state.run?.run_id) {
    state.streak = 0;
    state.lowtime = false;
    state.drained = false;
  }
  state.run = run;
  setPalette(run.corp);
  setStatus({ corp: `${run.corp.title}`, timer: formatClock(run.remaining_ms), bops: run.bops });
  startClock(run.remaining_ms);
  renderMap(run);
  show("map");
  state.netmap.start();
}

function renderMap(run) {
  ui.mapFloor.textContent = `FLOOR ${run.floor.level} — ${run.floor.title}`;
  ui.mapTitle.textContent = run.corp.title;
  ui.mapCount.textContent = `${run.cleared.filter(id => id !== "central").length} / ${run.nodes.length} nodes clean · ${run.bops} Bops`;
  ui.mapLive.textContent = "";
  const nodePay = run.nodes[0]?.payout || { min: 0, max: 0 };
  const corePay = run.central?.payout || { min: 0, max: 0, kudos: 0, props: 0 };
  const brief = make("div");
  brief.append(make("strong", "", run.floor.topic));
  brief.append(make("p", "", `Each node pays ${nodePay.min}–${nodePay.max} Bops from your reflex score. The core pays ${corePay.min}–${corePay.max} Bops, ${corePay.kudos} Kudos, and ${corePay.props} props.`));
  ui.mapBrief.replaceChildren(brief);
  state.netmap.setRun(run);
  renderNodeList(run);
  ui.mapNodes.scrollTop = 0;
  renderMapHelper(run);
}

function payoutLabel(entry) {
  const payout = entry.payout || { min: 0, max: 0 };
  if (entry.status === "cleared") return `${entry.earned_bops || 0} Bops paid`;
  return `${payout.min}–${payout.max} Bops`;
}

function renderNodeList(run) {
  ui.mapNodes.replaceChildren();
  for (const node of run.nodes) {
    const row = make("button", `node-row ${node.status}`);
    row.type = "button";
    row.disabled = node.status !== "open";
    row.setAttribute("role", "listitem");
    const copy = make("span");
    copy.append(make("span", "nr-label", `${node.label} · ${node.name}`));
    copy.append(make("span", "nr-sub", `${node.fit.label} · ${payoutLabel(node)}`));
    row.append(copy, make("span", "nr-state", node.status === "cleared" ? "CLEAN" : node.status === "open" ? "OPEN" : "LOCKED"));
    row.addEventListener("click", () => {
      if (node.status === "open") openNode(node.id);
    });
    ui.mapNodes.append(row);
  }
  const central = run.central;
  const row = make("button", `node-row central ${central.status}`);
  row.type = "button";
  row.disabled = central.status !== "open";
  const copy = make("span");
  copy.append(make("span", "nr-label", "CORE · CENTRAL SERVER"));
  copy.append(make("span", "nr-sub", `${central.fit.label} · ${central.payout.min}–${central.payout.max} Bops + ${central.payout.kudos} Kudos`));
  row.append(copy, make("span", "nr-state", central.status === "open" ? "READY" : central.status === "cleared" ? "CLEAN" : "LOCKED"));
  row.addEventListener("click", () => {
    if (central.status === "open") openNode("central");
  });
  ui.mapNodes.append(row);
}

function renderMapHelper(run) {
  ui.mapHelper.replaceChildren();
  if (!run.helper) {
    ui.mapHelper.classList.add("solo");
    ui.mapHelper.textContent = "SOLO RUN — no roommate support";
    return;
  }
  ui.mapHelper.classList.remove("solo");
  ui.mapHelper.append(image(run.helper.avatar_url, run.helper.name));
  const body = make("div", "hs-body");
  body.append(make("strong", "", run.helper.name));
  body.append(make("span", "", `Energy: ${run.helper.condition.energy}`));
  body.append(make("span", "", `Vibe: ${run.helper.vibe.label}`));
  ui.mapHelper.append(body);
}

async function openNode(nodeId) {
  if (state.isBusy) return;
  state.isBusy = true;
  try {
    const response = await TinyActivity.command(`.hack enter ${nodeId}`);
    state.audio?.blip("open");
    state.fx?.glitch(state.run?.corp?.palette?.phosphor, 0.5);
    state.run = response.payload.run;
    state.nodeId = nodeId;
    renderNode();
    show("node");
  } catch (error) {
    console.warn("[hacker] could not open node", error);
    TinyActivity.toast(error.message || "That node would not open.", true);
    state.audio?.blip("bad");
  } finally {
    state.isBusy = false;
  }
}

// -- node screen ------------------------------------------------------------

function cleanupNodeScreen() {
  stopTips();
  state.screenHandle?.destroy?.();
  state.screenHandle = null;
  state.gameHandle?.cancel?.();
  state.gameHandle = null;
  ui.gameStage.replaceChildren();
  ui.gameStage.hidden = true;
  ui.eduStage.hidden = false;
}

function renderNode() {
  cleanupNodeScreen();
  const run = state.run;
  const active = run?.active;
  if (!active) {
    show("map");
    state.netmap.start();
    return;
  }
  const central = active.id === "central";
  const node = central ? run.central : run.nodes.find(entry => entry.id === active.id);
  ui.nodeKind.textContent = central ? "CENTRAL SERVER" : `${nodeKindLabel(node.kind)} · ${node.label}`;
  ui.nodeTitle.textContent = central ? "THE CORE" : node.name;
  feedback("");
  renderStepper(active.screens);
  renderComments(run);
  if (!state.drained && run.helper && Number(run.helper.fatigue) >= 0.5) {
    state.drained = true;
    window.setTimeout(() => say("drain"), 400);
  }

  if (active.challenge) {
    renderChallengeReady(active.challenge, "CHALLENGE RESUMED");
    return;
  }
  if (active.ready) {
    renderChallengeReady(null, "FIREWALL READY");
    return;
  }
  const index = nextOpenIndex(active.screens);
  if (index < 0) {
    renderChallengeReady(null, "FIREWALL READY");
    return;
  }
  const screen = active.screens[index];
  state.screenHandle = renderEduScreen(ui.eduStage, screen, {
    reducedMotion: prefersReduced(),
    audio: state.audio,
    onSolved: (answers, elapsed) => submitAnswer(screen, answers, elapsed),
    onTimeout: elapsed => submitTimeout(screen, elapsed),
    onWrong: () => {
      feedback("Not quite. Look again.", true);
      say("wrong");
    },
  });
  state.screenHandle?.focus?.();
  startTips(active);
}

function renderStepper(screens) {
  ui.nodeStepper.replaceChildren();
  const index = nextOpenIndex(screens);
  screens.forEach((screen, position) => {
    const dot = make("span", "step-dot");
    if (screen.passed) dot.classList.add("done");
    else if (position === index) dot.classList.add("live");
    ui.nodeStepper.append(dot);
  });
}

function renderChallengeReady(challenge, title) {
  ui.eduStage.replaceChildren();
  const wrap = make("div", "edu-body");
  wrap.append(make("h2", "", title));
  const run = state.run;
  const helperLine = run.helper
    ? `${run.helper.name} is ${run.helper.condition.energy.toLowerCase()} and ready.`
    : "No roommate. Pure nerve.";
  const hint = challenge ? gameHint(challenge.game) : "Decrypt the maths, then run the node's reflex challenge.";
  const payout = run.active?.payout || { min: 0, max: 0 };
  const rewardLine = run.active?.id === "central"
    ? `Payout: ${payout.min}–${payout.max} Bops, ${payout.kudos} Kudos, and ${payout.props} props.`
    : `Payout: ${payout.min}–${payout.max} Bops.`;
  wrap.append(make("p", "edu-brief", `${helperLine} ${hint}`));
  wrap.append(make("p", "edu-brief", `${rewardLine} The challenge always succeeds; your score sets the size.`));
  const actions = make("div", "edu-actions");
  const start = make("button", "hack-btn primary", challenge ? "RESUME CHALLENGE" : "RUN REFLEX CHALLENGE");
  start.type = "button";
  start.addEventListener("click", () => beginChallenge(challenge));
  actions.append(start);
  wrap.append(actions);
  ui.eduStage.append(wrap);
  say("central");
}

async function submitAnswer(screen, answers, elapsed) {
  if (state.isBusy) return;
  state.isBusy = true;
  feedback("UPLOADING...");
  try {
    const pairs = answerPairs(answers);
    const response = await TinyActivity.command(`.hack answer ${screen.id} ${Math.round(elapsed)} ${pairs}`);
    state.run = response.payload.run;
    const passed = response.payload.result.passed;
    const streak = passed ? state.streak + 1 : 0;
    if (passed) {
      state.streak = streak;
      state.audio?.blip("good");
      state.fx?.burst(window.innerWidth * 0.5, window.innerHeight * 0.42, state.run.corp.palette.phosphor, 14);
    } else {
      state.audio?.blip("bad");
    }
    renderNode();
    feedback(passed ? "DECRYPTED. Line is green." : "The server disagrees. Re-check the line.", !passed);
    if (passed) say(streak % 3 === 0 ? "streak" : "correct");
    else say("wrong");
  } catch (error) {
    feedback(error.message || "That answer was rejected.", true);
    TinyActivity.toast(error.message || "That answer was rejected.", true);
    state.audio?.blip("bad");
  } finally {
    state.isBusy = false;
  }
}

async function submitTimeout(screen, elapsed) {
  if (state.isBusy) return;
  state.isBusy = true;
  feedback("TIME OUT. Reseating the packets...");
  state.audio?.blip("bad");
  try {
    const response = await TinyActivity.command(`.hack answer ${screen.id} ${Math.round(elapsed + 500)} timeout=1`);
    state.run = response.payload.run;
    say("timeout");
    renderNode();
  } catch (error) {
    feedback(error.message || "The screen refused to reset.", true);
  } finally {
    state.isBusy = false;
  }
}

async function beginChallenge(existing) {
  const run = state.run;
  if (!run?.active || state.isBusy) return;
  let challenge = existing;
  if (!challenge) {
    state.isBusy = true;
    try {
      const response = await TinyActivity.command(".hack challenge");
      challenge = response.payload.challenge;
      state.run = response.payload.run;
    } catch (error) {
      console.warn("[hacker] challenge failed", error);
      feedback(error.message || "That challenge is not ready.", true);
      TinyActivity.toast(error.message || "That challenge is not ready.", true);
      return;
    } finally {
      state.isBusy = false;
    }
  }
  await runChallenge(challenge);
}

async function runChallenge(challenge) {
  const run = state.run;
  const active = run?.active;
  if (!active) return;
  const central = active.id === "central";
  const node = central ? run.central : run.nodes.find(entry => entry.id === active.id);
  const kind = central ? "core" : node.kind;
  ui.eduStage.hidden = true;
  ui.gameStage.hidden = false;
  ui.gameStage.replaceChildren();
  feedback("CONNECTING TO THE FIREWALL...");
  const arena = challenge.arena_url ? image(challenge.arena_url, "") : null;
  const skin = createHackSkin(state.run.corp.palette);
  const sprite = tokenPainter(kind, state.run.corp.palette);
  let lastOutcome = null;
  state.gameHandle = runMinigame({
    host: ui.gameStage,
    gameId: challenge.game,
    params: challenge.params,
    sprite,
    skin,
    arena,
    reducedMotion: prefersReduced(),
    onResult: outcome => {
      lastOutcome = outcome;
      state.audio?.blip(outcome === "hit" ? "good" : "bad");
    },
    onPhase: (phase, detail) => {
      if (phase === "done") feedback(`Challenge complete: ${detail?.score ?? ""}`);
    },
    overlay: (ctx, detail) => drawCrtOverlay(ctx, detail),
  });
  feedback(`REFLEX CHALLENGE — ${gameHint(challenge.game)}`);
  try {
    const { score, elapsedMs } = await state.gameHandle.promise;
    state.gameHandle = null;
    await resolveChallenge(challenge, score, elapsedMs, lastOutcome);
  } catch (error) {
    state.gameHandle = null;
    if (error?.message === CANCELLED_MESSAGE) {
      feedback("Challenge cancelled.");
      renderNode();
      return;
    }
    console.warn("[hacker] challenge crashed", error);
    feedback(error?.message || "The challenge failed to start.", true);
  }
}

async function resolveChallenge(challenge, score, elapsedMs, lastOutcome) {
  if (state.isBusy) return;
  state.isBusy = true;
  try {
    const response = await TinyActivity.command(
      `.hack resolve ${challenge.node_id} ${challenge.id} ${score} ${Math.round(elapsedMs)}`,
    );
    state.run = response.payload.run;
    const result = response.payload.result;
    if (result.passed) {
      state.audio?.blip(result.central ? "core" : "node");
      state.fx?.glitch(state.run?.corp?.palette?.phosphor || "#4bff7e", 1.4);
      state.fx?.burst(window.innerWidth * 0.5, window.innerHeight * 0.45, state.run?.corp?.palette?.phosphor || "#4bff7e", 36);
      if (response.payload.outcome) {
        showResult(response.payload.outcome);
        return;
      }
      say("nodewin");
      if (result.paid) {
        TinyActivity.toast(`Node clean. +${result.bops} Bops.`);
      } else {
        TinyActivity.toast("Node clean. This floor already paid out this cycle.");
      }
      state.run = response.payload.run;
      applyRun(state.run);
      return;
    }
    state.audio?.blip("fail");
    say("nodelose");
    const message = result.text || "The node holds. The maths is safe. Try the challenge again.";
    if (state.run) {
      renderNode();
      show("node");
      feedback(message, true);
    }
  } catch (error) {
    feedback(error.message || "That challenge result was rejected.", true);
    TinyActivity.toast(error.message || "That challenge result was rejected.", true);
    if (lastOutcome === "miss") state.audio?.blip("bad");
  } finally {
    state.isBusy = false;
  }
}

// -- result -----------------------------------------------------------------

function showResult(outcome) {
  stopClock();
  cleanupNodeScreen();
  ui.resultKicker.textContent = outcome.abandoned ? "Link severed" : "Connection closed";
  ui.resultTitle.textContent = outcome.abandoned ? "ACCESS REVOKED" : "ACCESS GRANTED";
  ui.resultTitle.dataset.text = ui.resultTitle.textContent;
  blipClass(ui.resultTitle, "glitching", 700);
  ui.resultText.textContent = outcome.abandoned
    ? "You backed out. The tower logs the attempt and keeps the maths."
    : `Floor ${outcome.floor} of ${outcome.corp_id.toUpperCase()} is yours. ${outcome.cleared} nodes cleaned.`;
  ui.resultStats.replaceChildren();
  const stats = [
    ["BOPS", outcome.bops ?? 0],
    ["KUDOS", outcome.kudos ?? 0],
    ["NODES", outcome.cleared ?? 0],
    ["PROPS", (outcome.props || []).length],
  ];
  for (const [label, value] of stats) {
    const stat = make("div", "result-stat");
    stat.append(make("strong", "", String(value)), make("span", "", label));
    ui.resultStats.append(stat);
  }
  ui.resultProps.replaceChildren();
  for (const prop of outcome.props || []) {
    ui.resultProps.append(make("span", "result-prop", `UNLOCKED: ${prop.label}`));
  }
  ui.resultHelper.replaceChildren();
  if (outcome.helper) {
    ui.resultHelper.append(image(outcome.helper.avatar_url, outcome.helper.name));
    ui.resultHelper.append(make("span", "", `${outcome.helper.name} · ${outcome.helper.vibe_label} (${outcome.helper.vibe_delta >= 0 ? "+" : ""}${outcome.helper.vibe_delta})`));
  }
  if (!outcome.abandoned && !outcome.bops && !outcome.kudos) {
    ui.resultProps.append(make("span", "result-prop", "Rewards already collected this cycle."));
  }
  setStatus({ timer: "", bops: "" });
  show("result");
  state.fx?.burst(window.innerWidth * 0.5, window.innerHeight * 0.4, state.run?.corp?.palette?.phosphor || "#4bff7e", 48);
  state.run = null;
}

async function leaveToCorps() {
  stopClock();
  cleanupNodeScreen();
  state.blueprint.stop();
  show("corps");
  try {
    await refreshBoard();
  } catch (error) {
    ui.connection.textContent = error.message || "";
  }
}

async function exitNode() {
  stopTips();
  state.gameHandle?.cancel?.();
  state.gameHandle = null;
  state.screenHandle?.destroy?.();
  state.screenHandle = null;
  if (state.isBusy) {
    window.setTimeout(() => void exitNode(), 250);
    return;
  }
  state.isBusy = true;
  let run = null;
  try {
    const response = await TinyActivity.command(".hack leave");
    run = response.payload.run;
    state.audio?.blip("close");
  } catch (error) {
    TinyActivity.toast(error.message || "Could not leave that node.", true);
  } finally {
    state.isBusy = false;
  }
  if (run) applyRun(run);
}

async function abandonRun() {
  try {
    const response = await TinyActivity.command(".hack quit");
    state.audio?.blip("close");
    showResult({
      abandoned: true,
      floor: state.run?.floor?.level || 1,
      corp_id: state.run?.corp?.id || "tower",
      cleared: response.payload.outcome?.cleared ?? 0,
      bops: response.payload.outcome?.bops ?? 0,
      kudos: 0,
      props: [],
      helper: null,
    });
  } catch (error) {
    TinyActivity.toast(error.message || "Could not abandon this hack.", true);
  }
}

// -- wiring -----------------------------------------------------------------

async function resumeRun() {
  try {
    const response = await TinyActivity.command(".hack resume");
    state.audio?.blip("open");
    applyRun(response.payload.run);
  } catch (error) {
    TinyActivity.toast(error.message || "That hack could not resume.", true);
    await leaveToCorps();
  }
}

function wire() {
  ui.bootGo.addEventListener("click", finishBoot);
  ui.screens.boot.addEventListener("click", event => {
    if (event.target.closest("button")) return;
    finishBoot();
  });
  document.addEventListener("keydown", event => {
    if (!ui.screens.boot.hidden && (event.key === " " || event.key === "Enter")) finishBoot();
  });

  ui.floorsBack.addEventListener("click", () => {
    state.blueprint.stop();
    show("corps");
  });
  ui.crewStart.addEventListener("click", jackIn);

  ui.resumeGo.addEventListener("click", resumeRun);
  ui.resumeAbandon.addEventListener("click", abandonRun);

  ui.mapLeave.addEventListener("click", () => {
    stopClock();
    show("corps");
    void refreshBoard();
  });
  ui.mapAbandon.addEventListener("click", abandonRun);
  ui.nodeExit.addEventListener("click", exitNode);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && !ui.screens.node.hidden) {
      event.preventDefault();
      void exitNode();
    }
  });

  ui.resultAgain.addEventListener("click", () => {
    state.fx?.glitch("#ffffff", 0.4);
    void leaveToCorps();
  });
  ui.resultClose.addEventListener("click", () => TinyActivity.close("complete"));

  TinyActivity.subscribe(() => {
    if (!state.board) void refreshBoard().catch(() => {});
  });
  window.setTimeout(() => {
    if (!state.board) void refreshBoard().catch(() => {});
  }, 900);
}

async function main() {
  setupEffects();
  wire();
  show("boot");
  void bootSequence();
  const params = new URLSearchParams(window.location.search);
  if (params.get("skip_boot") === "1") void finishBoot();
}

void main();
