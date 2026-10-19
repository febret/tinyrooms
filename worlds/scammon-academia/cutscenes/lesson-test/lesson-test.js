// The automatic end-of-lesson test: grades stamp down and the teacher's GPA
// is revealed. The server has already recorded the score before playback.

import { beginCutscene, endCutscene, sprite, wait } from "../../app/js/cutscenes/stage.js";

const LETTERS = ["A", "B", "C", "D"];

function stamp(scene, letter, index, total) {
  const node = document.createElement("span");
  node.textContent = letter;
  node.style.cssText = `position:absolute;left:${8 + (index / Math.max(1, total - 1)) * 84}%;top:38%;` +
    "font:800 3rem/1 Georgia, serif;color:#ff5a4a;border:5px solid #ff5a4a;" +
    "border-radius:12px;padding:0.1rem 0.5rem;transform:rotate(-14deg);";
  scene.append(node);
  node.animate(
    [
      { transform: "rotate(-14deg) scale(2.2)", opacity: 0 },
      { transform: "rotate(-14deg) scale(1)", opacity: 1, offset: 0.5 },
      { transform: "rotate(-14deg) scale(1)", opacity: 0 },
    ],
    { duration: 1100, delay: index * 160, easing: "ease-in", fill: "forwards" },
  );
}

export default async function (ctx) {
  const scene = beginCutscene("movie", {
    background: ctx.params.stage_background || "#0b2545",
    accent: "#f4c430",
    duration: 700,
  });

  const title = document.createElement("h2");
  title.textContent = "Class Test!";
  title.style.cssText = "position:absolute;top:14%;left:50%;transform:translateX(-50%);margin:0;" +
    "font:800 2rem/1.2 system-ui, sans-serif;color:#f4c430;letter-spacing:0.04em;";
  scene.append(title);
  title.animate([{ opacity: 0, transform: "translateX(-50%) translateY(-16px)" }, { opacity: 1, transform: "translateX(-50%) translateY(0)" }],
    { duration: 500, easing: "ease-out", fill: "forwards" });

  const pencils = document.createElement("div");
  pencils.style.cssText = "position:absolute;bottom:12%;left:0;right:0;display:flex;justify-content:center;gap:1.2rem;font-size:2.4rem;";
  for (const glyph of ["✏️", "📝", "✅"]) {
    const span = document.createElement("span");
    span.textContent = glyph;
    pencils.append(span);
  }
  scene.append(pencils);
  pencils.animate([{ transform: "translateY(20px)", opacity: 0 }, { transform: "translateY(0)", opacity: 1 }],
    { duration: 500, delay: 250, easing: "ease-out", fill: "forwards" });

  await wait(700);
  const count = Math.max(3, Number(ctx.params.students) || 5);
  for (let index = 0; index < count; index += 1) {
    stamp(scene, LETTERS[index % LETTERS.length], index, count);
  }

  await wait(1500);
  title.remove();
  pencils.remove();

  const gpa = ctx.params.gpa || "2.00";
  const reveal = document.createElement("div");
  reveal.style.cssText = "position:absolute;inset:0;display:grid;place-items:center;text-align:center;color:#fff;";
  reveal.innerHTML = `<div><div style="font:600 1rem/1.4 system-ui,sans-serif;letter-spacing:0.12em;text-transform:uppercase;color:#9ad0ff">Teacher GPA</div>` +
    `<div style="font:800 5rem/1 Georgia, serif;color:#f4c430">${gpa}</div>` +
    `<div style="font:600 1.1rem/1.6 system-ui,sans-serif;color:#f4c430">+${ctx.params.bops || "0"} Bops</div></div>`;
  scene.append(reveal);
  const seal = await sprite("$me");
  seal.style.cssText = "position:absolute;right:8%;bottom:8%;width:5rem;height:5rem;border-radius:50%;";
  scene.append(seal);
  reveal.animate([{ opacity: 0, transform: "scale(0.7)" }, { opacity: 1, transform: "scale(1)" }],
    { duration: 600, easing: "cubic-bezier(.2,1.4,.4,1)", fill: "forwards" });

  await wait(1600);
  endCutscene();
}
