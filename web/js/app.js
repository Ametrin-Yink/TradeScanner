// web/js/app.js
import { api } from "./api.js";
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

// --- Toast ---
export { showToast } from "./api.js";

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

// --- Init ---
document.addEventListener("DOMContentLoaded", async () => {
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
  initHash();

  // Auth key (if API_KEY is set)
  const { fetchApiKey } = await import("./api.js");
  await fetchApiKey();

  // Init modules (set up event listeners)
  initTags();
  initScan();

  // Load data
  await loadTags();
  loadStrategies();
  loadReports();
  if (window.location.hash === "#scan") loadScanStatus();
  if (window.location.hash === "#simulation") loadSimulation();
});
