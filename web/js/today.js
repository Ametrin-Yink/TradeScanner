// web/js/today.js
import { api, showToast } from "./api.js";

export function initToday() {
  document.getElementById("runScanBtn2").addEventListener("click", async () => {
    const btn = document.getElementById("runScanBtn2");
    const progress = document.getElementById("scanProgress2");
    btn.disabled = true;
    btn.textContent = "Scanning...";
    progress.style.display = "block";
    progress.textContent = "Starting scan...";

    try {
      const data = await api("POST", "/scan", { force: true });
      progress.style.display = "none";
      showToast("Scan complete: " + (data.candidates_found || 0) + " picks");
      await loadToday();
    } catch (e) {
      progress.style.display = "none";
      showToast("Scan failed: " + e.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Scan";
    }
  });
}

export async function loadToday() {
  try {
    const data = await api("GET", "/reports");
    const reports = data.reports || [];
    const container = document.getElementById("todayContent");

    if (reports.length === 0) {
      container.innerHTML =
        '<div class="empty-state"><div class="empty-state-text">No report yet. Click "Run Scan" to generate today\'s report.</div></div>';
      document.getElementById("todayDate").textContent = "";
      return;
    }

    const latest = reports[0];
    document.getElementById("todayDate").textContent = latest.date;
    container.innerHTML =
      '<iframe src="' +
      latest.url +
      '" style="width:100%;height:calc(100vh - 180px);border:none;border-radius:var(--radius);background:var(--ink)" onload="this.style.height=(this.contentWindow.document.body.scrollHeight+40)+\'px\'"></iframe>';
  } catch (e) {
    console.error("Today load failed:", e);
  }
}
