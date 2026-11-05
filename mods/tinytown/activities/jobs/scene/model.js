// Pure state for the little scene that plays out beside each Job Office minigame.
//
// The model owns the cast (the player plus invited roommates), where each one
// stands, how they react to hits and misses, and every transient effect. It
// never touches the DOM so node tests can drive it with synthetic events;
// draw.js paints whatever the model says.

import { clamp, mulberry32 } from "../minigames/core.js";

export const YOU = "you";

const PILE_ROWS = [4, 3, 2, 1];
const MAX_PARTICLES = 180;
const SPRING_K = 190;
const SPRING_C = 17;
const MAX_UPSCALE = 2.4;
const SIDE_OVERLAP = 0.8;
const LINEUP_STEP = 0.94;
const CONFETTI_COLORS = ["#ffd479", "#7fe0a4", "#ff8a73", "#8ec5ff", "#f6a6ff", "#fff8e8"];

const LINES = {
  intro: {
    tired: ["I'm so tired.", "Five more minutes?", "Is it nap time yet?", "Running on fumes here."],
    great: ["Right up my alley.", "I was born for this.", "Finally, a job for me."],
    solid: ["I can do this.", "Okay. Let's go.", "How hard can it be?"],
    hard: ["This is above my pay grade.", "Why me?", "I want that in writing."],
    you: ["Okay. Okay. Okay.", "I got this. Probably.", "Nobody panic."],
  },
  ready: ["Here we go...", "Eyes up.", "Don't blink."],
  go: ["Go!"],
  hit: ["Got it!", "Yes!", "Smooth.", "Nice one!", "Boom.", "Easy!", "Look at that!"],
  streak: ["On a roll!", "Unstoppable!", "Hot streak!", "Who's good?"],
  secured: ["That's plenty!", "We're in the clear!"],
  miss: ["Oops!", "Whoops.", "Not like that...", "Ah, no.", "Sorry!", "That's... fine."],
  doomed: ["This is going badly.", "We are not passing this.", "Well. That's a no."],
  win: ["Nailed it!", "Put that on my resume.", "Flawless. Ish."],
  lose: ["Well, that happened.", "We do not speak of this.", "The office will hear of this."],
};

export function layoutFor(width, height) {
  const w = Math.max(1, width);
  const h = Math.max(1, height);
  const pad = clamp(h * 0.1, 22, 34);
  const groundY = h - pad;
  const leadH = Math.min(h * 0.66, w * 1.15, Math.max(60, h - pad - 92));
  const tokenSize = clamp(h * 0.085, 18, 34);
  return {
    w,
    h,
    pad,
    groundY,
    leadH,
    leadX: w * 0.29,
    benchH: leadH * 0.4,
    pileX: w * 0.56,
    tokenSize,
    emblemSize: clamp(h * 0.16, 34, 74),
  };
}

export function pileRows(count) {
  let rows = 0;
  let filled = 0;
  for (const width of PILE_ROWS) {
    if (filled >= count) break;
    rows += 1;
    filled += width;
  }
  return rows;
}

export function pileSlot(layout, index) {
  let row = 0;
  let remaining = index;
  while (row < PILE_ROWS.length - 1 && remaining >= PILE_ROWS[row]) {
    remaining -= PILE_ROWS[row];
    row += 1;
  }
  const columns = PILE_ROWS[row];
  const size = layout.tokenSize;
  return {
    x: layout.pileX + (remaining - (columns - 1) / 2) * size * 1.04,
    y: layout.groundY - size * 0.5 - row * size * 0.88,
  };
}

