import {
  beginCutscene,
  captions,
  endCutscene,
  sound,
  wait,
} from "../../app/js/cutscenes/stage.js";

export default async function (ctx) {
  const dom = beginCutscene("letterbox", {
    background: ctx.params.stage_background,
    duration: 700,
  });

  const title = document.createElement("h2");
  title.className = "heist-cutscene-title heist-busted";
  title.textContent = "BUSTED";
  dom.append(title);
  sound("toast-fail.wav");

  await wait(800);
  await captions(ctx.text);
  await wait(300);
  endCutscene();
}
