// Maths screen renderers. Answers arrive with the screen (the server re-checks
// the final submission), so every line can turn green the instant it is right.

import { localCheck, normaliseAnswer } from "./hacker-model.js";

function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
}

function digitInput({ id, digits = 1, onCheck, autofocus = false }) {
  const input = el("input", "digit");
  input.dataset.answer = id;
  input.type = "text";
  input.inputMode = "numeric";
  input.autocomplete = "off";
  input.setAttribute("aria-label", `Answer ${id}`);
  input.maxLength = Math.max(1, digits);
  input.size = Math.max(2, digits);
  if (autofocus) window.setTimeout(() => input.focus({ preventScroll: true }), 60);
  input.addEventListener("input", () => {
    input.value = input.value.replace(/[^0-9-]/g, "").slice(0, Math.max(1, digits));
    input.classList.remove("wrong");
    onCheck(input);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      input.blur();
    }
  });
  return input;
}

function rowWith(text, input, mark = "") {
  const row = el("div", "prob-row");
  row.append(el("span", "prob-text", text), input, el("span", "prob-mark", mark));
  return row;
}

function head(container, screen) {
  const wrap = el("div", "edu-head");
  const copy = el("div");
  copy.append(el("h2", "", screen.title), el("p", "edu-brief", screen.brief));
  wrap.append(copy);
  container.append(wrap);
  return wrap;
}

function finalise(screen, answers, onSolved, startedAt) {
  const checked = localCheck(screen, answers);
  if (!checked.passed) return false;
  onSolved({ ...answers }, Date.now() - startedAt);
  return true;
}

// -- screen kinds -----------------------------------------------------------

function renderTyped(container, screen, options, { gap = false } = {}) {
  const prompts = screen.payload?.prompts || [];
  const list = el("div", "prob-list");
  const answers = {};
  let solved = false;
  const inputs = [];
  for (const prompt of prompts) {
    const input = digitInput({
      id: prompt.id,
      digits: prompt.digits || 2,
      autofocus: inputs.length === 0,
      onCheck: element => {
        const value = normaliseAnswer(element.value);
        if (value === "") return;
        if (value === normaliseAnswer(screen.answers[prompt.id])) {
          element.classList.add("correct");
          element.readOnly = true;
          answers[prompt.id] = value;
          row.classList.add("solved");
          mark.textContent = "✓";
          options.audio?.blip("good");
          if (!solved && finalise(screen, answers, options.onSolved, options.startedAt)) solved = true;
        } else if (value.length >= String(screen.answers[prompt.id]).length) {
          element.classList.add("wrong");
          options.audio?.blip("bad");
          options.onWrong?.();
        }
      },
    });
    const row = rowWith(gap ? prompt.text.replace("□", "▁") : prompt.text, input, "");
    const mark = row.querySelector(".prob-mark");
    row.dataset.problem = prompt.id;
    inputs.push(input);
    list.append(row);
  }
  container.append(list);
  return { focus: () => inputs[0]?.focus({ preventScroll: true }) };
}

