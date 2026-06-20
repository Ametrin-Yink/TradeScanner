// web/js/api.js
let _apiKey = null;

export async function fetchApiKey() {
  try {
    const res = await fetch("/api/config/auth-key");
    if (res.ok) {
      const data = await res.json();
      _apiKey = data.key;
    }
  } catch (e) {
    console.warn("Could not fetch API key:", e);
  }
}

export async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (_apiKey) {
    opts.headers["Authorization"] = "Bearer " + _apiKey;
  }
  if (body) {
    opts.headers["Content-Type"] = "application/json";
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
    throw new Error(
      data && typeof data === "object" && data.error
        ? data.error
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
