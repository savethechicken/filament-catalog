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

// Column sort (Excel-style). null column = default order (low stock first).
const sortState = { column: null, dir: "asc" };

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
  const params = currentParams();
  const rows = await fetch("/api/filaments?" + params.toString()).then((r) => r.json());
  renderRows(rows);
}

// The filter controls as a query string, shared by the table and the CSV export
// so the download always matches what is on screen.
function currentParams() {
  const params = new URLSearchParams();
  if (controls.search.value.trim()) params.set("q", controls.search.value.trim());
  if (controls.family.value) params.set("family", controls.family.value);
  if (controls.brand.value) params.set("brand", controls.brand.value);
  if (controls.finish.value) params.set("finish", controls.finish.value);
  if (controls.low.checked) params.set("low_stock", "true");
  return params;
}

// Sort by the clicked column; blanks always sort last. Numeric for the fill bar.
function sortRows(rows) {
  if (!sortState.column) return rows;
  const col = sortState.column;
  const dir = sortState.dir === "desc" ? -1 : 1;
  const numeric = col === "remaining_pct";
  return [...rows].sort((a, b) => {
    if (numeric) return ((a[col] || 0) - (b[col] || 0)) * dir;
    const av = (a[col] || "").toString().toLowerCase();
    const bv = (b[col] || "").toString().toLowerCase();
    if (av === "" && bv !== "") return 1; // blanks last
    if (bv === "" && av !== "") return -1;
    if (av < bv) return -1 * dir;
    if (av > bv) return 1 * dir;
    return 0;
  });
}

function updateSortIndicators() {
  document.querySelectorAll("th[data-sort]").forEach((th) => {
    th.classList.toggle("sort-asc", sortState.column === th.dataset.sort && sortState.dir === "asc");
    th.classList.toggle("sort-desc", sortState.column === th.dataset.sort && sortState.dir === "desc");
  });
}