function renderMatch(container, screen, options) {
  const prompts = screen.payload?.prompts || [];
  const choices = screen.payload?.choices || [];
  const answers = {};
  const links = new Map();
  let selected = "";
  let solved = false;
  let resizeFrame = 0;
  const layout = el("div", "match-layout");
  const left = el("div", "match-col");
  const right = el("div", "match-col");
  left.append(el("p", "hack-kicker", "Operations"));
  right.append(el("p", "hack-kicker", "Results"));
  const promptNodes = new Map();
  const choiceNodes = new Map();
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", "match-links");
  svg.setAttribute("aria-hidden", "true");
  const NS = "http://www.w3.org/2000/svg";

  function point(node, side) {
    const rect = node.getBoundingClientRect();
    const box = layout.getBoundingClientRect();
    const inset = 9;
    return {
      x: (side === "right" ? rect.right - inset : rect.left + inset) - box.left,
      y: rect.top + rect.height / 2 - box.top,
    };
  }

  function tracePath(promptId, choiceId) {
    const promptNode = promptNodes.get(promptId);
    const choiceNode = choiceNodes.get(choiceId);
    if (!promptNode || !choiceNode) return "";
    const fromPoint = point(promptNode, "right");
    const toPoint = point(choiceNode, "left");
    if (toPoint.x <= fromPoint.x) return "";
    const mid = fromPoint.x + (toPoint.x - fromPoint.x) * 0.55;
    return `M ${fromPoint.x} ${fromPoint.y} H ${mid} V ${toPoint.y} H ${toPoint.x}`;
  }

  function pad(x, y) {
    const rect = document.createElementNS(NS, "rect");
    rect.setAttribute("class", "match-node");
    rect.setAttribute("x", String(x - 2.5));
    rect.setAttribute("y", String(y - 2.5));
    rect.setAttribute("width", "5");
    rect.setAttribute("height", "5");
    return rect;
  }

  function drawTrace(promptId, animate) {
    const choiceId = links.get(promptId);
    if (!choiceId) return;
    const pathData = tracePath(promptId, choiceId);
    if (!pathData) return;
    const path = document.createElementNS(NS, "path");
    path.setAttribute("class", "match-link");
    path.setAttribute("d", pathData);
    path.setAttribute("pathLength", "1");
    if (animate) path.classList.add("draw");
    svg.append(path);
    const fromPoint = point(promptNodes.get(promptId), "right");
    const toPoint = point(choiceNodes.get(choiceId), "left");
    svg.append(pad(fromPoint.x, fromPoint.y), pad(toPoint.x, toPoint.y));
  }

  function redraw() {
    svg.replaceChildren();
    for (const promptId of links.keys()) drawTrace(promptId, false);
  }

  function queueRedraw() {
    window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(redraw);
  }

  function choosePrompt(id) {
    if (answers[id]) return;
    selected = id;
    for (const [key, node] of promptNodes) node.classList.toggle("selected", key === id);
  }

  function chooseResult(choiceId, node) {
    if (!selected) return;
    const promptId = selected;
    const correct = normaliseAnswer(screen.answers[promptId]) === normaliseAnswer(choiceId);
    if (correct) {
      answers[promptId] = choiceId;
      links.set(promptId, choiceId);
      promptNodes.get(promptId)?.classList.add("solved");
      promptNodes.get(promptId)?.classList.remove("selected");
      node.classList.add("used");
      node.disabled = true;
      selected = "";
      drawTrace(promptId, true);
      options.audio?.blip("good");
      if (!solved && finalise(screen, answers, options.onSolved, options.startedAt)) solved = true;
    } else {
      node.classList.add("wrong");
      options.audio?.blip("bad");
      options.onWrong?.();
      window.setTimeout(() => node.classList.remove("wrong"), 380);
    }
  }

  for (const prompt of prompts) {
    const node = el("button", "match-item", prompt.text);
    node.type = "button";
    node.dataset.prompt = prompt.id;
    node.addEventListener("click", () => choosePrompt(prompt.id));
    promptNodes.set(prompt.id, node);
    left.append(node);
  }
  for (const choice of choices) {
    const node = el("button", "match-item", choice.label);
    node.type = "button";
    node.dataset.choice = choice.id;
    node.addEventListener("click", () => chooseResult(choice.id, node));
    choiceNodes.set(choice.id, node);
    right.append(node);
  }
  layout.append(left, right);
  container.append(layout);
  layout.append(svg);

  const observer = typeof ResizeObserver === "function" ? new ResizeObserver(queueRedraw) : null;
  observer?.observe(layout);
  window.addEventListener("resize", queueRedraw);

  return {
    focus: () => promptNodes.values().next().value?.focus({ preventScroll: true }),
    destroy: () => {
      observer?.disconnect();
      window.cancelAnimationFrame(resizeFrame);
      window.removeEventListener("resize", queueRedraw);
    },
  };
}

