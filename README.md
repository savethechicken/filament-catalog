# Filament Catalog

A small web app for cataloging your 3D-printing filament. Runs on your homelab
server and is reachable from any browser in the house.

Built with **FastAPI + SQLite** (same stack as your Homepage Editor). No build
step, no external database — the whole catalog lives in one `filament.db` file.

## What it tracks

Per spool: material, color, finish, brand, full-spool weight, grams remaining,
nozzle/bed temps, and notes. The list shows a fill bar, flags anything at or
below **25%** as low stock, and lets you search and filter.

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
volume), so it survives image updates. Copy that file to back up, or delete it
and recreate the container to start fresh. Running locally without Docker, it's
`filament.db` in the project root.

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
  requirements.txt
  data/filament.db        your data (Docker volume; gitignored)
```

## Tweaks you might want

- **Fill-color thresholds**: `LOW_STOCK_PCT` (red, 25) and `CAUTION_PCT`
  (amber, 50) near the top of `app/main.py`.
- **Port**: change the `8077` mapping in `docker-compose.yml` (left side).
