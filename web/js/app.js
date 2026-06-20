// web/js/app.js
import { api, isLoggedIn, setApiKey, verifyKey, showToast } from "./api.js";
import { loadTags, initTags } from "./tags.js";
import { loadReports } from "./reports.js";
import { loadSimulation } from "./simulation.js";
import { loadToday, initToday } from "./today.js";
import { loadConfig, initConfig } from "./config.js";

export function switchTab(name) {
  document
    .querySelectorAll(".tab-pane")
    .forEach((p) => p.classList.remove("active"));
  document
    .querySelectorAll(".navbar-tab")
    .forEach((t) => t.classList.remove("active"));
  const pane = document.getElementById("pane-" + name);
  if (pane) pane.classList.add("active");
  const tab = document.querySelector('.navbar-tab[data-tab="' + name + '"]');
  if (tab) tab.classList.add("active");
  window.location.hash = name;
  if (name === "today") loadToday();
  if (name === "simulation") loadSimulation();
  if (name === "config") loadConfig();
}

export function updateScope(tagCount, stockCount) {
  const p = (n, s) => n + " " + s + (n !== 1 ? "s" : "");
  document.getElementById("scopeText").textContent =
    p(tagCount, "tag") + " · " + p(stockCount, "stock");
  document.getElementById("tagTotalCount").textContent =
    p(tagCount, "tag") + " · " + p(stockCount, "stock");
}

function showLogin() {
  document.getElementById("loginOverlay").style.display = "flex";
  document.getElementById("appMain").style.display = "none";
  document.getElementById("loginError").style.display = "none";
}

function hideLogin() {
  document.getElementById("loginOverlay").style.display = "none";
  document.getElementById("appMain").style.display = "flex";
}

async function handleLogin() {
  const key = document.getElementById("apiKeyInput").value.trim();
  if (!key) return;
  const btn = document.getElementById("loginBtn");
  btn.disabled = true;
  btn.textContent = "Verifying...";
  try {
    const valid = await verifyKey(key);
    if (valid) {
      setApiKey(key);
      hideLogin();
      await initApp();
    } else {
      document.getElementById("loginError").style.display = "block";
    }
  } catch (e) {
    document.getElementById("loginError").style.display = "block";
  } finally {
    btn.disabled = false;
    btn.textContent = "Login";
  }
}

async function initApp() {
  initTags();
  initToday();
  initConfig();
  await loadTags();
  loadReports();
  await loadToday();
  if (window.location.hash === "#simulation") loadSimulation();
  if (window.location.hash === "#config") loadConfig();
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".navbar-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  function initHash() {
    const hash = window.location.hash.replace("#", "");
    if (["today", "tags", "reports", "simulation", "config"].includes(hash))
      switchTab(hash);
  }
  window.addEventListener("hashchange", initHash);

  document.getElementById("loginBtn").addEventListener("click", handleLogin);
  document.getElementById("apiKeyInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleLogin();
  });
  document.getElementById("logoutBtn").addEventListener("click", () => {
    import("./api.js").then((m) => {
      m.clearApiKey();
      window.location.reload();
    });
  });

  if (isLoggedIn()) {
    hideLogin();
    initApp().then(() => initHash());
  } else showLogin();
});
