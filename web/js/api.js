// web/js/api.js
const KEY_STORAGE = "tradescanner_api_key";

export function getApiKey() {
  return (
    sessionStorage.getItem(KEY_STORAGE) || localStorage.getItem(KEY_STORAGE)
  );
}

export function setApiKey(key) {
  sessionStorage.setItem(KEY_STORAGE, key);
  localStorage.setItem(KEY_STORAGE, key);
}

export function clearApiKey() {
  sessionStorage.removeItem(KEY_STORAGE);
  localStorage.removeItem(KEY_STORAGE);
}

export function isLoggedIn() {
  return !!getApiKey();
}

// Migrate: if key exists in sessionStorage but not localStorage, mirror it
export function syncKeyToLocalStorage() {
  const key = sessionStorage.getItem(KEY_STORAGE);
  if (key && !localStorage.getItem(KEY_STORAGE)) {
    localStorage.setItem(KEY_STORAGE, key);
  }
}

export async function verifyKey(key) {
  const res = await fetch("/api/config/auth-key", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key: key }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  return data.valid === true;
}

export async function api(method, url, body) {
  const opts = { method, headers: {} };
  const key = getApiKey();
  if (key) {
    opts.headers["Authorization"] = "Bearer " + key;
  }
  if (method === "GET" || method === "HEAD") {
    // Content-Type not needed for GET/HEAD
  } else {
    opts.headers["Content-Type"] = "application/json";
  }
  if (body !== undefined && body !== null) {
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(url, opts);
  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (e) {
    data = text;
  }
  if (!res.ok) {
    if (res.status === 401) {
      clearApiKey();
      window.location.reload();
    }
    throw new Error(
      data && typeof data === "object" && data.message
        ? data.message
        : "Request failed (" + res.status + ")",
    );
  }
  return data;
}

export function showToast(msg, isError) {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = "toast" + (isError ? " toast-error" : "");
  el.textContent = (isError ? "✖ " : "✔ ") + msg;
  container.appendChild(el);
  requestAnimationFrame(() => el.classList.add("show"));
  setTimeout(() => {
    el.classList.remove("show");
    setTimeout(() => el.remove(), 400);
  }, 2500);
}

export function escapeHtml(str) {
  if (str == null) return "";
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}
