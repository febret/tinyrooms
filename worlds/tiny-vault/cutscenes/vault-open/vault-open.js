import {
  beginCutscene,
  captions,
  endCutscene,
  sound,
  wait,
} from "../../app/js/cutscenes/stage.js";

export default async function (ctx) {
  const dom = beginCutscene("movie", {
    background: ctx.params.stage_background,
    duration: 700,
  });

  const vault = document.createElement("h2");
  vault.className = "heist-cutscene-title heist-vault";
  vault.textContent = "VAULT OPEN";
  dom.append(vault);
  sound("open-metal.wav");

  await wait(800);
  await captions(ctx.text);
  await wait(300);
  endCutscene();
}
