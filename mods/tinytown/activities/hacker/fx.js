// Vector particles, CRT glitches, and terminal typing for the Hacker Collective.

const GLYPHS = "0123456789ABCDEF#%&@$*+=<>/\\";

function randomGlyph() {
  return GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
}

export function createFx(canvas, { reducedMotion = false } = {}) {
  const ctx = canvas.getContext("2d");
  const particles = [];
  const streaks = [];
  let frame = 0;
  let last = 0;
  let clock = 0;
  let ratio = 1;

  function resize() {
    ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(1, Math.round(window.innerWidth * ratio));
    const height = Math.max(1, Math.round(window.innerHeight * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function ensure() {
    if (frame || reducedMotion) return;
    frame = window.requestAnimationFrame(tick);
  }

  function tick(now) {
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
    last = now;
    clock += dt;
    ctx.clearRect(0, 0, window.innerWidth, window.innerHeight);
    for (let index = particles.length - 1; index >= 0; index -= 1) {
      const particle = particles[index];
      particle.life -= dt;
      if (particle.life <= 0) {
        particles.splice(index, 1);
        continue;
      }
      particle.vy += 220 * dt;
      particle.x += particle.vx * dt;
      particle.y += particle.vy * dt;
      const alpha = Math.max(0, particle.life / particle.max);
      ctx.globalAlpha = alpha;
      ctx.fillStyle = particle.color;
      if (particle.kind === "shard") {
        ctx.save();
        ctx.translate(particle.x, particle.y);
        ctx.rotate(particle.angle + clock * particle.spin);
        ctx.fillRect(-particle.size, -particle.size / 3, particle.size * 2, particle.size / 1.5);
        ctx.restore();
      } else {
        ctx.fillRect(particle.x, particle.y, particle.size, particle.size);
      }
    }
    for (let index = streaks.length - 1; index >= 0; index -= 1) {
      const streak = streaks[index];
      streak.life -= dt;
      if (streak.life <= 0) {
        streaks.splice(index, 1);
        continue;
      }
      const progress = 1 - streak.life / streak.max;
      ctx.globalAlpha = Math.max(0, 0.55 * (1 - progress));
      ctx.fillStyle = streak.color;
      const y = streak.y + Math.sin(progress * 9) * 5;
      ctx.fillRect(progress * window.innerWidth * 0.6, y, window.innerWidth * 0.4, streak.height);
    }
    ctx.globalAlpha = 1;
    if (particles.length || streaks.length) {
      frame = window.requestAnimationFrame(tick);
    } else {
      frame = 0;
      last = 0;
    }
  }

  window.addEventListener("resize", resize);
  resize();

  return {
    burst(x, y, color, count = 24) {
      if (reducedMotion) return;
      for (let index = 0; index < count; index += 1) {
        const angle = Math.random() * Math.PI * 2;
        const speed = 60 + Math.random() * 240;
        const life = 0.45 + Math.random() * 0.6;
        particles.push({
          x,
          y,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed - 60,
          life,
          max: life,
          size: 1.5 + Math.random() * 4,
          color,
          kind: Math.random() > 0.45 ? "shard" : "bit",
          angle: Math.random() * Math.PI,
          spin: (Math.random() - 0.5) * 8,
        });
      }
      ensure();
    },
    glitch(color = "#ffffff", strength = 1) {
      if (reducedMotion) return;
      const count = Math.round(3 + strength * 5);
      for (let index = 0; index < count; index += 1) {
        const life = 0.06 + Math.random() * 0.18;
        streaks.push({
          y: Math.random() * window.innerHeight,
          height: 1 + Math.random() * 5 * strength,
          life,
          max: life,
          color,
        });
      }
      ensure();
    },
    destroy() {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      frame = 0;
      particles.length = 0;
      streaks.length = 0;
    },
  };
}

export function typeLines(element, lines, { speed = 26, reducedMotion = false } = {}) {
  element.replaceChildren();
  if (reducedMotion) {
    for (const line of lines) {
      const item = document.createElement("li");
      item.textContent = line;
      element.append(item);
    }
    return Promise.resolve();
  }
  return new Promise(resolve => {
    let lineIndex = 0;
    let charIndex = 0;
    let item = null;
    function step() {
      if (lineIndex >= lines.length) {
        resolve();
        return;
      }
      if (!item) {
        item = document.createElement("li");
        element.append(item);
      }
      charIndex += 1;
      item.textContent = lines[lineIndex].slice(0, charIndex);
      if (charIndex >= lines[lineIndex].length) {
        lineIndex += 1;
        charIndex = 0;
        item = null;
        window.setTimeout(step, 130);
        return;
      }
      window.setTimeout(step, speed);
    }
    step();
  });
}

export function scrambleTo(element, text, { reducedMotion = false, duration = 650 } = {}) {
  if (reducedMotion) {
    element.textContent = text;
    return Promise.resolve();
  }
  return new Promise(resolve => {
    const started = performance.now();
    const target = String(text);
    function frame(now) {
      const progress = Math.min(1, (now - started) / duration);
      const revealed = Math.floor(target.length * progress);
      let value = target.slice(0, revealed);
      for (let index = revealed; index < target.length; index += 1) {
        value += randomGlyph();
      }
      element.textContent = value;
      if (progress < 1) {
        window.requestAnimationFrame(frame);
      } else {
        element.textContent = target;
        resolve();
      }
    }
    window.requestAnimationFrame(frame);
  });
}

export function blipClass(element, className = "glitching", duration = 520) {
  element.classList.add(className);
  window.setTimeout(() => element.classList.remove(className), duration);
}

export function addLog(container, text, tone = "") {
  const line = document.createElement("p");
  line.textContent = text;
  if (tone) line.className = tone;
  container.prepend(line);
  while (container.childElementCount > 24) {
    container.lastElementChild?.remove();
  }
}
