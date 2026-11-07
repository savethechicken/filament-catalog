# Filament Catalog

A small web app for cataloging your 3D-printing filament. Runs on your homelab
server and is reachable from any browser in the house.

Built with **FastAPI + SQLite** (same stack as your Homepage Editor). No build
step, no external database — the whole catalog lives in one `filament.db` file.

## What it tracks

Per spool: material, color, finish, brand, barcode, full-spool weight, grams
remaining, nozzle/bed temps, and notes. The list shows a fill bar, flags
anything at or below **25%** as low stock, and lets you search and filter.
Grams remaining are clamped to the spool's full weight, so the bar always reads
between 0 and 100%.

The material filter groups by **family**: picking **PLA** shows every variant
(PLA, PLA+, PLA Pro, HSPLA+); **PETG** covers PETG, PETG+, HSPETG; and so on.
Families are derived automatically from the material name (see `material_family`
in `app/main.py`), so new variants slot into the right group with no setup.

On the desktop table, **click a column header** (Material, Color, Finish, Brand,
Remaining) to sort A→Z; click again to reverse to Z→A. Blanks sort last.

## Export to a spreadsheet

Tap **⬇ Export CSV** in the header to download the current view as a `.csv` file
you can open in Excel, Google Sheets, or LibreOffice. The export uses the same
search and filters as the page, so it always contains exactly the spools you're
looking at — filter to **PLA** and **Low stock only**, and you get a shopping
list.

The file includes the spool id, material, color, finish, brand, barcode, full
weight, grams remaining, fill percentage, temps, notes, and created/updated
timestamps. It's written as UTF-8 with a BOM so Excel shows accented characters
correctly. The same download is available directly at
`GET /api/export.csv` (it accepts the same `q`, `family`, `brand`, `finish`, and
`low_stock` query parameters as `/api/filaments`).

## Log what you used

Each row has a **Use…** action. Pick a preset amount (10/25/50/100/250 g) or
type the grams you used, see the resulting total, and hit **Remove grams**. The
spool's remaining amount drops immediately and is clamped at zero, so logging
more than is left empties the spool rather than producing a negative number.
This is the quick alternative to opening the edit dialog and retyping the total.

The underlying endpoint is `POST /api/filaments/{id}/use` with a JSON body like
`{"grams": 50}`.

## Scan a barcode

Tap **📷 Scan**, photograph the spool's barcode, and the app decodes it right in
the browser (no internet or app needed — the decoders are bundled: jsQR for QR
codes, html5-qrcode for 1D barcodes like UPC/EAN). Then it does a "remember this
spool" lookup:

- **Seen this barcode before?** Material, color, brand, weight and temps fill in
  automatically — just set how full this spool is and save.
- **New barcode?** Fill the details in once; every future scan of that code
  auto-fills from what you entered.

It gets smarter the more you scan, so rebuying the same Inland spools becomes a
near one-tap add. Taking the photo works over plain `http`, so no HTTPS setup is
needed on your home network.

**The barcode memory outlives the spool.** Product details (material, color,
brand, weight, temps) are saved in a separate `products` table, so when a roll
is used up and you delete it from the list, the barcode is *not* forgotten —
scan it on your next refill and everything re-imports.

## Known products

Tap **📚 Products** in the header to see every remembered barcode. Each row
shows the material, color, finish/brand, and barcode, with two actions:

- **Edit** — correct the details a future scan should pre-fill. Existing spools
  keep their own values; only the barcode memory changes.
- **Forget** — remove the remembered product entirely, so the next scan starts
  from a blank form. Spools already in the catalog are untouched.

This is the fix for a bad barcode memory (for example, a color the upfront
lookup guessed wrong). The same operations are available as
`PATCH /api/products/{barcode}` and `DELETE /api/products/{barcode}`, and
`GET /api/products` lists everything remembered — the natural hook for a future
OpenSpool / NFC tie-in.

## Look up by maker code

