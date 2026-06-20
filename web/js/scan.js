// web/js/scan.js
import { api, showToast } from "./api.js";

export async function loadScanStatus() {
  try {
    const data = await api("GET", "/api/scan/status");
    if (data.last_scan) {
      document.getElementById("statLastRun").textContent = data.last_scan.date;
      document.getElementById("statStatus").textContent = data.last_scan.status;
      document.getElementById("statStocks").textContent =
        data.last_scan.stocks || "--";
      document.getElementById("statCands").textContent =
        data.last_scan.candidates || "--";
    }
  } catch (e) {
    // silently ignore
  }
}

export function initScan() {
  // Module-level listeners below handle setup
}

// --- Run Scan ---
document.getElementById("runScanBtn").addEventListener("click", async () => {
  const btn = document.getElementById("runScanBtn");
  const result = document.getElementById("scanResult");
  btn.disabled = true;
  btn.textContent = "Scanning...";
  result.style.display = "block";
  result.innerHTML =
    '<div class="loading-pulse">Running scan pipeline -- this takes several minutes...</div>';
  try {
    const data = await api("POST", "/scan");
    result.innerHTML =
      '<div style="color:var(--accent);font-weight:600">Scan complete!</div>' +
      '<div style="margin-top:8px;color:var(--text-secondary)">Candidates found: ' +
      data.candidates_found +
      "</div>" +
      '<div style="color:var(--text-secondary)">Report: <a href="' +
      data.report_path +
      '" target="_blank" style="color:var(--accent)">' +
      data.report_path +
      "</a></div>";
    showToast("Scan complete: " + data.candidates_found + " candidates");
    loadScanStatus();
  } catch (e) {
    result.innerHTML =
      '<div style="color:var(--danger)">Scan failed: ' + e.message + "</div>";
    showToast("Scan failed: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run Full Scan";
  }
});
