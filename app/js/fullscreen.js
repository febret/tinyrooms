const CHANGE_EVENTS = ["fullscreenchange", "webkitfullscreenchange", "MSFullscreenChange"];

function requestMethod(element) {
  return element.requestFullscreen
    || element.webkitRequestFullscreen
    || element.webkitRequestFullScreen
    || element.msRequestFullscreen
    || null;
}

function exitMethod() {
  return document.exitFullscreen
    || document.webkitExitFullscreen
    || document.webkitCancelFullScreen
    || document.msExitFullscreen
    || null;
}

export function currentFullscreenElement() {
  return document.fullscreenElement
    || document.webkitFullscreenElement
    || document.msFullscreenElement
    || null;
}

export function isFullscreen() {
  return Boolean(currentFullscreenElement());
}

export function fullscreenSupported(element = document.documentElement) {
  return typeof requestMethod(element) === "function" && typeof exitMethod() === "function";
}

export async function enterFullscreen(element = document.documentElement) {
  const request = requestMethod(element);
  if (typeof request !== "function") throw new Error("Fullscreen is not supported on this device.");
  await Promise.resolve(request.call(element));
}

export async function exitFullscreen() {
  const exit = exitMethod();
  if (typeof exit !== "function") return;
  await Promise.resolve(exit.call(document));
}

export function onFullscreenChange(handler) {
  CHANGE_EVENTS.forEach(name => document.addEventListener(name, handler));
  return () => CHANGE_EVENTS.forEach(name => document.removeEventListener(name, handler));
}
