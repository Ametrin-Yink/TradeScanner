// web/js/reports.js
import { api, showToast, escapeHtml } from "./api.js";

let reportsCache = null;

function formatSize(bytes) {
  if (bytes == null) return "--";
  const n = Number(bytes);
  if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
  if (n >= 1e3) return Math.round(n / 1e3) + " KB";
  return n + " B";
}

function previewReport(url) {
  const preview = document.getElementById("reportPreview");
  const frame = document.getElementById("reportFrame");
  preview.style.display = "block";
  frame.src = url;
}

export async function loadReports() {
  const tbody = document.getElementById("reportsTableBody");
  const empty = document.getElementById("reportsEmpty");
  try {
    const data = await api("GET", "/reports");
    reportsCache = data.reports || [];
    renderReports(reportsCache);
    empty.style.display = reportsCache.length === 0 ? "flex" : "none";
  } catch (e) {
    tbody.innerHTML =
      '<tr><td colspan="4" style="text-align:center;padding:30px;color:var(--danger)">Failed to load reports: ' +
      e.message +
      "</td></tr>";
  }
}

function renderReports(reports) {
  const tbody = document.getElementById("reportsTableBody");
  tbody.innerHTML = "";
  if (reports.length === 0) {
    document.getElementById("reportsEmpty").style.display = "flex";
    return;
  }
  document.getElementById("reportsEmpty").style.display = "none";
  reports.forEach((r) => {
    const tr = document.createElement("tr");
    const date = r.date
      ? new Date(r.date).toLocaleDateString("en-US", {
          year: "numeric",
          month: "short",
          day: "numeric",
          hour: "2-digit",
          minute: "2-digit",
        })
      : "--";
    const filename = r.filename || "--";
    const url = r.url || "/reports/" + encodeURIComponent(filename);
    tr.innerHTML =
      "<td>" +
      date +
      "</td>" +
      '<td><a href="' +
      escapeHtml(url) +
      '" target="_blank">' +
      escapeHtml(filename) +
      "</a></td>" +
      '<td class="size">' +
      formatSize(r.size) +
      "</td>" +
      '<td><button class="btn btn-sm preview-btn" data-url="' +
      escapeHtml(url) +
      '">Preview</button> ' +
      '<a href="' +
      escapeHtml(url) +
      '" target="_blank" class="btn btn-sm">Open</a></td>';
    tbody.appendChild(tr);
  });
}

// --- Preview Button Delegation ---
document.getElementById("reportsTableBody").addEventListener("click", (e) => {
  const btn = e.target.closest(".preview-btn");
  if (btn) {
    previewReport(btn.dataset.url);
  }
});

// --- Search Filter ---
document.getElementById("reportsSearch").addEventListener("input", () => {
  const q = document.getElementById("reportsSearch").value.toLowerCase();
  if (!reportsCache) return;
  if (!q) {
    renderReports(reportsCache);
    return;
  }
  const filtered = reportsCache.filter(
    (r) =>
      (r.filename && r.filename.toLowerCase().includes(q)) ||
      (r.date &&
        new Date(r.date)
          .toLocaleDateString("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
          })
          .toLowerCase()
          .includes(q)),
  );
  renderReports(filtered);
});
