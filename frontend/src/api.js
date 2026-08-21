const TOKEN_KEY = "wa_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t) => localStorage.setItem(TOKEN_KEY, t);
export const clearToken = () => localStorage.removeItem(TOKEN_KEY);

async function req(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const token = getToken();
  if (token) headers["Authorization"] = `Token ${token}`;

  const res = await fetch(`/api${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    throw new Error("Session expired, please sign in again");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || data.detail || "Request failed");
  return data;
}

export const login = (username, password) =>
  req("/auth/login/", { method: "POST", body: JSON.stringify({ username, password }) });

export const getMe = () => req("/auth/me/");

export const getStatus = () => req("/whatsapp/status/");

export const getQueue = () => req("/whatsapp/queue/");

export const sendMessage = (phone, message) =>
  req("/whatsapp/send/", { method: "POST", body: JSON.stringify({ phone, message }) });

export const getGeminiSettings = () => req("/gemini/settings/");

export const saveGeminiSettings = (payload) =>
  req("/gemini/settings/", { method: "PUT", body: JSON.stringify(payload) });

export const testGemini = (payload) =>
  req("/gemini/test/", { method: "POST", body: JSON.stringify(payload) });

export const getAutomationSettings = () => req("/automation/settings/");

export const saveAutomationSettings = (payload) =>
  req("/automation/settings/", { method: "PUT", body: JSON.stringify(payload) });

export const listApiKeys = () => req("/keys/");

export const createApiKey = (name, type) =>
  req("/keys/", { method: "POST", body: JSON.stringify({ name, type }) });

export const deleteApiKey = (id) => req(`/keys/${id}/`, { method: "DELETE" });
