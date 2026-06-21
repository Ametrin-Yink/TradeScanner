// web/js/tags.js
import { api, showToast, escapeHtml } from "./api.js";

let tags = [];
let selectedTag = null;
let totalStocksUnique = 0;
let searchTimeout = null;

function formatMarketCap(cap) {
  if (cap == null) return "--";
  const n = Number(cap);
  if (n >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  return n.toLocaleString();
}

export async function loadTags() {
  try {
    document.getElementById("tagsList").innerHTML =
      '<div class="empty-state" style="padding:20px"><div class="loading-pulse empty-state-text">Loading tags...</div></div>';
    const data = await api("GET", "/api/config/sectors");
    tags = data.sectors || [];
    totalStocksUnique = data.total_stocks_assigned || 0;
    renderTagList();
    updateScopeFromTags();
    if (selectedTag && tags.find((s) => s.name === selectedTag)) {
      selectTag(selectedTag);
    } else if (tags.length > 0) {
      selectTag(tags[0].name);
    } else {
      selectedTag = null;
      showTagEmpty();
    }
  } catch (e) {
    document.getElementById("tagsList").innerHTML =
      '<div class="empty-state" style="padding:20px;color:var(--danger)">Failed to load tags: ' +
      e.message +
      "</div>";
  }
}

function updateScopeFromTags() {
  const totalTags = tags.length;
  function plural(n, s) {
    return n + " " + s + (n !== 1 ? "s" : "");
  }
  const text =
    plural(totalTags, "tag") + " · " + plural(totalStocksUnique, "stock");
  document.getElementById("scopeText").textContent = text;
  document.getElementById("tagTotalCount").textContent = text;
}

function renderTagList() {
  const list = document.getElementById("tagsList");
  list.innerHTML = "";
  if (tags.length === 0) {
    list.innerHTML =
      '<div class="empty-state" style="padding:20px"><div class="empty-state-text">No tags yet</div></div>';
    return;
  }
  tags.forEach((s) => {
    const card = document.createElement("div");
    card.className = "sector-card" + (selectedTag === s.name ? " active" : "");
    card.setAttribute("tabindex", "0");
    card.dataset.name = s.name;
    let chgHtml = "";
    if (s.daily_change != null) {
      const cls =
        s.daily_change >= 0 ? "sector-change-up" : "sector-change-down";
      const sign = s.daily_change >= 0 ? "+" : "";
      chgHtml =
        '<span class="sector-change ' +
        cls +
        '">' +
        sign +
        s.daily_change.toFixed(2) +
        "%</span>";
    }
    card.innerHTML =
      '<span class="sector-card-name">' +
      escapeHtml(s.name) +
      "</span>" +
      chgHtml +
      '<span class="sector-card-badge">' +
      (s.stock_count || 0) +
      "</span>" +
      '<button class="sector-card-remove" title="Remove tag" data-action="remove-sector">&times;</button>';
    card.addEventListener("click", (e) => {
      if (e.target.dataset.action === "remove-sector") return;
      selectTag(s.name);
    });
    card
      .querySelector('[data-action="remove-sector"]')
      .addEventListener("click", async (e) => {
        e.stopPropagation();
        const btn = e.currentTarget;
        if (btn.dataset.confirming) {
          try {
            await api(
              "DELETE",
              "/api/config/sectors/" + encodeURIComponent(s.name),
            );
            showToast('Tag "' + s.name + '" removed');
            await loadTags();
          } catch (e) {
            showToast(e.message, true);
          }
        } else {
          btn.dataset.confirming = "1";
          btn.textContent = "✖";
          btn.style.color = "var(--danger)";
          setTimeout(() => {
            delete btn.dataset.confirming;
            btn.textContent = "×";
            btn.style.color = "";
          }, 2500);
        }
      });
    list.appendChild(card);
  });
}

function selectTag(name) {
  selectedTag = name;
  renderTagList();
  document.getElementById("tagEmptyState").style.display = "none";
  const detail = document.getElementById("tagDetail");
  detail.style.display = "flex";
  loadTagStocks(name);
}

function showTagEmpty() {
  selectedTag = null;
  document.getElementById("tagEmptyState").style.display = "flex";
  document.getElementById("tagDetail").style.display = "none";
}

async function loadTagStocks(name) {
  const sec = tags.find((s) => s.name === name);
  document.getElementById("detailTagName").textContent = name;
  document.getElementById("detailStockCount").textContent =
    (sec ? sec.stock_count || 0 : 0) + " stocks";
  const etfTag = document.getElementById("detailEtfTag");
  if (sec && sec.etf) {
    etfTag.style.display = "inline";
    etfTag.textContent = sec.etf;
  } else {
    etfTag.style.display = "none";
  }

  const tbody = document.getElementById("stocksTableBody");
  tbody.innerHTML =
    '<tr class="stock-table-empty"><td colspan="5"><div class="loading-pulse">Loading stocks...</div></td></tr>';

  try {
    const data = await api(
      "GET",
      "/api/config/sectors/" + encodeURIComponent(name) + "/stocks",
    );
    renderStockTable(data.stocks || []);
  } catch (e) {
    tbody.innerHTML =
      '<tr class="stock-table-empty"><td colspan="5" style="color:var(--danger)">Failed to load stocks: ' +
      e.message +
      "</td></tr>";
  }
}

function renderStockTable(stocks) {
  const tbody = document.getElementById("stocksTableBody");
  tbody.innerHTML = "";
  if (!stocks || stocks.length === 0) {
    tbody.innerHTML =
      '<tr class="stock-table-empty"><td colspan="5">No stocks assigned to this tag</td></tr>';
    return;
  }
  stocks.sort((a, b) => (a.symbol || "").localeCompare(b.symbol || ""));
  stocks.forEach((st) => {
    const chg = st.ret_5d != null ? st.ret_5d : 0;
    const chgCls = chg >= 0 ? "up" : "down";
    const chgSign = chg >= 0 ? "+" : "";
    const tr = document.createElement("tr");
    tr.innerHTML =
      '<td class="sym">' +
      escapeHtml(st.symbol) +
      "</td>" +
      "<td>" +
      escapeHtml(st.name || st.symbol) +
      "</td>" +
      '<td class="num">$<!--ret--></td><td class="cap">' +
      formatMarketCap(st.market_cap) +
      "</td>" +
      '<td class="actions"><button class="remove-btn" data-action="remove-stock" data-symbol="' +
      escapeHtml(st.symbol) +
      '">Remove</button></td>';
    const removeBtn = tr.querySelector('[data-action="remove-stock"]');
    removeBtn.addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      if (btn.dataset.confirming) {
        try {
          await api(
            "DELETE",
            "/api/config/sectors/" +
              encodeURIComponent(selectedTag) +
              "/stocks/" +
              encodeURIComponent(st.symbol),
          );
          showToast(st.symbol + " removed from " + selectedTag);
          await loadTagStocks(selectedTag);
          await loadTags();
        } catch (e) {
          showToast(e.message, true);
        }
      } else {
        btn.dataset.confirming = "1";
        btn.textContent = "Remove?";
        btn.classList.add("confirming");
        setTimeout(() => {
          delete btn.dataset.confirming;
          btn.textContent = "Remove";
          btn.classList.remove("confirming");
        }, 2500);
      }
    });
    tbody.appendChild(tr);
  });
}

