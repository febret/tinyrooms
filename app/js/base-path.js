const BASE_PATH = typeof window !== "undefined" && typeof window.__TR_BASE__ === "string"
  ? window.__TR_BASE__
  : "";

export function withBase(path) {
  if (!BASE_PATH || typeof path !== "string" || !path.startsWith("/") || path.startsWith("//")) {
    return path;
  }
  if (path === BASE_PATH || path.startsWith(`${BASE_PATH}/`)) {
    return path;
  }
  return `${BASE_PATH}${path}`;
}