function renderRows(rows) {
  rows = sortRows(rows);
  updateSortIndicators();
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
        <button class="link" data-use="${r.id}">Use…</button>
        <button class="link" data-edit="${r.id}">Edit</button>
        <button class="link danger" data-del="${r.id}">Delete</button>
      </td>`;
    tbody.appendChild(tr);
  }

  tbody.querySelectorAll("[data-use]").forEach((b) =>
    b.addEventListener("click", () => openUse(rows.find((x) => x.id == b.dataset.use)))
  );
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

// ---- Quick "used grams" --------------------------------------------------
// Open a small dialog to subtract a number of grams from one spool. The server
// clamps at zero, so over-logging empties the spool rather than going negative.

const useDialog = $("use-dialog");
let useTarget = null;

function openUse(spool, grams = 50, note = "") {
  useTarget = spool;
  $("use-summary").textContent =
    `${spool.material} · ${spool.color} — ${spool.remaining_g} of ${spool.spool_weight_g} g left`;
  const suggested = Math.round(Number(grams));
  $("use-grams").value = Math.max(1, Number.isFinite(suggested) ? suggested : 50);
  const source = $("use-source");
  source.hidden = !note;
  source.textContent = note;
  updateUsePreview();
  useDialog.showModal();
  $("use-grams").select();
}

function updateUsePreview() {
  if (!useTarget) return;
  const grams = Math.max(0, Math.floor(Number($("use-grams").value) || 0));
  const after = Math.max(0, useTarget.remaining_g - grams);
  const pct = useTarget.spool_weight_g
    ? Math.round((after / useTarget.spool_weight_g) * 100)
    : 0;
  $("use-after").textContent = `After removing ${grams} g: ${after} g left (${pct}%).`;
}

$("use-grams").addEventListener("input", updateUsePreview);

document.querySelectorAll("[data-use-grams]").forEach((b) =>
  b.addEventListener("click", () => {
    $("use-grams").value = b.dataset.useGrams;
    updateUsePreview();
    $("use-grams").focus();
  })
);

$("use-cancel-btn").addEventListener("click", () => useDialog.close());

$("use-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const grams = Math.floor(Number($("use-grams").value));
  if (!useTarget || !Number.isFinite(grams) || grams <= 0) return;
  const res = await fetch(`/api/filaments/${useTarget.id}/use`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ grams }),
  });
  if (!res.ok) {
    alert("Could not update: " + (await res.text()));
    return;
  }
  useDialog.close();
  await loadRows();
});

// ---- Usage from a sliced file -------------------------------------------
// Read the slicer's own per-filament estimate from a .gcode or .gcode.3mf,
// let the user pick which spool each slot maps to, then hand the grams to the
// Use dialog. The slicer number is only a suggestion until confirmed there.

const sliceDialog = $("slice-dialog");
const sliceFile = $("slice-file");

$("slice-btn").addEventListener("click", () => {
  $("slice-results").innerHTML = "";
  $("slice-status").hidden = true;
  $("slice-status").textContent = "";
  sliceFile.value = "";
  sliceDialog.showModal();
});

$("slice-close-btn").addEventListener("click", () => sliceDialog.close());
$("slice-pick-btn").addEventListener("click", () => sliceFile.click());

sliceFile.addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = ""; // let the same file be picked again
  if (file) await loadSliceUsage(file);
});

async function loadSliceUsage(file) {
  const status = $("slice-status");
  $("slice-results").innerHTML = "";
  status.hidden = false;
  status.textContent = `Reading ${file.name}…`;

  try {
    const body = new FormData();
    body.append("file", file);
    const res = await fetch("/api/slice/usage", { method: "POST", body });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      status.textContent = data.detail || "Couldn't read that file.";
      return;
    }
    if (!data.filaments || !data.filaments.length) {
      status.textContent = "No filament usage found in that file.";
      return;
    }

    const spools = await fetch("/api/filaments").then((r) => r.json());
    if (!spools.length) {
      status.textContent = "Add a spool first, then load the slice again.";
      return;
    }

    const count = data.filaments.length;
    status.textContent =
      `${file.name}: ${data.total_g} g total across ${count} ` +
      `filament${count === 1 ? "" : "s"}.`;
    renderSliceResults(data.filaments, spools);
  } catch (err) {
    status.textContent = "Upload failed — is the server online?";
  }
}

function normalizeHex(value) {
  const text = String(value || "").trim();
  return /^#[0-9a-f]{3,8}$/i.test(text) ? text : null;
}

// Pick the obvious spool, but only when it really is obvious. Material names
// must match; a hex color is used only when both sides actually store hex.
function matchSpool(slot, spools) {
  const material = String(slot.type || "").toLowerCase();
  const hex = normalizeHex(slot.color);
  let candidates = material
    ? spools.filter((s) => String(s.material || "").toLowerCase() === material)
    : [];
  if (hex) {
    const exact = candidates.filter((s) => normalizeHex(s.color) === hex);
    if (exact.length) candidates = exact;
  }
  if (candidates.length === 1) return candidates[0];
  if (!material && spools.length === 1) return spools[0]; // type unknown, only one candidate
  return null;
}

function renderSliceResults(filaments, spools) {
  const box = $("slice-results");
  box.innerHTML = "";
  const sorted = [...spools].sort((a, b) => (b.remaining_g || 0) - (a.remaining_g || 0));

  filaments.forEach((slot, index) => {
    const hex = normalizeHex(slot.color);
    const swatch = hex ? `<span class="swatch" style="background:${hex}"></span>` : "";
    const profile = slot.profile
      ? `<span class="slice-detail">${escapeHtml(slot.profile)}</span>`
      : "";
    const options = sorted
      .map(
        (s) =>
          `<option value="${s.id}">#${s.id} — ${escapeHtml(s.material)} / ` +
          `${escapeHtml(s.color)} (${s.remaining_g} g left)</option>`
      )
      .join("");

    const row = document.createElement("div");
    row.className = "slice-row";
    row.innerHTML = `
      <div class="slice-main">
        <span class="pill">${escapeHtml(slot.type || "Filament")}</span>
        ${swatch}
        <strong>${slot.grams} g</strong>
        ${profile}
      </div>
      <div class="slice-target">
        <select data-slot-select="${index}">
          <option value="">Choose a spool…</option>
          ${options}
        </select>
        <button class="link" data-slot-apply="${index}">Use…</button>
      </div>`;
    box.appendChild(row);

    const match = matchSpool(slot, sorted);
    if (match) row.querySelector(`[data-slot-select="${index}"]`).value = match.id;
  });

  box.querySelectorAll("[data-slot-apply]").forEach((button) =>
    button.addEventListener("click", () => {
      const index = Number(button.dataset.slotApply);
      const select = box.querySelector(`[data-slot-select="${index}"]`);
      const spool = sorted.find((s) => String(s.id) === select.value);
      if (!spool) return alert("Choose which spool this filament came from.");
      const slot = filaments[index];
      const note = `Slicer estimate: ${slot.grams} g` + (slot.type ? ` of ${slot.type}` : "") + ".";
      sliceDialog.close();
      openUse(spool, slot.grams, note);
    })
  );
}

// ---- Known products ------------------------------------------------------
// The barcode memory behind "remember this spool". Editing here only changes
// what a future scan pre-fills; existing spools keep their own values.

const productsDialog = $("products-dialog");
const productEditor = $("product-editor");
let products = [];
let productTarget = null;

