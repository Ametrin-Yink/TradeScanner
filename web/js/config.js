// web/js/config.js
import { api, showToast } from "./api.js";

async function loadSettings() {
  try {
    const resp = await api("GET", "/api/config/settings");
    if (resp.settings) {
      document.getElementById("configScanTime").value =
        resp.settings.scan_time || "06:00";
      document.getElementById("configAccountValue").value =
        resp.settings.account_value || 50000;
      document.getElementById("configRiskPct").value =
        resp.settings.risk_per_trade_pct || 1.0;
      document.getElementById("configAiKey").value =
        resp.settings.ai_api_key || "";
      document.getElementById("configAiModel").value =
        resp.settings.ai_model || "deepseek-chat";
    }
  } catch (e) {
    /* defaults are fine */
  }
}

export function initConfig() {
  document
    .getElementById("saveConfigBtn")
    .addEventListener("click", async () => {
      const settings = {
        scan_time: document.getElementById("configScanTime").value || "06:00",
        account_value:
          parseInt(document.getElementById("configAccountValue").value) ||
          50000,
        risk_per_trade_pct:
          parseFloat(document.getElementById("configRiskPct").value) || 1.0,
        ai_api_key: document.getElementById("configAiKey").value,
        ai_model: document.getElementById("configAiModel").value,
      };
      try {
        await api("PUT", "/api/config/settings", settings);
        const el = document.getElementById("configSaved");
        el.style.display = "inline";
        setTimeout(() => (el.style.display = "none"), 2000);
        showToast("Settings saved");
      } catch (e) {
        showToast("Save failed: " + e.message, true);
      }
    });
}

export async function loadConfig() {
  await loadSettings();
}
