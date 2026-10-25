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

  const banner = document.createElement("h2");
  banner.className = "cutscene-banner";
  banner.textContent = ctx.title.toUpperCase();
  dom.append(banner);

  const hero = await sprite("$me");
  hero.className = "cutscene-sprite cutscene-sprite-me";
  dom.append(hero);

  await wait(400);
  await captions(ctx.text);
  await wait(400);
  endCutscene();
}
