function csrfToken() {
  const match = document.cookie.split("; ").find((entry) => entry.startsWith("tr_mc_csrf="));
  return match ? decodeURIComponent(match.split("=").slice(1).join("=")) : "";
}

async function request(method, path, options = {}) {
  const opts = { method, credentials: "same-origin", headers: { ...(options.headers || {}) } };
  if (options.json !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(options.json);
  }
  if (options.body !== undefined) opts.body = options.body;
  if (method !== "GET") opts.headers["X-CSRF-Token"] = csrfToken();
  const response = await fetch(path, opts);
  let data = null;
  try {
    data = await response.json();
  } catch (error) {
    data = null;
  }
  if (!response.ok) {
    const message = data && data.message ? data.message : `HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, json) => request("POST", path, { json }),
  patch: (path, json) => request("PATCH", path, { json }),
  del: (path) => request("DELETE", path),
  upload: (path, blob) => request("POST", path, { body: blob, headers: { "Content-Type": "application/zip" } }),
};
