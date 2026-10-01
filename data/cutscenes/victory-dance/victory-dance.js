import {
  beginCutscene,
  endCutscene,
  registerCutsceneFrame,
  sprite,
  wait,
} from "../../app/js/cutscenes/stage.js";

registerCutsceneFrame("victory-banner", {
  cssClass: "cutscene-frame-victory",
  introMs: 520,
  outroMs: 300,
});

export default async function (ctx) {
  const dom = beginCutscene("victory-banner", {
    background: ctx.params.stage_background,
    accent: ctx.params.accent,
  });

  const banner = document.createElement("h2");
  banner.className = "cutscene-banner";
  banner.textContent = ctx.title.toUpperCase();
  dom.append(banner);

  const dancer = await sprite("$me");
  dancer.className = "cutscene-dancer";
  dom.append(dancer);

  await wait(2600);
  endCutscene();
}
