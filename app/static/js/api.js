let currentUser = null;
let getIdToken = async () => null;

export function setUser(user, tokenGetter) {
  currentUser = user;
  getIdToken = tokenGetter || (async () => null);
}

export function getUser() {
  return currentUser;
}

export async function authHeaders() {
  const headers = {};
  if (window.DEV_AUTH && currentUser) {
    headers["X-Dev-UID"] = currentUser.uid;
    return headers;
  }
  const t = await getIdToken();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  return headers;
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
  }
}

export async function api(method, path, body) {
  const headers = await authHeaders();
  const opts = { method, headers };
  if (body !== undefined) {
    if (body instanceof FormData) {
      opts.body = body;
    } else {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const resp = await fetch(path, opts);
  let data = {};
  try { data = await resp.json(); } catch {}
  if (!resp.ok) throw new ApiError(resp.status, data.detail || `HTTP ${resp.status}`);
  return data;
}

export function wsUrl(code) {
  return new Promise(async (resolve) => {
    while (!currentUser) await new Promise(r => setTimeout(r, 100));
    const proto = location.protocol === "https:" ? "wss" : "ws";
    if (window.DEV_AUTH) {
      resolve(`${proto}://${location.host}/api/rooms/ws/${code}?uid=${encodeURIComponent(currentUser.uid)}&name=${encodeURIComponent(currentUser.displayName || "")}`);
    } else {
      const t = await getIdToken();
      resolve(`${proto}://${location.host}/api/rooms/ws/${code}?token=${encodeURIComponent(t)}`);
    }
  });
}
