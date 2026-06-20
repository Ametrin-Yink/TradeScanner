// web/js/strategies.js
import { api, showToast, escapeHtml } from "./api.js";

let strategiesData = null;
let originalStrategies = null;
let dirtyStrategyKeys = new Set();

const LETTERS = ["A1", "A2", "B", "C", "D", "E", "F", "G", "H"];
const SKIP_KEYS = new Set(["position_tiers", "sector_etfs", "enabled"]);

function humanizeKey(key) {
  return key
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function directionTag(dir) {
  if (!dir) return "";
  const d = String(dir).toUpperCase();
  if (d === "LONG") return "long";
  if (d === "SHORT") return "short";
  return "both";
}

export async function loadStrategies() {
  const accordion = document.getElementById("strategyAccordion");
  const loading = document.getElementById("strategiesLoading");
  try {
    const data = await api("GET", "/api/config/strategies");
    strategiesData = JSON.parse(JSON.stringify(data.strategies));
    originalStrategies = JSON.parse(JSON.stringify(data.strategies));
    dirtyStrategyKeys.clear();
    updateSaveBar();
    loading.style.display = "none";
    accordion.style.display = "flex";
    renderStrategies();
  } catch (e) {
    loading.innerHTML =
      '<div class="empty-state-text" style="color:var(--danger)">Failed to load strategies: ' +
      e.message +
      "</div>";
  }
}

function renderStrategies() {
  const accordion = document.getElementById("strategyAccordion");
  accordion.innerHTML = "";
  const keys = Object.keys(strategiesData);
  let idx = 0;
  keys.forEach((key) => {
    const strat = strategiesData[key];
    if (!strat || typeof strat !== "object") return;
    const letter = LETTERS[idx] || "?";
    idx++;
    const dir = directionTag(strat.direction);

    const card = document.createElement("div");
    card.className = "strategy-card";
    card.dataset.strategyKey = key;

    const header = document.createElement("div");
    header.className = "strategy-card-header";
    header.setAttribute("tabindex", "0");
    header.innerHTML =
      '<span class="strategy-badge">' +
      letter +
      "</span>" +
      '<span class="strategy-name">' +
      humanizeKey(key) +
      "</span>" +
      (dir
        ? '<span class="strategy-direction ' + dir + '">' + dir + "</span>"
        : "") +
      '<span class="strategy-chevron">&#9660;</span>';

    const body = document.createElement("div");
    body.className = "strategy-card-body";
    const inner = document.createElement("div");
    inner.className = "strategy-card-body-inner";

    const fields = document.createElement("div");
    fields.className = "strategy-fields";

    Object.keys(strat).forEach((param) => {
      const val = strat[param];
      if (SKIP_KEYS.has(param)) {
        const fld = document.createElement("div");
        fld.className = "strategy-field";
        fld.innerHTML =
          "<label>" +
          humanizeKey(param) +
          "</label>" +
          '<div class="readonly-block">' +
          escapeHtml(JSON.stringify(val, null, 1)) +
          "</div>";
        fields.appendChild(fld);
        return;
      }
      const valType = typeof val;
      if (valType !== "number" && valType !== "string") return;
      if (param === "direction") return;

      const fld = document.createElement("div");
      fld.className = "strategy-field";
      fld.dataset.param = param;

      const label = document.createElement("label");
      label.textContent = humanizeKey(param);

      let input;
      if (valType === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.step = val % 1 === 0 ? "1" : "0.01";
        input.value = val;
      } else {
        input = document.createElement("input");
        input.type = "text";
        input.value = val;
      }

      input.addEventListener("input", () => {
        const newVal =
          input.type === "number" ? parseFloat(input.value) : input.value;
        const origVal = (originalStrategies[key] || {})[param];
        if (input.type === "number" && isNaN(newVal)) return;
        strategiesData[key][param] = newVal;
        if (newVal === origVal) {
          dirtyStrategyKeys.delete(key + "." + param);
          fld.classList.remove("dirty");
        } else {
          dirtyStrategyKeys.add(key + "." + param);
          fld.classList.add("dirty");
        }
        updateSaveBar();
      });

      fld.appendChild(label);
      fld.appendChild(input);

      let hint = "";
      if (param.includes("period") || param === "window") hint = "(bars)";
      else if (
        param.includes("threshold") ||
        param.includes("min_") ||
        param.includes("max_")
      )
        hint = "(%)";
      else if (param.includes("atr_mult") || param.includes("mult"))
        hint = "(x ATR)";
      else if (param.includes("risk") || param.includes("stop")) hint = "(%)";
      if (hint) {
        const hintEl = document.createElement("div");
        hintEl.className = "unit-hint";
        hintEl.textContent = hint;
        fld.appendChild(hintEl);
      }

      fields.appendChild(fld);
    });

    inner.appendChild(fields);
    body.appendChild(inner);
    card.appendChild(header);
    card.appendChild(body);
    accordion.appendChild(card);

    header.addEventListener("click", () => {
      card.classList.toggle("expanded");
    });
    header.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        card.classList.toggle("expanded");
      }
    });
  });

  if (accordion.firstChild) accordion.firstChild.classList.add("expanded");
}

function updateSaveBar() {
  const bar = document.getElementById("saveBar");
  bar.classList.toggle("dirty", dirtyStrategyKeys.size > 0);
}

// --- Save Strategies ---
document
  .getElementById("saveStrategiesBtn")
  .addEventListener("click", async () => {
    try {
      await api("PUT", "/api/config/strategies", {
        strategies: strategiesData,
      });
      originalStrategies = JSON.parse(JSON.stringify(strategiesData));
      dirtyStrategyKeys.clear();
      updateSaveBar();
      document
        .querySelectorAll(".strategy-field.dirty")
        .forEach((el) => el.classList.remove("dirty"));
      showToast("Strategies saved");
    } catch (e) {
      showToast(e.message, true);
    }
  });