export function initTags() {
  // Module-level listeners below handle setup
}

// --- Add Tag Form ---
document.getElementById("addTagBtn").addEventListener("click", () => {
  document.getElementById("tagActionButtons").style.display = "none";
  document.getElementById("tagAddForm").style.display = "block";
  document.getElementById("newTagName").focus();
});

document.getElementById("cancelTagBtn").addEventListener("click", () => {
  document.getElementById("tagAddForm").style.display = "none";
  document.getElementById("tagActionButtons").style.display = "flex";
  document.getElementById("newTagName").value = "";
  document.getElementById("newTagEtf").value = "";
});

document.getElementById("saveTagBtn").addEventListener("click", async () => {
  const name = document.getElementById("newTagName").value.trim();
  if (!name) {
    showToast("Tag name is required", true);
    return;
  }
  const etf = document.getElementById("newTagEtf").value.trim().toUpperCase();
  try {
    await api("POST", "/api/config/sectors", { name, etf });
    showToast('Tag "' + name + '" created');
    document.getElementById("tagAddForm").style.display = "none";
    document.getElementById("tagActionButtons").style.display = "flex";
    document.getElementById("newTagName").value = "";
    document.getElementById("newTagEtf").value = "";
    await loadTags();
  } catch (e) {
    showToast(e.message, true);
  }
});