function renderGlitch(container, screen, options) {
  const equations = screen.payload?.equations || [];
  const target = Number(screen.payload?.target || 3);
  const flagged = new Set();
  let solved = false;
  const grid = el("div", "glitch-grid");
  const nodes = new Map();
  for (const equation of equations) {
    const node = el("button", "glitch-cell", equation.text);
    node.type = "button";
    node.dataset.equation = equation.id;
    node.setAttribute("aria-pressed", "false");
    node.addEventListener("click", () => {
      if (solved) return;
      if (flagged.has(equation.id)) flagged.delete(equation.id);
      else if (flagged.size < target) flagged.add(equation.id);
      node.classList.toggle("flagged", flagged.has(equation.id));
      node.setAttribute("aria-pressed", String(flagged.has(equation.id)));
      confirm.disabled = flagged.size !== target;
      options.audio?.blip("key");
    });
    nodes.set(equation.id, node);
    grid.append(node);
  }
  const confirm = el("button", "hack-btn primary", "RUN DIAGNOSTIC");
  confirm.type = "button";
  confirm.disabled = true;
  confirm.addEventListener("click", () => {
    if (flagged.size !== target) return;
    const answers = {};
    for (const equation of equations) {
      answers[equation.id] = flagged.has(equation.id) ? "bad" : "ok";
    }
    if (finalise(screen, answers, options.onSolved, options.startedAt)) {
      solved = true;
      confirm.disabled = true;
      for (const equation of equations) {
        const node = nodes.get(equation.id);
        if (flagged.has(equation.id)) node.classList.add("solved");
      }
      return;
    }
    options.audio?.blip("bad");
    options.onWrong?.();
    for (const id of flagged) {
      const node = nodes.get(id);
      node.classList.remove("flagged");
    }
    flagged.clear();
    confirm.disabled = true;
  });
  const actions = el("div", "edu-actions");
  actions.append(confirm);
  container.append(grid, actions);
  return { focus: () => nodes.values().next().value?.focus({ preventScroll: true }) };
}

function renderQuickPick(container, screen, options) {
  const prompts = screen.payload?.prompts || [];
  const limit = Number(screen.payload?.time_limit_ms || 15000);
  const answers = {};
  let solved = false;
  let remaining = limit;
  const cooldowns = [];
  const timer = el("p", "edu-timer", `${(remaining / 1000).toFixed(1)}s`);
  (container.parentElement || container).querySelector(".edu-head")?.append(timer);
  const grid = el("div", "quick-grid");
  const cards = new Map();

  function updateTimer() {
    timer.textContent = `${(remaining / 1000).toFixed(1)}s`;
    timer.classList.toggle("urgent", remaining <= 4000);
    if (remaining <= 0) {
      window.clearInterval(handle);
      if (!solved) options.onTimeout?.(limit);
    }
  }

  const handle = window.setInterval(() => {
    remaining -= 100;
    if (Math.floor(remaining / 1000) !== Math.floor((remaining + 100) / 1000) && remaining > 0) {
      options.audio?.blip("tick");
    }
    updateTimer();
  }, 100);
  updateTimer();

  for (const prompt of prompts) {
    const card = el("div", "quick-card");
    card.dataset.prompt = prompt.id;
    card.append(el("div", "prob-text", prompt.text));
    const choices = el("div", "quick-choices");
    const buttons = [];
    for (const choice of prompt.choices || []) {
      const button = el("button", "choice-btn", choice.label);
      button.type = "button";
      button.dataset.choice = choice.id;
      button.addEventListener("click", () => {
        if (solved || answers[prompt.id]) return;
        if (normaliseAnswer(screen.answers[prompt.id]) === normaliseAnswer(choice.id)) {
          answers[prompt.id] = choice.id;
          button.classList.add("taken");
          card.classList.add("solved");
          for (const other of buttons) other.disabled = true;
          options.audio?.blip("good");
          if (!solved && finalise(screen, answers, options.onSolved, options.startedAt)) {
            solved = true;
            window.clearInterval(handle);
          }
        } else {
          button.classList.add("wrong");
          card.classList.add("locked");
          for (const other of buttons) other.disabled = true;
          options.audio?.blip("bad");
          options.onWrong?.();
          cooldowns.push(window.setTimeout(() => {
            card.classList.remove("locked");
            if (!answers[prompt.id]) {
              for (const other of buttons) other.disabled = false;
              button.classList.remove("wrong");
            }
          }, 1000));
        }
      });
      buttons.push(button);
      choices.append(button);
    }
    card.append(choices);
    cards.set(prompt.id, card);
    grid.append(card);
  }
  container.append(grid);
  return {
    focus: () => grid.querySelector("button")?.focus({ preventScroll: true }),
    destroy: () => {
      window.clearInterval(handle);
      for (const timeout of cooldowns) window.clearTimeout(timeout);
    },
  };
}

