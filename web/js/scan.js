// web/js/scan.js
import { api, showToast } from "./api.js";

export async function loadScanStatus() {
  try {
    const data = await api("GET", "/status");
    if (data.last_scan) {
      document.getElementById("statLastRun").textContent =
        data.last_scan.date || "--";
      document.getElementById("statStatus").textContent =
        data.last_scan.status || (data.last_scan.date ? "completed" : "--");
      document.getElementById("statStocks").textContent =
        data.last_scan.stocks || "--";
      document.getElementById("statCands").textContent =
        data.last_scan.candidates || "--";
    }
  } catch (e) {
    /* silent */
  }
}

export function initScan() {
  document.getElementById("runScanBtn").addEventListener("click", async () => {
    const btn = document.getElementById("runScanBtn");
    const result = document.getElementById("scanResult");
    const progress = document.getElementById("scanProgress");
    btn.disabled = true;
    btn.textContent = "Scanning...";
    progress.style.display = "block";
    result.style.display = "none";

    let pollInterval;
    try {
      // Start scan
      const scanPromise = api("POST", "/scan");

      // Poll progress
      pollInterval = setInterval(async () => {
        try {
          const status = await api("GET", "/status");
          if (status.last_scan && status.last_scan.status === "running") {
            progress.textContent =
              "Scan in progress... " +
              (status.last_scan.duration
                ? Math.round(status.last_scan.duration) + "s elapsed"
                : "");
          }
        } catch (e) {
          /* polling errors are non-fatal */
        }
      }, 5000);

      const data = await scanPromise;
      clearInterval(pollInterval);
      progress.style.display = "none";

      result.style.display = "block";
      result.innerHTML =
        '<div style="color:var(--accent);font-weight:600">Scan complete!</div>' +
        '<div style="margin-top:8px;color:var(--text-secondary)">Report: <a href="' +
        data.report_path +
        '" target="_blank" style="color:var(--accent)">' +
        data.report_path +
        "</a></div>";
      showToast("Scan complete");
      loadScanStatus();
    } catch (e) {
      clearInterval(pollInterval);
      progress.style.display = "none";
      result.style.display = "block";
      result.innerHTML =
        '<div style="color:var(--danger)">Scan failed: ' + e.message + "</div>";
      showToast("Scan failed: " + e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Full Scan";
    }
  });
}
