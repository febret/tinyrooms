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

  const alarm = document.createElement("h2");
  alarm.className = "heist-cutscene-title heist-alarm";
  alarm.textContent = "ALARM";
  dom.append(alarm);
  sound("danger1.wav");

  await wait(800);
  await captions(ctx.text);
  await wait(300);
  endCutscene();
}
