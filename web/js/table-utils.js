// web/js/table-utils.js
function makeTablesSortable() {
  document.querySelectorAll("table").forEach((table) => {
    const headers = table.querySelectorAll("th");
    headers.forEach((th, colIdx) => {
      th.style.cursor = "pointer";
      th.title = "Click to sort";
      th.addEventListener("click", () => sortTable(table, colIdx));
    });
  });
}

function sortTable(table, colIdx) {
  const tbody = table.querySelector("tbody");
  if (!tbody) return;

  const rows = Array.from(tbody.querySelectorAll("tr"));
  const currentDir = table.dataset.sortDir === "asc" ? -1 : 1;
  const isNum = table.querySelector("td.num") !== null;

  rows.sort((a, b) => {
    let aVal =
      a.children[colIdx]?.textContent?.replace(/[$,%x]/g, "").trim() || "";
    let bVal =
      b.children[colIdx]?.textContent?.replace(/[$,%x]/g, "").trim() || "";

    if (isNum && colIdx >= 3) {
      // price columns and beyond
      aVal = parseFloat(aVal) || 0;
      bVal = parseFloat(bVal) || 0;
    } else {
      aVal = aVal.toLowerCase();
      bVal = bVal.toLowerCase();
    }

    if (aVal < bVal) return -1 * currentDir;
    if (aVal > bVal) return 1 * currentDir;
    return 0;
  });

  table.dataset.sortDir = currentDir === 1 ? "asc" : "desc";
  rows.forEach((row) => tbody.appendChild(row));

  // Update header indicators
  table
    .querySelectorAll("th")
    .forEach(
      (th) =>
        (th.textContent = th.textContent.replace(" ↑", "").replace(" ↓", "")),
    );
  const th = table.querySelectorAll("th")[colIdx];
  th.textContent += currentDir === 1 ? " ↑" : " ↓";
}

document.addEventListener("DOMContentLoaded", makeTablesSortable);