function renderLongMult(container, screen, options) {
  const problems = screen.payload?.problems || [];
  const answers = {};
  let solved = false;
  const totalInputs = problems.reduce(
    (sum, problem) => sum + problem.rows.reduce((count, row) => count + row.cells.filter(cell => cell.input_id).length, 0),
    0,
  );
  let correctCount = 0;
  const scroll = el("div", "longmult-scroll");
  const inputs = [];
  for (const problem of problems) {
    const wrap = el("div", "lm-problem");
    wrap.append(el("p", "lm-head", `${problem.top} × ${problem.bottom}`));
    const grid = el("div", "lm-grid");
    grid.style.gridTemplateColumns = `repeat(${problem.width}, minmax(32px, auto))`;
    for (const row of problem.rows) {
      const line = el("div", "lm-row");
      for (let column = 0; column < problem.width; column += 1) {
        const cell = el("div", "lm-cell");
        const entry = (row.cells || []).find(item => item.col === column);
        if (!entry) {
          cell.textContent = "";
          line.append(cell);
          continue;
        }
        if (entry.input_id) {
          cell.classList.add("blank");
          const input = el("input", "lm-input");
          input.type = "text";
          input.inputMode = "numeric";
          input.maxLength = 1;
          input.autocomplete = "off";
          input.setAttribute("aria-label", `Digit ${entry.input_id}`);
          input.dataset.answer = entry.input_id;
          input.addEventListener("input", () => {
            input.value = input.value.replace(/[^0-9]/g, "").slice(0, 1);
            if (input.value === entry.text) {
              if (!input.classList.contains("correct")) {
                correctCount += 1;
                answers[entry.input_id] = input.value;
                input.classList.add("correct");
                input.readOnly = true;
                options.audio?.blip("good");
                if (!solved && correctCount === totalInputs) {
                  if (finalise(screen, answers, options.onSolved, options.startedAt)) solved = true;
                }
              }
            } else {
              input.classList.remove("correct");
            }
          });
          inputs.push(input);
          cell.append(input);
        } else {
          cell.classList.add("given");
          cell.textContent = entry.text;
        }
        line.append(cell);
      }
      grid.append(line);
    }
    wrap.append(grid);
    scroll.append(wrap);
  }
  container.append(scroll);
  return { focus: () => inputs[0]?.focus({ preventScroll: true }) };
}

