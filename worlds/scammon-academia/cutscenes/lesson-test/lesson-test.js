// The automatic end-of-lesson test. Grades and the teacher GPA are already
// committed server-side; this scene presents each student's result in turn.

import { beginCutscene, endCutscene, sprite, wait } from "../../app/js/cutscenes/stage.js";

const MAX_STUDENTS = 5;

function panel(styles) {
  const node = document.createElement("div");
  Object.assign(node.style, {
    position: "absolute",
    inset: "0",
    display: "grid",
    placeItems: "center",
    gap: "0.6rem",
    textAlign: "center",
    ...styles,
  });
  return node;
}

function popIn(node) {
  node.animate(
    [
      { opacity: 0, transform: "translateY(18px) scale(0.86)" },
      { opacity: 1, transform: "translateY(0) scale(1)" },
    ],
    { duration: 360, easing: "cubic-bezier(.2,1.4,.4,1)", fill: "forwards" },
  );
}

export default async function (ctx) {
  const params = ctx.params || {};
  const stage = beginCutscene("movie", {
    background: params.stage_background || "#0b2545",
    accent: "#f4c430",
    duration: 700,
  });

  const title = panel({ gap: "0.2rem" });
  title.innerHTML =
    '<div style="font:800 2.1rem/1.15 system-ui,sans-serif;color:#f4c430;letter-spacing:.04em">Class Test!</div>' +
    '<div style="font:600 0.95rem/1.3 system-ui,sans-serif;color:#9ad0ff">Every student gets a grade.</div>';
  stage.append(title);
  popIn(title);
  await wait(850);
  title.remove();

  const count = Math.min(MAX_STUDENTS, Math.max(1, Number(params.students) || MAX_STUDENTS));
  for (let index = 1; index <= count; index += 1) {
    const ref = typeof params[`s${index}`] === "string" ? params[`s${index}`] : "";
    const result = typeof params[`r${index}`] === "string" ? params[`r${index}`] : "";

    const card = panel({ gap: "0.5rem", padding: "0 6%" });
    const student = await sprite(ref, { label: "Student" });
    student.style.cssText = "width:min(26vmin,190px);height:min(26vmin,190px);object-fit:contain;filter:drop-shadow(0 12px 22px #000a);";

    const line = document.createElement("div");
    line.textContent = result;
    line.style.cssText =
      "font:700 clamp(0.9rem,2.2vmin,1.35rem)/1.35 system-ui,sans-serif;color:#f7f5ed;" +
      "padding:0.45rem 0.9rem;border-radius:12px;background:#04080cd0;max-width:88%;" +
      "box-shadow:0 8px 22px #0009;";

    const stamp = document.createElement("span");
    stamp.textContent = String(index).padStart(2, "0");
    stamp.style.cssText =
      "position:absolute;top:12%;right:12%;font:900 1.2rem/1 Georgia,serif;color:#ff5a4a;" +
      "border:4px solid #ff5a4a;border-radius:12px;padding:0.15rem 0.5rem;transform:rotate(-12deg);";

    card.append(student, line, stamp);
    stage.append(card);
    popIn(card);
    await wait(1700);
    card.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(-14px)" }], {
      duration: 280,
      easing: "ease-in",
      fill: "forwards",
    });
    await wait(280);
    card.remove();
  }

  const reveal = panel({ gap: "0.15rem" });
  reveal.innerHTML =
    '<div style="font:600 0.95rem/1.4 system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:#9ad0ff">Teacher GPA</div>' +
    `<div style="font:800 5rem/1 Georgia,serif;color:#f4c430">${params.gpa || "2.00"}</div>` +
    `<div style="font:700 1.15rem/1.5 system-ui,sans-serif;color:#f4c430">+${params.bops || "0"} Bops</div>`;
  const seal = await sprite("$me");
  seal.style.cssText = "width:4.5rem;height:4.5rem;object-fit:contain;margin-top:0.4rem;";
  reveal.append(seal);
  stage.append(reveal);
  popIn(reveal);
  await wait(1800);
  endCutscene();
}
