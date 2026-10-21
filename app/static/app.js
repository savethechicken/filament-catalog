"use strict";

// Small helper to grab an element by id.
const $ = (id) => document.getElementById(id);

// Current filter state, read from the controls each time we load.
const controls = {
  search: $("search"),
  family: $("filter-family"),
  brand: $("filter-brand"),
  finish: $("filter-finish"),
  low: $("filter-low"),
};

let lowStockPct = 25; // overwritten by /api/meta

// ---- Loading & rendering -------------------------------------------------

async function loadMeta() {
  const meta = await fetch("/api/meta").then((r) => r.json());
  lowStockPct = meta.low_stock_pct;
  fillOptions(controls.family, "All materials", meta.families);
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
  if (controls.family.value) params.set("family", controls.family.value);
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
      <td data-label="Material"><span class="pill">${escapeHtml(r.material)}</span></td>
      <td data-label="Color">${escapeHtml(r.color)}</td>
      <td data-label="Finish" class="${r.finish ? "" : "empty-cell"}">${r.finish ? escapeHtml(r.finish) : "<span class='grams'>—</span>"}</td>
      <td data-label="Brand" class="${r.brand ? "" : "empty-cell"}">${r.brand ? escapeHtml(r.brand) : "<span class='grams'>—</span>"}</td>
      <td data-label="Remaining">
        <div class="bar ${r.level}">
          <span style="width:${r.remaining_pct}%"></span>
          <span class="bar-label">${r.remaining_pct}%</span>
        </div>
        <div class="grams">${r.remaining_g} / ${r.spool_weight_g} g</div>
      </td>
      <td class="temps ${temps ? "" : "empty-cell"}" data-label="Temps">${temps || "—"}</td>
      <td class="notes ${r.notes ? "" : "empty-cell"}" data-label="Notes">${r.notes ? escapeHtml(r.notes) : ""}</td>
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
  $("f-barcode").value = isEdit ? spool.barcode || "" : "";
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
    barcode: $("f-barcode").value.trim() || null,
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

// ---- Barcode scanning ----------------------------------------------------
// Take a photo of the spool's barcode, decode it in the browser (html5-qrcode),
// then ask the server if we've saved that product before. Works over plain
// http — the file input opens the camera without needing HTTPS.

const scanInput = $("scan-input");
let _onScan = null; // callback waiting for the next decoded photo

// Decode a photo File into a barcode string. Throws if none is found.
async function decodeFile(file) {
  const scanner = new Html5Qrcode("qr-scratch", { verbose: false });
  try {
    return await scanner.scanFile(file, false);
  } finally {
    try { await scanner.clear(); } catch (e) { /* nothing to clean up */ }
  }
}

// Opens the camera and resolves with the decoded code, "" if unreadable, or
// null if the user backed out without taking a photo.
function scanBarcode() {
  return new Promise((resolve) => {
    _onScan = resolve;
    scanInput.click();
  });
}

scanInput.addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = ""; // let the same photo be re-picked later
  const resolve = _onScan;
  _onScan = null;
  if (!resolve) return;
  if (!file) return resolve(null);
  try {
    resolve(await decodeFile(file));
  } catch (err) {
    resolve(""); // no barcode found in the image
  }
});

async function lookupBarcode(code) {
  const res = await fetch(`/api/barcode/${encodeURIComponent(code)}`);
  return res.ok ? res.json() : null; // null = barcode we've never saved
}

function applyProduct(p) {
  $("f-material").value = p.material || "";
  $("f-color").value = p.color || "";
  $("f-finish").value = p.finish || "";
  $("f-brand").value = p.brand || "";
  $("f-weight").value = p.spool_weight_g != null ? p.spool_weight_g : 1000;
  $("f-nozzle").value = p.nozzle_temp != null ? p.nozzle_temp : "";
  $("f-bed").value = p.bed_temp != null ? p.bed_temp : "";
}

const UNREADABLE =
  "Couldn't read a barcode in that photo. Try again — fill the frame, hold steady, good light — or type the number in.";

// Header "Scan": scan straight into a new spool entry.
$("scan-btn").addEventListener("click", async () => {
  const code = await scanBarcode();
  if (code === null) return; // cancelled
  if (code === "") return alert(UNREADABLE);

  const product = await lookupBarcode(code);
  openEditor(null);            // fresh spool (new physical roll)
  $("f-barcode").value = code;
  if (product) {
    applyProduct(product);     // known product -> fields pre-filled
    $("f-remaining").focus();  // you just set how full this one is
  } else {
    $("f-material").focus();   // new product -> fill details once
  }
});

// Dialog "Scan": attach/look up a barcode while the form is open.
$("dialog-scan-btn").addEventListener("click", async () => {
  const code = await scanBarcode();
  if (code === null) return;
  if (code === "") return alert(UNREADABLE);
  $("f-barcode").value = code;
  const product = await lookupBarcode(code);
  // Only fill blanks, so we never clobber something you've already typed.
  if (product && !$("f-material").value.trim()) applyProduct(product);
});

// ---- Wiring --------------------------------------------------------------

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

[controls.search, controls.family, controls.brand, controls.finish, controls.low].forEach((el) =>
  el.addEventListener("input", loadRows)
);

(async function init() {
  await loadMeta();
  await loadRows();
})();