async function openProducts() {
  await loadProducts();
  productsDialog.showModal();
}

async function loadProducts() {
  products = await fetch("/api/products").then((r) => r.json());
  const list = $("products-list");
  list.innerHTML = "";
  $("products-empty").hidden = products.length > 0;

  products.forEach((p, index) => {
    const row = document.createElement("div");
    row.className = "product-row";
    const details = [p.finish, p.brand].filter(Boolean).map(escapeHtml).join(" · ");
    row.innerHTML = `
      <div class="product-main">
        <span class="pill">${escapeHtml(p.material)}</span>
        <strong>${escapeHtml(p.color)}</strong>
        ${details ? `<span class="product-details">${details}</span>` : ""}
        <code class="product-barcode">${escapeHtml(p.barcode)}</code>
      </div>
      <div class="product-actions">
        <button class="link" data-edit-product="${index}">Edit</button>
        <button class="link danger" data-forget-product="${index}">Forget</button>
      </div>`;
    list.appendChild(row);
  });

  list.querySelectorAll("[data-edit-product]").forEach((b) =>
    b.addEventListener("click", () =>
      openProductEditor(products[Number(b.dataset.editProduct)])
    )
  );
  list.querySelectorAll("[data-forget-product]").forEach((b) =>
    b.addEventListener("click", () =>
      forgetProduct(products[Number(b.dataset.forgetProduct)])
    )
  );
}

function openProductEditor(product) {
  productTarget = product;
  $("product-barcode").textContent = `Barcode ${product.barcode}`;
  $("p-material").value = product.material || "";
  $("p-color").value = product.color || "";
  $("p-finish").value = product.finish || "";
  $("p-brand").value = product.brand || "";
  $("p-weight").value = product.spool_weight_g != null ? product.spool_weight_g : 1000;
  $("p-nozzle").value = product.nozzle_temp != null ? product.nozzle_temp : "";
  $("p-bed").value = product.bed_temp != null ? product.bed_temp : "";
  productEditor.showModal();
}

async function forgetProduct(product) {
  const label = `${product.material} ${product.color} (${product.barcode})`;
  if (
    !confirm(
      `Forget ${label}?\n\nSpools already in the catalog keep their details. ` +
        `This only changes what a future scan pre-fills.`
    )
  )
    return;
  const res = await fetch(`/api/products/${encodeURIComponent(product.barcode)}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    alert("Could not forget: " + (await res.text()));
    return;
  }
  await loadProducts();
}

$("products-btn").addEventListener("click", openProducts);
$("products-close-btn").addEventListener("click", () => productsDialog.close());
$("product-cancel-btn").addEventListener("click", () => productEditor.close());

$("product-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!productTarget) return;
  const payload = {
    material: $("p-material").value.trim(),
    color: $("p-color").value.trim(),
    finish: $("p-finish").value.trim() || null,
    brand: $("p-brand").value.trim() || null,
    spool_weight_g: Number($("p-weight").value) || 1000,
    nozzle_temp: $("p-nozzle").value ? Number($("p-nozzle").value) : null,
    bed_temp: $("p-bed").value ? Number($("p-bed").value) : null,
  };
  const res = await fetch(`/api/products/${encodeURIComponent(productTarget.barcode)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    alert("Could not save: " + (await res.text()));
    return;
  }
  productEditor.close();
  await loadProducts();
});

// ---- Barcode scanning ----------------------------------------------------
// Take a photo of the spool's barcode, decode it in the browser (html5-qrcode),
// then ask the server if we've saved that product before. Works over plain
// http — the file input opens the camera without needing HTTPS.

const scanInput = $("scan-input");
let _onScan = null; // callback waiting for the next decoded photo

// Decode a photo File into a code string. Throws if nothing is found.
// QR first (jsQR — reliable on still photos, used by Numakers' SKU QR), then
// fall back to html5-qrcode for 1D barcodes (UPC/EAN on spool labels).
async function decodeFile(file) {
  const qr = await decodeQR(file);
  if (qr) return qr;

  const scanner = new Html5Qrcode("qr-scratch", { verbose: false });
  try {
    return await scanner.scanFile(file, false);
  } finally {
    try { await scanner.clear(); } catch (e) { /* nothing to clean up */ }
  }
}

function loadImage(url) {
  return new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = rej;
    i.src = url;
  });
}

// jsQR on one region of an image at a given max dimension. Returns text or null.
function jsQROnce(img, sx, sy, sw, sh, cap) {
  const scale = Math.min(1, cap / Math.max(sw, sh));
  const w = Math.max(1, Math.round(sw * scale));
  const h = Math.max(1, Math.round(sh * scale));
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(img, sx, sy, sw, sh, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h);
  const r = jsQR(data.data, w, h, { inversionAttempts: "attemptBoth" });
  return r && r.data ? r.data : null;
}

