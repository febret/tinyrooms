const JSON_HEADERS = { "Content-Type": "application/json" };

let csrfToken = "";

async function request(method, url, payload) {
  const headers = { ...JSON_HEADERS };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(url, {
    method,
    headers,
    credentials: "same-origin",
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (!response.ok) {
    const error = new Error(body?.message || body?.detail || `Request failed (${response.status})`);
    error.status = response.status;
    error.body = body || {};
    throw error;
  }
  return body;
}

export async function loadSession() {
  const body = await request("GET", "/api/session");
  csrfToken = body?.csrf_token || "";
  return body;
}

export function loadCatalog() {
  return request("GET", "/api/prop-editor/catalog");
}

export function loadProp(kind, source, propId) {
  const query = new URLSearchParams({ kind, source, prop_id: propId });
  return request("GET", `/api/prop-editor/prop?${query}`);
}

export function saveProp(payload) {
  return request("PUT", "/api/prop-editor/prop", payload);
}

export function loadEffects() {
  return request("GET", "/api/prop-editor/effects");
}

export function loadEffect(effectId) {
  const query = new URLSearchParams({ effect_id: effectId });
  return request("GET", `/api/prop-editor/effect?${query}`);
}

export function saveEffect(payload) {
  return request("PUT", "/api/prop-editor/effect", payload);
}

export function reloadWorld() {
  return request("POST", "/api/prop-editor/reload", {});
}
