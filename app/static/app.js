"use strict";

// Small helper to grab an element by id.
const $ = (id) => document.getElementById(id);

// Current filter state, read from the controls each time we load.
const controls = {
  search: $("search"),
  material: $("filter-material"),
  brand: $("filter-brand"),
  finish: $("filter-finish"),
  low: $("filter-low"),
};

let lowStockPct = 25; // overwritten by /api/meta

// ---- Loading & rendering -------------------------------------------------

async function loadMeta() {
  const meta = await fetch("/api/meta").then((r) => r.json());
  lowStockPct = meta.low_stock_pct;
  fillOptions(controls.material, "All materials", meta.materials);
  fillOptions(controls.brand, "All brands", meta.brands);
  fillOptions(controls.finish, "All finishes", meta.finishes);
  fillDatalist("material-list", meta.materials);
  fillDatalist("brand-list", meta.brands);
  fillDatalist("finish-list", meta.finishes);
}

function fillOptions(select, allLabel, values) {
  const current = select.value;
  select.innerHTML = `<option value="">${allLabel}</option>`;
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  }
  select.value = current; // keep the user's choice if it still exists
}

function fillDatalist(id, values) {
  $(id).innerHTML = values.map((v) => `<option value="${escapeHtml(v)}">`).join("");
}

async function loadRows() {
  const params = new URLSearchParams();
  if (controls.search.value.trim()) params.set("q", controls.search.value.trim());
  if (controls.material.value) params.set("material", controls.material.value);
  if (controls.brand.value) params.set("brand", controls.brand.value);
  if (controls.finish.value) params.set("finish", controls.finish.value);
  if (controls.low.checked) params.set("low_stock", "true");

  const rows = await fetch("/api/filaments?" + params.toString()).then((r) => r.json());
  renderRows(rows);
}

function renderRows(rows) {
  const tbody = $("rows");
  tbody.innerHTML = "";
  $("count").textContent = `${rows.length} spool${rows.length === 1 ? "" : "s"}`;
  $("empty").hidden = rows.length > 0;

  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.classList.add(r.level); // "good" | "caution" | "low" — drives the row accent

    const temps = [r.nozzle_temp ? `${r.nozzle_temp}°` : null, r.bed_temp ? `${r.bed_temp}°` : null]
      .filter(Boolean)
      .join(" / ");

    tr.innerHTML = `
      <td><span class="pill">${escapeHtml(r.material)}</span></td>
      <td>${escapeHtml(r.color)}</td>
      <td>${r.finish ? escapeHtml(r.finish) : "<span class='grams'>—</span>"}</td>
      <td>${r.brand ? escapeHtml(r.brand) : "<span class='grams'>—</span>"}</td>
      <td>
        <div class="bar ${r.level}">
          <span style="width:${r.remaining_pct}%"></span>
          <span class="bar-label">${r.remaining_pct}%</span>
        </div>
        <div class="grams">${r.remaining_g} / ${r.spool_weight_g} g</div>
      </td>
      <td class="temps">${temps || "—"}</td>
      <td class="notes">${r.notes ? escapeHtml(r.notes) : ""}</td>
      <td class="row-actions">
        <button class="link" data-edit="${r.id}">Edit</button>
        <button class="link danger" data-del="${r.id}">Delete</button>
      </td>`;
    tbody.appendChild(tr);
  }

  tbody.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => openEditor(rows.find((x) => x.id == b.dataset.edit)))
  );
  tbody.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", () => removeSpool(b.dataset.del))
  );
}

// ---- The Add / Edit dialog ----------------------------------------------

const dialog = $("editor");

function openEditor(spool) {
  const isEdit = Boolean(spool);
  $("editor-title").textContent = isEdit ? "Edit spool" : "Add spool";
  $("f-id").value = isEdit ? spool.id : "";
  $("f-material").value = isEdit ? spool.material : "";
  $("f-color").value = isEdit ? spool.color : "";
  $("f-finish").value = isEdit ? spool.finish || "" : "";
  $("f-brand").value = isEdit ? spool.brand || "" : "";
  $("f-weight").value = isEdit ? spool.spool_weight_g : 1000;
  $("f-remaining").value = isEdit ? spool.remaining_g : 1000;
  $("f-fraction").value = "";
  $("f-nozzle").value = isEdit && spool.nozzle_temp != null ? spool.nozzle_temp : "";
  $("f-bed").value = isEdit && spool.bed_temp != null ? spool.bed_temp : "";
  $("f-notes").value = isEdit ? spool.notes || "" : "";
  dialog.showModal();
}

// Picking a fraction fills in grams from the full-spool weight.
$("f-fraction").addEventListener("change", (e) => {
  const frac = e.target.value;
  if (frac === "") return;
  const weight = Number($("f-weight").value) || 0;
  $("f-remaining").value = Math.round(weight * Number(frac));
});

// If the spool weight changes while a fraction is selected, recompute grams.
$("f-weight").addEventListener("input", () => {
  const frac = $("f-fraction").value;
  if (frac !== "") $("f-remaining").value = Math.round((Number($("f-weight").value) || 0) * Number(frac));
});

$("add-btn").addEventListener("click", () => openEditor(null));
$("cancel-btn").addEventListener("click", () => dialog.close());

$("editor-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    material: $("f-material").value.trim(),
    color: $("f-color").value.trim(),
    finish: $("f-finish").value.trim() || null,
    brand: $("f-brand").value.trim() || null,
    spool_weight_g: Number($("f-weight").value) || 0,
    remaining_g: Number($("f-remaining").value) || 0,
    nozzle_temp: $("f-nozzle").value ? Number($("f-nozzle").value) : null,
    bed_temp: $("f-bed").value ? Number($("f-bed").value) : null,
    notes: $("f-notes").value.trim() || null,
  };

  const id = $("f-id").value;
  const url = id ? `/api/filaments/${id}` : "/api/filaments";
  const method = id ? "PATCH" : "POST";
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert("Could not save: " + (await res.text()));
    return;
  }
  dialog.close();
  await loadMeta();
  await loadRows();
});

async function removeSpool(id) {
  if (!confirm("Delete this spool from the catalog?")) return;
  await fetch(`/api/filaments/${id}`, { method: "DELETE" });
  await loadMeta();
  await loadRows();
}

// ---- Wiring --------------------------------------------------------------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

[controls.search, controls.material, controls.brand, controls.finish, controls.low].forEach((el) =>
  el.addEventListener("input", loadRows)
);

(async function init() {
  await loadMeta();
  await loadRows();
})();
