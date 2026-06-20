// web/js/app.js
import { api, isLoggedIn, setApiKey, verifyKey, showToast } from "./api.js";
import { loadTags, initTags } from "./tags.js";
import { loadStrategies } from "./strategies.js";
import { loadReports } from "./reports.js";
import { initScan, loadScanStatus } from "./scan.js";
import { loadSimulation } from "./simulation.js";

// --- Tab Routing ---
export function switchTab(name) {
  document
    .querySelectorAll(".tab-pane")
    .forEach((p) => p.classList.remove("active"));
  document
    .querySelectorAll(".navbar-tab")
    .forEach((t) => t.classList.remove("active"));
  document.getElementById("pane-" + name).classList.add("active");
  document
    .querySelector('.navbar-tab[data-tab="' + name + '"]')
    .classList.add("active");
  window.location.hash = name;
  if (name === "scan") loadScanStatus();
  if (name === "simulation") loadSimulation();
}

// --- Scope Indicator ---
export function updateScope(tagCount, stockCount) {
  function plural(n, s) {
    return n + " " + s + (n !== 1 ? "s" : "");
  }
  document.getElementById("scopeText").textContent =
    plural(tagCount, "tag") + " · " + plural(stockCount, "stock");
  document.getElementById("tagTotalCount").textContent =
    plural(tagCount, "tag") + " · " + plural(stockCount, "stock");
}

// --- Login ---
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
  const input = document.getElementById("apiKeyInput");
  const key = input.value.trim();
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

// --- Init ---
async function initApp() {
  initTags();
  initScan();
  await loadTags();
  loadStrategies();
  loadReports();
  if (window.location.hash === "#scan") loadScanStatus();
  if (window.location.hash === "#simulation") loadSimulation();
}

document.addEventListener("DOMContentLoaded", () => {
  // Tab click handlers
  document.querySelectorAll(".navbar-tab").forEach((tab) => {
    tab.addEventListener("click", () => switchTab(tab.dataset.tab));
  });

  // Hash routing
  function initHash() {
    const hash = window.location.hash.replace("#", "");
    if (
      ["tags", "strategies", "reports", "scan", "simulation"].includes(hash)
    ) {
      switchTab(hash);
    }
  }
  window.addEventListener("hashchange", initHash);

  // Login button
  document.getElementById("loginBtn").addEventListener("click", handleLogin);
  document.getElementById("apiKeyInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") handleLogin();
  });

  // Logout
  document.getElementById("logoutBtn").addEventListener("click", () => {
    import("./api.js").then((m) => {
      m.clearApiKey();
      window.location.reload();
    });
  });

  // Check login state
  if (isLoggedIn()) {
    hideLogin();
    initApp().then(() => initHash());
  } else {
    showLogin();
  }
});