// Read a QR from a photo. Native BarcodeDetector first (robust, same engine the
// phone's camera uses, works over http), then jsQR at several scales and a
// center crop so a small-in-frame or large photo still decodes. Returns null.
async function decodeQR(file) {
  // 1) Native detector (Android Chrome etc.)
  try {
    if ("BarcodeDetector" in window) {
      let ok = true;
      if (BarcodeDetector.getSupportedFormats) {
        ok = (await BarcodeDetector.getSupportedFormats()).includes("qr_code");
      }
      if (ok) {
        const detector = new BarcodeDetector({ formats: ["qr_code"] });
        const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
        const codes = await detector.detect(bitmap);
        if (bitmap.close) bitmap.close();
        if (codes && codes.length) return codes[0].rawValue;
      }
    }
  } catch (e) {
    /* fall through to jsQR */
  }

  // 2) jsQR at a few sizes, then a center crop for a QR that's small in frame.
  const url = URL.createObjectURL(file);
  try {
    const img = await loadImage(url);
    const { width: W, height: H } = img;
    for (const cap of [2000, 1200, 800]) {
      const hit = jsQROnce(img, 0, 0, W, H, cap);
      if (hit) return hit;
    }
    const cw = W * 0.6;
    const ch = H * 0.6;
    const crop = jsQROnce(img, (W - cw) / 2, (H - ch) / 2, cw, ch, 1200);
    if (crop) return crop;
    return null;
  } catch (e) {
    return null;
  } finally {
    URL.revokeObjectURL(url);
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

// Fill the form from the manufacturer's catalog using the code in the SKU field.
async function lookupSku() {
  const brand = $("f-sku-brand").value;
  const code = $("f-sku").value.trim();
  if (!code) return;
  const btn = $("sku-lookup-btn");
  btn.disabled = true;
  btn.textContent = "Looking…";
  try {
    const res = await fetch(`/api/sku/${encodeURIComponent(brand)}/${encodeURIComponent(code)}`);
    if (!res.ok) {
      const msg = (await res.json().catch(() => ({}))).detail || "Lookup failed.";
      return alert(msg);
    }
    applyProduct(await res.json()); // fills material/finish/color/brand/weight
    $("f-remaining").focus();       // then set how full this spool is
  } catch (e) {
    alert("Lookup failed — is the server online and able to reach the internet?");
  } finally {
    btn.disabled = false;
    btn.textContent = "Look up";
  }
}

// "Look up" button: look up whatever SKU is typed in.
$("sku-lookup-btn").addEventListener("click", lookupSku);

// "Scan box label": photograph the label, OCR it on the server, fill the form.
const ocrInput = $("ocr-input");
$("label-scan-btn").addEventListener("click", () => ocrInput.click());
ocrInput.addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const btn = $("label-scan-btn");
  btn.disabled = true;
  btn.textContent = "Reading…";
  try {
    const fd = new FormData();
    fd.append("image", file);
    const res = await fetch("/api/ocr", { method: "POST", body: fd });
    if (!res.ok) {
      const msg = (await res.json().catch(() => ({}))).detail || "Couldn't read the label.";
      return alert(msg);
    }
    const d = await res.json();
    applyProduct(d);                              // material/finish/color/brand/weight/temps
    if (d.barcode) $("f-barcode").value = d.barcode;
    if (d.notes) $("f-notes").value = d.notes;
    $("f-remaining").focus();                     // then set how full this spool is
  } catch (err) {
    alert("Label scan failed — is the server online?");
  } finally {
    btn.disabled = false;
    btn.textContent = "📷 Scan box label";
  }
});

// Maker-code "Scan": read the brand's QR (which just holds the SKU), then look it up.
$("sku-scan-btn").addEventListener("click", async () => {
  const code = await scanBarcode();
  if (code === null) return; // cancelled
  if (code === "") return alert(UNREADABLE);
  $("f-sku").value = code.trim();
  await lookupSku();
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

// "Export CSV": download the rows that match the filters currently applied.
$("export-btn").addEventListener("click", () => {
  window.location.href = "/api/export.csv?" + currentParams().toString();
});

// Click a column header to sort; click again to reverse (A→Z ↔ Z→A).
document.querySelectorAll("th[data-sort]").forEach((th) => {
  th.addEventListener("click", () => {
    const col = th.dataset.sort;
    if (sortState.column === col) {
      sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
    } else {
      sortState.column = col;
      sortState.dir = "asc";
    }
    loadRows();
  });
});

(async function init() {
  await loadMeta();
  await loadRows();
})();