// --- Delete Tag ---
document.getElementById("deleteTagBtn").addEventListener("click", async () => {
  if (!selectedTag) return;
  const btn = document.getElementById("deleteTagBtn");
  if (btn.dataset.confirming) {
    try {
      await api(
        "DELETE",
        "/api/config/sectors/" + encodeURIComponent(selectedTag),
      );
      showToast('Tag "' + selectedTag + '" deleted');
      await loadTags();
    } catch (e) {
      showToast(e.message, true);
    }
  } else {
    btn.dataset.confirming = "1";
    btn.textContent = "Confirm Delete";
    setTimeout(() => {
      delete btn.dataset.confirming;
      btn.textContent = "Delete Tag";
    }, 3000);
  }
});

// --- Seed CSV ---
document.getElementById("seedCsvBtn").addEventListener("click", async () => {
  try {
    const data = await api("POST", "/api/config/seed");
    showToast(
      "Seeded " + data.added + " stocks across " + data.sectors + " tags",
    );
    await loadTags();
  } catch (e) {
    showToast(e.message, true);
  }
});

// --- Stock Search ---
document.getElementById("stockSearchInput").addEventListener("input", () => {
  clearTimeout(searchTimeout);
  const q = document.getElementById("stockSearchInput").value.trim();
  const resultsDiv = document.getElementById("searchResults");
  if (q.length < 1) {
    resultsDiv.style.display = "none";
    return;
  }
  searchTimeout = setTimeout(async () => {
    try {
      const data = await api(
        "GET",
        "/api/config/stocks/search?q=" + encodeURIComponent(q),
      );
      renderSearchResults(data.results || []);
    } catch (e) {
      document.getElementById("searchResults").innerHTML =
        '<div class="search-result-item" style="color:var(--danger)">Error: ' +
        e.message +
        "</div>";
      document.getElementById("searchResults").style.display = "block";
    }
  }, 250);
});

document.getElementById("searchResults").addEventListener("click", (e) => {
  const item = e.target.closest(".search-result-item");
  if (!item) return;
  document.getElementById("stockSearchInput").value = item.dataset.symbol;
  document.getElementById("searchResults").style.display = "none";
});

function renderSearchResults(results) {
  const div = document.getElementById("searchResults");
  div.innerHTML = "";
  if (results.length === 0) {
    div.innerHTML =
      '<div class="search-result-item" style="color:var(--text-dim)">No results found</div>';
    div.style.display = "block";
    return;
  }
  results.slice(0, 15).forEach((r) => {
    const item = document.createElement("div");
    item.className = "search-result-item";
    item.dataset.symbol = r.symbol;
    item.innerHTML =
      '<span class="sym">' +
      escapeHtml(r.symbol) +
      "</span>" +
      '<span class="name">' +
      escapeHtml(r.name || "") +
      "</span>" +
      '<span class="cap">' +
      formatMarketCap(r.market_cap) +
      "</span>";
    div.appendChild(item);
  });
  div.style.display = "block";
}

document.addEventListener("click", (e) => {
  const dd = document.getElementById("searchResults");
  if (!e.target.closest(".search-dropdown")) dd.style.display = "none";
});

// --- Add Stock ---
document.getElementById("addStockBtn").addEventListener("click", async () => {
  const input = document.getElementById("stockSearchInput");
  const symbol = input.value.trim().toUpperCase();
  if (!symbol || !selectedTag) return;
  try {
    await api(
      "POST",
      "/api/config/sectors/" + encodeURIComponent(selectedTag) + "/stocks",
      { symbol },
    );
    showToast(symbol + " assigned to " + selectedTag);
    input.value = "";
    document.getElementById("searchResults").style.display = "none";
    await loadTagStocks(selectedTag);
    await loadTags();
  } catch (e) {
    showToast(e.message, true);
  }
});

document.getElementById("stockSearchInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") document.getElementById("addStockBtn").click();
});