function renderAreaModel(container, screen, options) {
  const payload = screen.payload || {};
  const answers = {};
  const inputs = [];
  let solved = false;
  const totalCount = (payload.parts || []).length + 1;
  let correctCount = 0;
  const parts = el("div", "area-parts");
  const formula = el("p", "area-formula", `${payload.a} × ${payload.b} = (${payload.a_parts?.[0]} + ${payload.a_parts?.[1]}) × (${payload.b_parts?.[0]} + ${payload.b_parts?.[1]})`);
  container.append(formula);
  for (const part of payload.parts || []) {
    const row = el("div", "area-part");
    row.append(el("span", "", part.text));
    const input = digitInput({
      id: part.id,
      digits: part.digits || 3,
      onCheck: element => checkValue(part.id, element, row),
    });
    inputs.push(input);
    row.append(input);
    parts.append(row);
  }
  container.append(parts);
  const total = el("div", "area-total");
  total.append(el("span", "", `Total ${payload.total?.text || ""}`));
  const totalInput = digitInput({
    id: payload.total?.id || "total",
    digits: payload.total?.digits || 4,
    onCheck: element => checkValue(payload.total?.id || "total", element, total),
  });
  inputs.push(totalInput);
  total.append(totalInput);
  container.append(total);

  function checkValue(id, input, row) {
    const value = normaliseAnswer(input.value);
    if (!value) return;
    if (value === normaliseAnswer(screen.answers[id])) {
      if (!input.classList.contains("correct")) {
        correctCount += 1;
        answers[id] = value;
        input.classList.add("correct");
        input.readOnly = true;
        row.classList.add("solved");
        options.audio?.blip("good");
        if (!solved && correctCount === totalCount && finalise(screen, answers, options.onSolved, options.startedAt)) solved = true;
      }
    } else if (value.length >= String(screen.answers[id]).length) {
      input.classList.add("wrong");
      options.audio?.blip("bad");
      options.onWrong?.();
    }
  }

  return { focus: () => inputs[0]?.focus({ preventScroll: true }) };
}

function renderEstimate(container, screen, options) {
  const prompts = screen.payload?.prompts || [];
  const answers = {};
  let solved = false;
  const list = el("div", "prob-list");
  const buttons = [];
  for (const prompt of prompts) {
    const row = el("div", "estimate-row");
    row.dataset.prompt = prompt.id;
    const copy = el("div");
    copy.append(el("div", "est-text", prompt.text), el("div", "est-hint", prompt.rounded || ""));
    const choices = el("div", "quick-choices");
    const rowButtons = [];
    for (const choice of prompt.choices || []) {
      const button = el("button", "choice-btn", choice.label);
      button.type = "button";
      button.dataset.choice = choice.id;
      button.addEventListener("click", () => {
        if (solved || answers[prompt.id]) return;
        if (normaliseAnswer(screen.answers[prompt.id]) === normaliseAnswer(choice.id)) {
          answers[prompt.id] = choice.id;
          button.classList.add("taken");
          row.classList.add("solved");
          for (const other of rowButtons) other.disabled = true;
          options.audio?.blip("good");
          if (!solved && finalise(screen, answers, options.onSolved, options.startedAt)) solved = true;
        } else {
          button.classList.add("wrong");
          options.audio?.blip("bad");
          options.onWrong?.();
          window.setTimeout(() => button.classList.remove("wrong"), 300);
        }
      });
      rowButtons.push(button);
      choices.append(button);
    }
    buttons.push(...rowButtons);
    row.append(copy, choices);
    list.append(row);
  }
  container.append(list);
  return { focus: () => buttons[0]?.focus({ preventScroll: true }) };
}

const RENDERERS = {
  "type-in": (container, screen, options) => renderTyped(container, screen, options),
  "fill-gap": (container, screen, options) => renderTyped(container, screen, options, { gap: true }),
  match: renderMatch,
  "spot-glitch": renderGlitch,
  "quick-pick": renderQuickPick,
  "long-mult": renderLongMult,
  "long-mult-small": renderLongMult,
  "area-model": renderAreaModel,
  "estimate-lock": renderEstimate,
};

export function renderEduScreen(container, screen, { reducedMotion = false, audio = null, onSolved, onTimeout, onWrong } = {}) {
  container.replaceChildren();
  container.dataset.screen = screen.id;
  container.dataset.kind = screen.type;
  head(container, screen);
  const options = {
    reducedMotion,
    audio,
    onSolved,
    onTimeout,
    onWrong,
    startedAt: Date.now(),
  };
  const renderer = RENDERERS[screen.type];
  if (!renderer) {
    container.append(el("p", "edu-brief", "This screen type is not supported yet."));
    return { destroy() {} };
  }
  const body = el("div", "edu-body");
  container.append(body);
  const handle = renderer(body, screen, options) || {};
  return {
    focus: handle.focus,
    destroy: () => handle.destroy?.(),
  };
}