Some brands print a code/SKU you can use to pull the details from their site. In
the Add/Edit dialog, pick the brand, enter the code (or tap **📷** to scan the
brand's QR, which just holds the SKU), and hit **Look up** — it fills material,
finish, color, weight and brand from the manufacturer's catalog. Scanning the QR
auto-runs the lookup, so it's one step.

- **Numakers** is supported now (their Shopify catalog is matched by SKU, e.g.
  `PLMT11KPAA` → PLA / Matte / Midnight Shade). Material, finish and weight are
  reliable; **color is a best guess** to confirm, since their catalog data is a
  bit inconsistent.
- The lookup runs **server-side**, so the container needs outbound internet. If
  it can't reach the maker, you just get a message and fall back to typing it in.
- Resolvers live in `app/suppliers.py`, one per brand — see `RESOLVERS`.

## Scan a box label (OCR)

Some brands (e.g. Bambu Lab) print everything on the box but have no clean code
lookup. In the Add/Edit dialog, tap **📷 Scan box label**, photograph the label,
and the server OCRs it and fills the form: material, finish, color, weight,
nozzle temp, the barcode, and notes (filament code, temp range, model).

- Runs **server-side with Tesseract** (bundled in the Docker image), so it needs
  no internet. For local dev without Docker, install Tesseract and point
  `TESSERACT_CMD` at it.
- Uploads are capped at **10 MB / 40 megapixels**. That's well above a normal
  phone photo, but stops an oversized image from tying up the server. Files that
  aren't images are rejected before OCR runs.
- Parsers live in `app/labels.py`, one per brand in `BRAND_PARSERS`; the label's
  text picks the brand automatically. Bambu Lab is supported now.
- Take a straight-on, well-lit photo that fills the frame. Color is a best guess
  to confirm; everything else is read from the printed fields.

## Run it on your PC (to try it out)

Clone the repo, then from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app.seed          # loads the starter catalog (only on an empty database)
uvicorn app.main:app --reload --port 8077
```

Then open http://localhost:8077

## Run the tests

The repo includes a pytest smoke suite that drives the real app through
FastAPI's `TestClient`. It covers the page, spool CRUD, barcode memory, gram
clamping, the OCR upload guards, SQLite settings, and the CSV export. Tests use
a temporary SQLite database, so they never touch your `filament.db`, and they
don't need Tesseract or Docker.

```powershell
pip install -r requirements-dev.txt
python -m pytest
```

`requirements-dev.txt` adds `pytest` and `httpx` on top of the runtime
requirements; the Docker image still installs only `requirements.txt`.

## Run it on `mediacenter` from GitHub (Docker — same as Homepage Editor)

Every push to `main` on GitHub rebuilds the Docker image and publishes it to
GHCR (`ghcr.io/savethechicken/filament-catalog:latest`) automatically. The
server only ever pulls the finished image.

**First install** (once, in your homelab tools folder, e.g. `/opt/docker`):

```bash
cd /opt/docker
git clone https://github.com/savethechicken/filament-catalog.git
cd filament-catalog
docker compose up -d
```

Then from any computer in the house, open `http://mediacenter:8077`
(or the server IP, e.g. `http://192.168.1.224:8077`).

**Update after you push changes** (the same flow as Homepage Editor):

```bash
cd /opt/docker/filament-catalog
git pull
docker compose pull && docker compose up -d --force-recreate
```

The footer at the bottom of the page shows the running version and short commit
hash, so you can confirm the new image is live.

`restart: unless-stopped` in `docker-compose.yml` keeps it running across
reboots.

## Make a change

Edit the code locally, then:

```bash
git add -A
git commit -m "describe your change"
git push
```

GitHub builds the new image; run the update commands above on the server to pull
it. (To test a change on the server without waiting for GHCR, use
`docker compose up -d --build` to build from the pulled source.)

## Back up your data

Your catalog lives in **`filament.db`**. In Docker that's mounted at
`./data/filament.db` inside the project folder on the server (the `data/`
volume), so it survives image updates. Running locally without Docker, it's
`filament.db` in the project root.

SQLite runs in **WAL mode** (write-ahead logging), so recent writes can sit in
`filament.db-wal` until they're checkpointed. You'll see `filament.db-wal` and
`filament.db-shm` beside the database — that's normal, and copying
`filament.db` alone while the app is running can miss the latest changes. WAL
also lets several devices use the catalog at the same time without locking each
other out.

The simplest clean backup is to stop the app, copy the file, and start it again:

```bash
cd /opt/docker/filament-catalog
docker compose stop
cp data/filament.db ~/filament-$(date +%F).db
docker compose start
```

Or take an online backup without downtime, then copy it out:

```bash
docker compose exec filament-catalog python -c "import sqlite3; s=sqlite3.connect('/data/filament.db'); d=sqlite3.connect('/data/backup.db'); s.backup(d); d.close(); s.close()"
cp data/backup.db ~/filament-$(date +%F).db && rm data/backup.db
```

To start fresh, stop the container, delete `data/filament.db` (and any
`-wal`/`-shm` siblings), and recreate it with `docker compose up -d`. The
starter catalog is seeded again on the next start.

## Project layout

```
filament-catalog/
  app/
    main.py        FastAPI routes (the API + the page)
    models.py      the Filament table and form shapes
    database.py    SQLite connection + table creation
    seed.py        your starting 15 spools
    templates/
      index.html   the page
    static/
      app.js       loads/edits spools in the browser
      style.css
  Dockerfile              builds the container image
  docker-compose.yml      how the server runs it
  .github/workflows/      GitHub Action that builds + publishes the image
  tests/
    conftest.py           temp database + TestClient fixture
    test_smoke.py         API, CSV export, and UI smoke tests
  pytest.ini
  requirements.txt
  requirements-dev.txt    test-only dependencies
  data/filament.db        your data (Docker volume; gitignored)
```

## Tweaks you might want

- **Fill-color thresholds**: `LOW_STOCK_PCT` (red, 25) and `CAUTION_PCT`
  (amber, 50) near the top of `app/main.py`.
- **Version in the footer**: `APP_VERSION` near the top of `app/main.py`; bump it
  when you make a notable change. The short commit hash beside it is injected at
  image build time (`BUILD_SHA`), so the page always says exactly which build is
  deployed.
- **Port**: change the `8077` mapping in `docker-compose.yml` (left side).
