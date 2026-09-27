/**
 * Built-in cutscene frame types.
 *
 * A frame owns the geometry of the cutscene container plus its intro and
 * outro timing. The runtime drives the phases with a CSS animation and reads
 * the durations from here, so a frame never implements timing itself.
 */
export const BUILTIN_FRAMES = {
  movie: {
    cssClass: "cutscene-frame-movie",
    introMs: 700,
    outroMs: 520,
    from: "left",
  },
  vs: {
    cssClass: "cutscene-frame-vs",
    introMs: 620,
    outroMs: 420,
    from: "top",
  },
  letterbox: {
    cssClass: "cutscene-frame-letterbox",
    introMs: 460,
    outroMs: 360,
    from: "top",
  },
  caption: {
    cssClass: "cutscene-frame-caption",
    introMs: 320,
    outroMs: 240,
    from: "bottom",
  },
  plain: {
    cssClass: "cutscene-frame-plain",
    introMs: 220,
    outroMs: 180,
    from: "center",
  },
};

export const DEFAULT_FRAME = "plain";