export function createSceneModel({ seed = 1, reducedMotion = false } = {}) {
  const rng = mulberry32(seed);
  const pick = list => list[Math.floor(rng() * list.length)];
  const model = {
    reducedMotion,
    time: 0,
    layout: layoutFor(600, 360),
    figures: [],
    leadId: null,
    leadFatigue: 0,
    phase: "pick",
    challenge: { required: 1, total: 1, difficulty: 5 },
    hits: 0,
    misses: 0,
    streak: 0,
    secured: false,
    doomed: false,
    pile: 0,
    pilePulse: 0,
    emblemFall: 0,
    phaseTime: 0,
    bubble: null,
    floaters: [],
    particles: [],
    flights: [],
    dropped: [],
    shake: 0,
    flash: { tone: "", age: 9 },
    lastLine: "",
  };

  function say(text, tone = "", ttl = 1.8) {
    model.bubble = { text, tone, age: 0, ttl };
    model.lastLine = text;
  }

  function line(list) {
    let text = pick(list);
    if (text === model.lastLine && list.length > 1) text = pick(list);
    return text;
  }

  function lead() {
    return model.figures.find(entry => entry.id === model.leadId) || null;
  }

  function figureWidth(figure, height = figure.h) {
    return height * figure.aspect;
  }

  function spawn(kind, x, y, extra = {}) {
    if (model.reducedMotion || model.particles.length >= MAX_PARTICLES) return;
    model.particles.push({
      kind,
      x,
      y,
      vx: 0,
      vy: 0,
      rot: rng() * Math.PI * 2,
      vr: 0,
      age: 0,
      ttl: 0.8,
      size: 8,
      color: "#ffd479",
      gravity: 0,
      ...extra,
    });
  }

  function burst(kind, x, y, count, config) {
    for (let index = 0; index < count; index += 1) {
      const angle = rng() * Math.PI * 2;
      const speed = config.speed * (0.45 + rng() * 0.8);
      spawn(kind, x, y, {
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - (config.lift || 0),
        vr: (rng() - 0.5) * 9,
        ttl: config.ttl * (0.7 + rng() * 0.6),
        size: config.size * (0.7 + rng() * 0.6),
        color: config.colors ? config.colors[index % config.colors.length] : config.color,
        gravity: config.gravity || 0,
      });
    }
  }

  function anchors() {
    const figure = lead();
    const layout = model.layout;
    if (!figure) {
      return {
        head: { x: layout.leadX, y: layout.groundY - layout.leadH * 0.9 },
        hands: { x: layout.leadX, y: layout.groundY - layout.leadH * 0.45 },
        feet: { x: layout.leadX, y: layout.groundY },
      };
    }
    return {
      head: { x: figure.x, y: figure.y - figure.h * 0.92 },
      hands: { x: figure.x + figureWidth(figure) * 0.32, y: figure.y - figure.h * 0.45 },
      feet: { x: figure.x, y: figure.y },
    };
  }

  function floater(text, tone) {
    const { hands } = anchors();
    model.floaters.push({
      text,
      tone,
      x: hands.x + 18 + (rng() - 0.5) * 26,
      y: hands.y - 26,
      age: 0,
      ttl: 1.1,
    });
    if (model.floaters.length > 8) model.floaters.shift();
  }

  function hop(figure, power = 1, delay = 0) {
    if (model.reducedMotion) return;
    figure.hopT = -delay;
    figure.hopPower = power;
  }

  function wobble(figure, power = 1, delay = 0) {
    if (model.reducedMotion) return;
    figure.wobbleT = -delay;
    figure.wobbleDepth = power;
  }

  function cheerBench(kind) {
    let delay = 0.05;
    for (const figure of model.figures) {
      if (figure.role !== "bench" && figure.role !== "done") continue;
      if (kind === "cheer") hop(figure, 0.55, delay);
      else wobble(figure, 0.7, delay);
      delay += 0.07;
    }
  }

  function cappedHeight(figure, height) {
    return Math.min(height, figure.natH * MAX_UPSCALE);
  }

  function relayout() {
    const layout = model.layout;
    const side = model.figures.filter(entry => entry.role === "bench" || entry.role === "done");
    let sideScale = 1;
    const sideHeights = side.map(figure => cappedHeight(figure, layout.benchH));
    const sideWidths = side.map((figure, index) => sideHeights[index] * figure.aspect);
    const sideSpan = sideWidths.reduce((sum, width, index) => sum + width * (index === side.length - 1 ? 1 : SIDE_OVERLAP), 0);
    if (sideSpan > layout.w * 0.42) sideScale = (layout.w * 0.42) / sideSpan;
    let cursor = layout.w - layout.w * 0.03;
    for (let index = side.length - 1; index >= 0; index -= 1) {
      const figure = side[index];
      const width = sideWidths[index] * sideScale;
      figure.tx = cursor - width / 2;
      figure.ty = layout.groundY;
      figure.th = sideHeights[index] * sideScale;
      cursor -= width * SIDE_OVERLAP;
    }
    const sideLeft = side.length
      ? Math.min(...side.map(figure => figure.tx - (figure.th * figure.aspect) / 2))
      : layout.w;
    const sideBlock = layout.w - sideLeft;
    const lineup = model.figures.filter(entry => entry.role === "lineup");
    const regionLeft = layout.w * 0.05;
    const regionRight = layout.w - sideBlock - layout.w * (sideBlock ? 0.04 : 0.05);
    const avail = Math.max(40, regionRight - regionLeft);
    const base = Math.min(layout.h * 0.62, layout.leadH);
    const heights = lineup.map(figure => cappedHeight(figure, base));
    const widths = lineup.map((figure, index) => heights[index] * figure.aspect);
    const span = widths.reduce((sum, width) => sum + width * LINEUP_STEP, 0);
    const lineupScale = Math.min(1, avail / Math.max(1, span));
    let x = regionLeft + (avail - span * lineupScale) / 2;
    lineup.forEach((figure, index) => {
      const width = widths[index] * lineupScale;
      figure.tx = x + width / 2;
      figure.ty = layout.groundY;
      figure.th = heights[index] * lineupScale;
      x += width * LINEUP_STEP;
    });
    for (const figure of model.figures) {
      if (figure.role !== "lead") continue;
      const height = cappedHeight(figure, layout.leadH);
      figure.tx = Math.max(layout.leadX, (height * figure.aspect) / 2 + layout.w * 0.03);
      figure.ty = layout.groundY;
      figure.th = height;
    }
  }

  function assignRoles() {
    for (const figure of model.figures) {
      if (figure.used) figure.role = "done";
      else if (model.leadId === figure.id) figure.role = "lead";
      else figure.role = model.leadId ? "bench" : "lineup";
    }
    const order = { lineup: 0, lead: 0, bench: 1, done: 2 };
    model.figures.sort((a, b) => order[a.role] - order[b.role]);
    relayout();
  }

  model.setCrew = function setCrew(crew) {
    const existing = new Map(model.figures.map(figure => [figure.id, figure]));
    model.figures = crew.map(member => {
      const previous = existing.get(member.id);
      const figure = previous || {
        id: member.id,
        x: model.layout.w * 0.5,
        y: model.layout.groundY,
        h: model.layout.leadH * 0.5,
        vx: 0,
        vh: 0,
        tx: 0,
        ty: 0,
        th: 0,
        aspect: 0.58,
        natH: 9999,
        hopT: 9,
        hopPower: 1,
        wobbleT: 9,
        wobbleDepth: 1,
        phase: rng() * 6.28,
        role: "lineup",
      };
      figure.name = member.name;
      figure.you = Boolean(member.you);
      figure.used = Boolean(member.used);
      return figure;
    });
    if (!model.figures.some(figure => figure.id === model.leadId && !figure.used)) model.leadId = null;
    assignRoles();
    for (const figure of model.figures) {
      if (!existing.has(figure.id)) {
        figure.x = figure.tx;
        figure.h = figure.th;
        hop(figure, 0.5, rng() * 0.2);
      }
    }
  };

  model.setAspect = function setAspect(id, aspect, naturalHeight = 9999) {
    const figure = model.figures.find(entry => entry.id === id);
    if (!figure || !(aspect > 0.1)) return;
    figure.aspect = clamp(aspect, 0.3, 1.4);
    figure.natH = Math.max(40, naturalHeight);
    relayout();
  };

  model.resize = function resize(width, height) {
    model.layout = layoutFor(width, height);
    relayout();
    if (model.time > 0) return;
    for (const figure of model.figures) {
      figure.x = figure.tx;
      figure.y = figure.ty;
      figure.h = figure.th;
    }
  };

  model.setLead = function setLead(id, fitLabel = "", fatigue = 0) {
    const figure = model.figures.find(entry => entry.id === id && !entry.used);
    model.leadId = figure ? figure.id : null;
    model.leadFatigue = figure ? clamp(Number(fatigue) || 0, 0, 1) : 0;
    assignRoles();
    if (!figure) {
      model.bubble = null;
      return;
    }
    hop(figure, 1);
    let pool = LINES.intro.solid;
    if (model.leadFatigue >= 0.5) pool = LINES.intro.tired;
    else if (figure.you) pool = LINES.intro.you;
    else if (fitLabel === "In their element") pool = LINES.intro.great;
    else if (fitLabel === "Out of their depth") pool = LINES.intro.hard;
    say(line(pool), "intro", 2.4);
  };

  model.markUsed = function markUsed(ids) {
    const set = new Set(ids);
    for (const figure of model.figures) figure.used = set.has(figure.id);
    assignRoles();
  };

  function clearRound() {
    model.phaseTime = 0;
    model.hits = 0;
    model.misses = 0;
    model.streak = 0;
    model.secured = false;
    model.doomed = false;
    model.pile = 0;
    model.emblemFall = 0;
    model.flights = [];
    model.dropped = [];
  }

  model.begin = function begin(challenge) {
    model.challenge = { required: 1, total: 1, difficulty: 5, ...challenge };
    if (Number.isFinite(challenge?.fatigue)) model.leadFatigue = clamp(challenge.fatigue, 0, 1);
    model.phase = "ready";
    clearRound();
    model.floaters = [];
    say(line(LINES.ready), "ready", 2.2);
  };

  model.go = function go() {
    model.phase = "play";
    model.phaseTime = 0;
    say(LINES.go[0], "go", 0.9);
    const figure = lead();
    if (figure) hop(figure, 0.8);
  };

  function launch(kind) {
    const { hands, feet } = anchors();
    const layout = model.layout;
    let to;
    if (kind === "hit") {
      to = pileSlot(layout, Math.min(model.hits - 1, 9));
    } else {
      const figure = lead();
      const reach = figure ? figureWidth(figure) * 0.7 : layout.tokenSize * 2;
      to = { x: feet.x + reach + rng() * layout.tokenSize * 1.6, y: layout.groundY - layout.tokenSize * 0.5 };
    }
    if (model.reducedMotion) {
      land({ kind, to });
      return;
    }
    model.flights.push({ kind, from: { ...hands }, to, t: 0, dur: kind === "hit" ? 0.48 : 0.55 });
  }

  function land(flight) {
    const layout = model.layout;
    if (flight.kind === "hit") {
      model.pile += 1;
      model.pilePulse = 1;
      burst("dust", flight.to.x, flight.to.y + layout.tokenSize * 0.3, 5, {
        speed: 70,
        ttl: 0.45,
        size: 5,
        color: "rgba(255, 248, 232, 0.8)",
      });
      burst("spark", flight.to.x, flight.to.y, 5, {
        speed: 110,
        ttl: 0.55,
        size: 7,
        colors: ["#ffd479", "#fff8e8"],
      });
    } else {
      model.dropped.push({ x: flight.to.x, y: flight.to.y, age: 0, ttl: 1.6, spin: rng() * 6 });
      burst("dust", flight.to.x, flight.to.y + layout.tokenSize * 0.3, 7, {
        speed: 90,
        ttl: 0.55,
        size: 6,
        color: "rgba(180, 170, 155, 0.8)",
      });
    }
  }

  model.hit = function hit() {
    if (model.phase !== "play") return;
    model.hits += 1;
    model.streak += 1;
    model.flash = { tone: "good", age: 0 };
    const figure = lead();
    if (figure) hop(figure, 0.85 + Math.min(0.5, model.streak * 0.08));
    cheerBench("cheer");
    const { head } = anchors();
    burst("spark", head.x + 10, head.y + 24, 6, { speed: 150, ttl: 0.6, size: 8, colors: ["#ffd479", "#fff8e8", "#7fe0a4"] });
    floater(model.streak >= 3 ? `x${model.streak}` : "+1", "good");
    if (!model.secured && model.hits >= model.challenge.required) {
      model.secured = true;
      say(line(LINES.secured), "good");
    } else if (model.streak >= 3 && model.streak % 2 === 1) {
      say(line(LINES.streak), "good");
    } else {
      say(line(LINES.hit), "good", 1.3);
    }
    launch("hit");
  };

  model.miss = function miss() {
    if (model.phase !== "play") return;
    model.misses += 1;
    model.streak = 0;
    model.flash = { tone: "bad", age: 0 };
    model.shake = model.reducedMotion ? 0 : 1;
    const figure = lead();
    if (figure) wobble(figure, 1);
    cheerBench("gasp");
    floater("Miss", "bad");
    const { head } = anchors();
    burst("drop", head.x - 12, head.y + 18, 3, { speed: 70, ttl: 0.7, size: 5, color: "#8ec5ff", gravity: 260, lift: 90 });
    if (!model.doomed && !model.secured && model.challenge.total - model.misses < model.challenge.required) {
      model.doomed = true;
      say(line(LINES.doomed), "bad", 2.2);
    } else {
      say(line(LINES.miss), "bad", 1.3);
    }
    launch("miss");
  };

  model.finish = function finish(passed) {
    model.phase = passed ? "win" : "lose";
    model.phaseTime = 0;
    model.flash = { tone: passed ? "good" : "bad", age: 0 };
    say(line(passed ? LINES.win : LINES.lose), passed ? "win" : "lose", 4);
    const { head } = anchors();
    if (passed) {
      burst("confetti", head.x, head.y, 30, {
        speed: 260,
        lift: 160,
        ttl: 1.6,
        size: 9,
        colors: CONFETTI_COLORS,
        gravity: 340,
      });
      cheerBench("cheer");
    } else {
      cheerBench("gasp");
      model.shake = model.reducedMotion ? 0 : 1;
    }
  };

  model.reset = function reset() {
    model.phase = "pick";
    clearRound();
    model.particles = [];
    model.floaters = [];
    model.bubble = null;
    model.shake = 0;
  };

  model.figureAt = function figureAt(x, y, roles = ["lineup", "bench"]) {
    let best = null;
    for (const figure of model.figures) {
      if (!roles.includes(figure.role)) continue;
      const halfW = figureWidth(figure) / 2 + 6;
      if (Math.abs(x - figure.x) <= halfW && y <= figure.y + 8 && y >= figure.y - figure.h - 6) {
        if (!best || Math.abs(x - figure.x) < Math.abs(x - best.x)) best = figure;
      }
    }
    return best;
  };

  model.anchors = anchors;
  model.figureWidth = figureWidth;

  function stepSpring(figure, dt) {
    const pieces = Math.max(1, Math.ceil(dt / (1 / 90)));
    const slice = dt / pieces;
    for (let index = 0; index < pieces; index += 1) {
      figure.vx += (SPRING_K * (figure.tx - figure.x) - SPRING_C * figure.vx) * slice;
      figure.x += figure.vx * slice;
      figure.vh += (SPRING_K * (figure.th - figure.h) - SPRING_C * figure.vh) * slice;
      figure.h += figure.vh * slice;
      figure.y += (figure.ty - figure.y) * Math.min(1, slice * 14);
    }
  }

  model.update = function update(dt) {
    const step = clamp(dt, 0, 0.05);
    model.time += step;
    model.phaseTime += step;
    for (const figure of model.figures) {
      if (model.reducedMotion) {
        figure.x = figure.tx;
        figure.y = figure.ty;
        figure.h = figure.th;
      } else {
        stepSpring(figure, step);
      }
      if (figure.hopT < 1) figure.hopT += step;
      if (figure.wobbleT < 1) figure.wobbleT += step;
    }
    if (model.bubble) {
      model.bubble.age += step;
      if (model.bubble.age > model.bubble.ttl) model.bubble = null;
    }
    model.pilePulse = Math.max(0, model.pilePulse - step * 4);
    model.shake = Math.max(0, model.shake - step * 3.2);
    model.flash.age += step;
    if (model.phase === "lose") model.emblemFall = Math.min(1, model.emblemFall + step * 2.2);
    for (const item of model.floaters) {
      item.age += step;
      item.y -= step * 34;
    }
    model.floaters = model.floaters.filter(item => item.age < item.ttl);
    for (const flight of model.flights) flight.t += step;
    const landed = model.flights.filter(flight => flight.t >= flight.dur);
    model.flights = model.flights.filter(flight => flight.t < flight.dur);
    for (const flight of landed) land(flight);
    for (const item of model.dropped) item.age += step;
    model.dropped = model.dropped.filter(item => item.age < item.ttl);
    for (const particle of model.particles) {
      particle.age += step;
      particle.vy += particle.gravity * step;
      particle.x += particle.vx * step;
      particle.y += particle.vy * step;
      particle.rot += particle.vr * step;
      if (particle.kind === "dust" || particle.kind === "spark") {
        particle.vx *= 1 - step * 2.5;
        particle.vy *= 1 - step * 2.5;
      }
    }
    model.particles = model.particles.filter(particle => particle.age < particle.ttl);
    if (!model.reducedMotion) emitAmbient(step);
  };

  let ambientClock = 0;
  function emitAmbient(step) {
    ambientClock += step;
    const { head } = anchors();
    const layout = model.layout;
    if (model.phase === "win" && ambientClock > 0.045 && model.phaseTime < 2.4) {
      ambientClock = 0;
      spawn("confetti", rng() * layout.w, -8, {
        vx: (rng() - 0.5) * 70,
        vy: 60 + rng() * 80,
        vr: (rng() - 0.5) * 10,
        ttl: 2.6,
        size: 8,
        color: pick(CONFETTI_COLORS),
        gravity: 30,
      });
    } else if (model.phase === "lose" && ambientClock > 0.08) {
      ambientClock = 0;
      spawn("drop", head.x + (rng() - 0.5) * 50, head.y - 6, {
        vy: 60,
        ttl: 0.9,
        size: 5,
        color: "#8ec5ff",
        gravity: 420,
      });
    } else if (model.leadFatigue >= 0.55 && model.leadId && model.phase !== "win" && ambientClock > 1.1) {
      ambientClock = 0;
      spawn("zzz", head.x + 26, head.y + 20, { vx: 14, vy: -26, vr: 0, rot: 0, ttl: 1.9, size: 15, color: "#cfe0ff" });
    } else if (model.phase === "play" && model.challenge.difficulty >= 7 && ambientClock > 0.7) {
      ambientClock = 0;
      spawn("drop", head.x + 22, head.y + 18, { vx: 30, vy: -50, ttl: 0.6, size: 4, color: "#bfe3ff", gravity: 300 });
    }
  }

  model.pose = function pose(figure) {
    const time = model.time + figure.phase;
    const state = { dx: 0, dy: 0, rot: 0, sx: 1, sy: 1, alpha: figure.role === "done" ? 0.62 : 1 };
    if (model.reducedMotion) return state;
    const isLead = figure.role === "lead";
    const tired = isLead ? model.leadFatigue : 0;
    const breath = Math.sin(time * (2.1 - tired * 1.1));
    state.sy += breath * (0.012 + tired * 0.012);
    state.sx -= breath * 0.006;
    if (tired > 0.3) {
      state.rot -= 0.035 * tired;
      state.sy *= 1 - 0.035 * tired;
      state.dy += figure.h * 0.012 * tired;
    }
    if (isLead && model.phase === "play") {
      const rate = (3 + model.challenge.difficulty * 0.22) * (1 - tired * 0.45);
      state.dy -= Math.abs(Math.sin(time * rate)) * figure.h * 0.015;
      state.rot += Math.sin(time * rate * 0.5) * 0.015;
    }
    if (isLead && model.phase === "win" && figure.hopT >= 1 && model.phaseTime > 0.5) {
      const loop = (model.phaseTime * 1.6) % 1;
      state.dy -= Math.sin(loop * Math.PI) * figure.h * 0.07;
    }
    if (isLead && model.phase === "lose") {
      state.rot -= 0.06;
      state.sy *= 0.95;
      state.dy += figure.h * 0.012;
    }
    if (figure.hopT >= 0 && figure.hopT < 0.5) {
      const unit = figure.hopT / 0.5;
      const arc = Math.sin(unit * Math.PI);
      state.dy -= arc * figure.h * 0.11 * figure.hopPower;
      const squash = unit < 0.12 || unit > 0.88 ? 0.06 : -0.04 * arc;
      state.sy -= squash * figure.hopPower;
      state.sx += squash * figure.hopPower * 0.8;
    }
    if (figure.wobbleT >= 0 && figure.wobbleT < 0.6) {
      const decay = 1 - figure.wobbleT / 0.6;
      state.rot += Math.sin(figure.wobbleT * 34) * 0.09 * decay * figure.wobbleDepth;
    }
    return state;
  }

  return model;
}
