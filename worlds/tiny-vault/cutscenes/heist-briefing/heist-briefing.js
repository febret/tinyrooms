import {
  beginCutscene,
  captions,
  endCutscene,
  sprite,
  wait,
} from "../../app/js/cutscenes/stage.js";

export default async function (ctx) {
  const dom = beginCutscene("movie", {
    background: ctx.params.stage_background,
    duration: 700,
  });

  const title = document.createElement("h2");
  title.className = "heist-cutscene-title";
  title.textContent = "THE PLAN";
  dom.append(title);

  const crew = document.createElement("div");
  crew.className = "heist-cutscene-crew";
  crew.append(await sprite("$me"));
  dom.append(crew);

  const note = document.createElement("p");
  note.className = "heist-cutscene-note";
  note.textContent = "Stay out of the red cones. Leave before lockdown.";
  dom.append(note);

  await wait(900);
  await captions(ctx.text);
  await wait(400);
  endCutscene();
}
