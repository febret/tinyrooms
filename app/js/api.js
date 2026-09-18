const JSON_HEADERS = { Accept: "application/json" };

export const PATHS = {
  session: "/api/session",
  bootstrap: "/api/bootstrap",
  createAccount: "/api/auth/create",
  login: "/api/auth/login",
  logout: "/api/auth/logout",
  stickers: "/api/stickers",
  confirmSticker: "/api/stickers/confirm",
  websocket: "/ws",
};

function parseJson(response) {
  return response.headers.get("content-type")?.includes("application/json")
    ? response.json()
    : Promise.resolve({});
}

function errorMessage(body, fallback) {
  if (typeof body?.message === "string" && body.message) return body.message;
  if (typeof body?.detail === "string" && body.detail) return body.detail;
  return fallback;
}

function withJson(body) {
  return {
    headers: { ...JSON_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

/** Call the backend and raise readable errors for non-OK JSON responses. */
async function requestJson(path, options = {}) {
  const { headers: optionHeaders = {}, ...requestOptions } = options;
  const response = await fetch(path, {
    credentials: "include",
    ...requestOptions,
    headers: { ...JSON_HEADERS, ...optionHeaders },
  });
  const body = await parseJson(response);
  if (!response.ok || body?.ok === false) {
    throw new Error(errorMessage(body, `${response.status} ${response.statusText}`.trim()));
  }
  return body;
}

/** Create the HTTP client for session, auth, stickers, bootstrap, and activity bridge calls. */
export function createApiClient() {
  let csrfToken = "";

  function rememberCsrf(token) {
    if (typeof token === "string" && token) csrfToken = token;
  }

  function authHeaders() {
    return csrfToken ? { "X-CSRF-Token": csrfToken } : {};
  }

  return {
    getCsrfToken() {
      return csrfToken;
    },
    async getSession() {
      const body = await requestJson(PATHS.session);
      rememberCsrf(body.csrf_token);
      return body;
    },
    async getBootstrap() {
      const body = await requestJson(PATHS.bootstrap);
      return body;
    },
    async listStickers() {
      const body = await requestJson(PATHS.stickers);
      return Array.isArray(body.stickers) ? body.stickers : [];
    },
    async createAccount(payload) {
      const body = await requestJson(PATHS.createAccount, {
        method: "POST",
        ...withJson(payload),
      });
      rememberCsrf(body.csrf_token);
      return body;
    },
    async login(payload) {
      const body = await requestJson(PATHS.login, {
        method: "POST",
        ...withJson(payload),
      });
      rememberCsrf(body.csrf_token);
      return body;
    },
    async logout() {
      const body = await requestJson(PATHS.logout, {
        method: "POST",
        headers: authHeaders(),
      });
      csrfToken = "";
      return body;
    },
    async confirmSticker(sticker) {
      const request = withJson({ sticker });
      const body = await requestJson(PATHS.confirmSticker, {
        method: "POST",
        ...request,
        headers: { ...request.headers, ...authHeaders() },
      });
      return body;
    },
    async bridgeActivity(activity, type, payload = {}) {
      if (!activity?.bridgeUrl) {
        throw new Error("This activity cannot be bridged right now.");
      }
      const request = withJson({ type, payload });
      return requestJson(activity.bridgeUrl, {
        method: "POST",
        ...request,
        headers: {
          ...request.headers,
          ...authHeaders(),
        },
      });
    },
  };
}
