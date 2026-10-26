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
  title.className = "heist-cutscene-title heist-clean";
  title.textContent = "CLEAN ESCAPE";
  dom.append(title);

  const crew = document.createElement("div");
  crew.className = "heist-cutscene-crew";
  crew.append(await sprite("$me"));
  dom.append(crew);

  await wait(900);
  await captions(ctx.text);
  await wait(400);
  endCutscene();
}
