const JSON_HEADERS = { "Content-Type": "application/json" };

let csrfToken = "";

async function parse(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { response, body };
}

async function request(method, url, payload) {
  const headers = { ...JSON_HEADERS };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const response = await fetch(url, {
    method,
    headers,
    credentials: "same-origin",
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const { body } = await parse(response);
  if (!response.ok) {
    const error = new Error(body?.message || `Request failed (${response.status})`);
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

export function loadDraft() {
  return request("GET", "/api/world-editor/draft");
}

export function saveDraft(draft) {
  return request("PUT", "/api/world-editor/draft", { draft });
}

export function discardDraft() {
  return request("POST", "/api/world-editor/discard", {});
}

export function validateDraft(draft) {
  return request("POST", "/api/world-editor/validate", { draft });
}

export function publishDraft(draft, confirm = false) {
  return request("POST", "/api/world-editor/publish", { draft, confirm });
}

export function loadCardDatabase() {
  return request("GET", "/api/card-database");
}
