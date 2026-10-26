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

export function loadFiles() {
  return request("GET", "/api/asset-bakery/files");
}

export function loadFile(fileId) {
  return request("GET", `/api/asset-bakery/file?file_id=${encodeURIComponent(fileId)}`);
}

export function saveFile(payload) {
  return request("PUT", "/api/asset-bakery/file", payload);
}

export function reseedFile(fileId, dryRun = false) {
  return request("POST", "/api/asset-bakery/reseed", { file_id: fileId, dry_run: dryRun });
}

export function startBake(payload) {
  return request("POST", "/api/asset-bakery/bake", payload);
}

export function loadJobs() {
  return request("GET", "/api/asset-bakery/jobs");
}

export function postprocess(payload) {
  return request("POST", "/api/asset-bakery/postprocess", payload);
}

export function outputUrl(fileId, label) {
  return withBase(`/api/asset-bakery/output?file_id=${encodeURIComponent(fileId)}&label=${encodeURIComponent(label)}`);
}
