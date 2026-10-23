import { withBase } from "../../app/js/base-path.js";

const JSON_HEADERS = { "Content-Type": "application/json" };

let csrfToken = "";

async function request(method, url, payload) {
  const headers = { ...JSON_HEADERS };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(withBase(url), {
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

export function loadCatalog(roomId) {
  const query = roomId ? `?room_id=${encodeURIComponent(roomId)}` : "";
  return request("GET", `/api/cutscene-catalog${query}`);
}

export function previewCutscene(body) {
  return request("POST", "/api/cutscene-catalog/preview", body);
}
