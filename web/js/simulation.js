// web/js/simulation.js
import { api, escapeHtml } from "./api.js";

export async function loadSimulation() {
  await Promise.all([loadSummary(), loadActive(), loadClosed()]);
}

async function loadSummary() {
  try {
    const data = await api("GET", "/api/simulation/summary");
    const container = document.getElementById("simSummary");
    container.innerHTML = "";
    const cards = [
      { label: "TOTAL TRADES", value: data.total_trades },
      { label: "WIN RATE", value: data.win_rate + "%" },
      {
        label: "AVG R/TRADE",
        value: (data.avg_r >= 0 ? "+" : "") + data.avg_r.toFixed(2) + "R",
      },
      {
        label: "PROFIT FACTOR",
        value:
          data.profit_factor === Infinity
            ? "--"
            : data.profit_factor.toFixed(2),
      },
      {
        label: "EXPECTANCY",
        value:
          (data.expectancy >= 0 ? "+" : "") + data.expectancy.toFixed(2) + "R",
      },
    ];
    cards.forEach((c) => {
      const card = document.createElement("div");
      card.className = "scan-stat-card";
      card.innerHTML =
        '<div class="scan-stat-label">' +
        c.label +
        "</div>" +
        '<div class="scan-stat-value">' +
        c.value +
        "</div>";
      container.appendChild(card);
    });
  } catch (e) {
    console.error("Simulation summary failed:", e);
  }
}

async function loadActive() {
  try {
    const data = await api("GET", "/api/simulation/active");
    const tbody = document.getElementById("simActiveBody");
    tbody.innerHTML = "";
    if (!data.positions || data.positions.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="6" style="text-align:center;padding:20px;color:var(--text-secondary)">No active positions</td></tr>';
      return;
    }
    data.positions.forEach((p) => {
      const tr = document.createElement("tr");
      const pnlCls =
        (p.pnl_pct || 0) >= 0
          ? 'style="color:var(--volt)"'
          : 'style="color:var(--ember)"';
      const pnlSign = (p.pnl_pct || 0) >= 0 ? "+" : "";
      tr.innerHTML =
        '<td class="sym">' +
        escapeHtml(p.symbol) +
        "</td>" +
        "<td>$" +
        p.entry_price.toFixed(2) +
        "</td>" +
        "<td>" +
        (p.current_price ? "$" + p.current_price.toFixed(2) : "--") +
        "</td>" +
        "<td " +
        pnlCls +
        ">" +
        (p.pnl_pct != null ? pnlSign + p.pnl_pct.toFixed(2) + "%" : "--") +
        "</td>" +
        "<td>" +
        (p.days_open || 0) +
        "d</td>" +
        '<td><div style="background:var(--bg-elevated);border-radius:3px;height:6px;width:100%"><div style="background:var(--accent);height:100%;width:' +
        (p.progress || 0) +
        '%;border-radius:3px"></div></div></td>';
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Active positions failed:", e);
  }
}

async function loadClosed(filter) {
  try {
    const url =
      "/api/simulation/closed" +
      (filter && filter !== "all" ? "?outcome=" + filter : "");
    const data = await api("GET", url);
    const tbody = document.getElementById("simClosedBody");
    tbody.innerHTML = "";
    if (!data.positions || data.positions.length === 0) {
      tbody.innerHTML =
        '<tr><td colspan="7" style="text-align:center;padding:20px;color:var(--text-secondary)">No closed positions</td></tr>';
      return;
    }
    data.positions.forEach((p) => {
      const tr = document.createElement("tr");
      const outcomeCls =
        p.outcome === "win"
          ? "color:var(--volt)"
          : p.outcome === "loss"
            ? "color:var(--ember)"
            : "color:var(--text-secondary)";
      const pnlCls =
        (p.pnl_dollars || 0) >= 0 ? "color:var(--volt)" : "color:var(--ember)";
      const pnlSign = (p.pnl_dollars || 0) >= 0 ? "+" : "";
      tr.innerHTML =
        "<td>" +
        (p.close_date || "--") +
        "</td>" +
        '<td class="sym">' +
        escapeHtml(p.symbol) +
        "</td>" +
        "<td>$" +
        p.entry_price.toFixed(2) +
        "</td>" +
        "<td>$" +
        (p.close_price ? p.close_price.toFixed(2) : "--") +
        "</td>" +
        '<td style="' +
        outcomeCls +
        ';font-weight:600">' +
        p.outcome.toUpperCase() +
        "</td>" +
        '<td style="' +
        pnlCls +
        '">' +
        pnlSign +
        "$" +
        Math.abs(p.pnl_dollars || 0).toFixed(2) +
        "</td>" +
        '<td style="' +
        pnlCls +
        '">' +
        (p.pnl_r != null ? pnlSign + p.pnl_r.toFixed(1) + "R" : "--") +
        "</td>";
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Closed positions failed:", e);
  }
}

// Filter handler
document.addEventListener("DOMContentLoaded", () => {
  const filterEl = document.getElementById("simFilter");
  if (filterEl) {
    filterEl.addEventListener("change", () => loadClosed(filterEl.value));
  }
});
