export function isFullscreen() {
  return Boolean(document.fullscreenElement);
}

export function fullscreenSupported(element = document.documentElement) {
  return typeof element.requestFullscreen === "function" && typeof document.exitFullscreen === "function";
}

export async function enterFullscreen(element = document.documentElement) {
  if (typeof element.requestFullscreen !== "function") throw new Error("Fullscreen is not supported on this device.");
  await element.requestFullscreen();
}

export async function exitFullscreen() {
  if (typeof document.exitFullscreen !== "function" || !document.fullscreenElement) return;
  await document.exitFullscreen();
}

export function onFullscreenChange(handler) {
  document.addEventListener("fullscreenchange", handler);
  return () => document.removeEventListener("fullscreenchange", handler);
}
