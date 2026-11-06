"""FastAPI application for the filament catalog.

Routes:
  GET  /                      -> the web page (templates/index.html)
  GET  /api/filaments         -> list spools, with optional search/filter
  POST /api/filaments         -> add a spool
  PATCH/api/filaments/{id}    -> edit a spool
  DELETE /api/filaments/{id}  -> remove a spool
  GET  /api/meta              -> dropdown values + the low-stock threshold
  GET  /api/barcode/{code}    -> remembered product details for a scanned barcode
  GET  /api/products          -> every remembered product (barcode -> details)
  GET  /api/sku/{brand}/{code}-> look up filament details from a maker's catalog
  POST /api/ocr               -> read filament details from a box-label photo

Run it with:  uvicorn app.main:app --host 0.0.0.0 --port 8077
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from .database import init_db, get_session, engine
from .models import Filament, FilamentCreate, FilamentUpdate, Product
from . import suppliers
from . import labels

# Fill-level thresholds (percent of a full spool):
#   > CAUTION_PCT          -> "good"    (green)
#   LOW_STOCK_PCT .. 50    -> "caution" (amber, getting low)
#   <= LOW_STOCK_PCT       -> "low"     (red, reorder soon)
# "low_stock" (the filter, the sort-to-top, the reorder flag) means <= LOW_STOCK_PCT.
LOW_STOCK_PCT = 25
CAUTION_PCT = 50

# Largest box-label photo we'll read into memory. 10 MB is plenty for a phone.
MAX_LABEL_BYTES = 10 * 1024 * 1024

# Base material families, checked most-specific first so PETG beats PET and each
# variant maps to its base (PLA+ -> PLA, HSPETG -> PETG, PLA Pro -> PLA).
_FAMILY_BASES = [
    "PETG", "PCTG", "PET",
    "PLA",
    "ABS", "ASA",
    "TPU", "TPE",
    "PVA", "HIPS",
    "NYLON", "PA",
    "PC", "PP",
]


def material_family(material: str) -> str:
    """Map a material name to its base family; fall back to the name itself."""
    norm = "".join(ch for ch in (material or "").upper() if ch.isalnum())
    for base in _FAMILY_BASES:
        if base in norm:
            return base
    return material

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Filament Catalog")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _asset_version() -> str:
    """A short hash of the CSS/JS so the browser refetches them when they change.

    Appended to the asset URLs as ?v=..., this makes every deploy that changes
    app.js or style.css bust the browser cache automatically.
    """
    import hashlib
    h = hashlib.md5()
    for name in ("static/app.js", "static/style.css"):
        try:
            h.update((BASE_DIR / name).read_bytes())
        except OSError:
            pass
    return h.hexdigest()[:8]


ASSET_VERSION = _asset_version()


@app.on_event("startup")
def on_startup() -> None:
    """Make sure the tables exist, then remember products for any barcoded spools.

    The backfill matters when upgrading a database that already had barcoded
    spools before the products table existed: it seeds a Product for each so the
    barcode memory is complete from the first run.
    """
    init_db()
    with Session(engine) as session:
        known = {p.barcode for p in session.exec(select(Product)).all()}
        spools = session.exec(
            select(Filament)
            .where(Filament.barcode.is_not(None))
            .order_by(Filament.updated_at.desc())
        ).all()
        for f in spools:
            if f.barcode and f.barcode not in known:
                upsert_product(session, f, commit=False)
                known.add(f.barcode)
        session.commit()


def upsert_product(session: Session, f: Filament, *, commit: bool = True) -> None:
    """Save (or refresh) the product behind a spool's barcode. No-op without one.

    SQLite's INSERT ... ON CONFLICT makes this safe when two requests save the
    same new barcode at once. Pass commit=False when the caller owns the
    transaction, so the spool and its remembered product are written together.
    """
    if not f.barcode:
        return

    values = {
        "barcode": f.barcode,
        "material": f.material,
        "color": f.color,
        "finish": f.finish,
        "brand": f.brand,
        "spool_weight_g": f.spool_weight_g,
        "nozzle_temp": f.nozzle_temp,
        "bed_temp": f.bed_temp,
        "updated_at": datetime.now(timezone.utc),
    }
    statement = sqlite_insert(Product).values(**values)
    session.execute(
        statement.on_conflict_do_update(
            index_elements=["barcode"],
            set_={key: value for key, value in values.items() if key != "barcode"},
        )
    )
    if commit:
        session.commit()


def clamp_remaining(remaining_g: Optional[int], spool_weight_g: Optional[int]) -> int:
    """Keep grams remaining within the spool's physical capacity.

    The form already limits this, but the API is open and an over-entry would
    otherwise render a >100% fill bar and a misleading percentage.
    """
    weight = max(spool_weight_g or 0, 0)
    return max(0, min(remaining_g or 0, weight))


def serialize(f: Filament) -> dict:
    """Turn a Filament row into a dict with the computed fields the page needs."""
    weight = f.spool_weight_g or 0
    remaining = clamp_remaining(f.remaining_g, weight)
    pct = round((remaining / weight) * 100) if weight else 0
    if pct <= LOW_STOCK_PCT:
        level = "low"
    elif pct < CAUTION_PCT:
        level = "caution"
    else:
        level = "good"
    data = f.model_dump()
    data["remaining_g"] = remaining
    data["remaining_pct"] = pct
    data["level"] = level
    data["low_stock"] = pct <= LOW_STOCK_PCT
    return data


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Serve the single-page catalog UI."""
    response = templates.TemplateResponse(
        "index.html", {"request": request, "asset_version": ASSET_VERSION}
    )
    # Always revalidate the page itself so it carries the current asset version.
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/api/meta")
def meta(session: Session = Depends(get_session)):
    """Distinct materials/brands/finishes (for filter dropdowns) + settings."""
    rows = session.exec(select(Filament)).all()
    materials = sorted({r.material for r in rows if r.material})
    families = sorted({material_family(r.material) for r in rows if r.material})
    brands = sorted({r.brand for r in rows if r.brand})
    finishes = sorted({r.finish for r in rows if r.finish})
    return {
        "materials": materials,
        "families": families,
        "brands": brands,
        "finishes": finishes,
        "low_stock_pct": LOW_STOCK_PCT,
    }


@app.get("/api/filaments")
def list_filaments(
    q: Optional[str] = None,
    material: Optional[str] = None,
    family: Optional[str] = None,
    brand: Optional[str] = None,
    finish: Optional[str] = None,
    low_stock: bool = Query(False),
    session: Session = Depends(get_session),
):
    """Return spools, newest first, narrowed by any filters that were passed."""
    statement = select(Filament)
    if material:
        statement = statement.where(Filament.material == material)
    if brand:
        statement = statement.where(Filament.brand == brand)
    if finish:
        statement = statement.where(Filament.finish == finish)
    rows = session.exec(statement).all()

    results = [serialize(r) for r in rows]

    # Material family (PLA covers PLA/PLA+/PLA Pro/HSPLA+, etc.) — derived, so
    # it's filtered here rather than in the SQL query.
    if family:
        results = [r for r in results if material_family(r["material"]) == family]

    # Free-text search across the human-readable fields.
    if q:
        needle = q.lower()
        results = [
            r for r in results
            if needle in " ".join(
                str(r.get(k) or "") for k in ("material", "color", "finish", "brand", "notes")
            ).lower()
        ]

    if low_stock:
        results = [r for r in results if r["low_stock"]]

    # Low stock first, then by material, then color — handy ordering.
    results.sort(key=lambda r: (not r["low_stock"], r["material"], r["color"]))
    return results


@app.get("/api/barcode/{code}")
def lookup_barcode(code: str, session: Session = Depends(get_session)):
    """Return the product details last saved for a scanned barcode.

    This is the "remember this spool" lookup. It reads the persistent products
    table, not the spool list, so it keeps working even after every spool of a
    product has been used up and deleted. The per-spool amount is not returned.
    """
    prod = session.exec(select(Product).where(Product.barcode == code)).first()
    if not prod:
        raise HTTPException(status_code=404, detail="No saved product for that barcode")
    return {
        "barcode": prod.barcode,
        "material": prod.material,
        "color": prod.color,
        "finish": prod.finish,
        "brand": prod.brand,
        "spool_weight_g": prod.spool_weight_g,
        "nozzle_temp": prod.nozzle_temp,
        "bed_temp": prod.bed_temp,
    }


@app.get("/api/sku/{brand}/{code}")
def lookup_sku(brand: str, code: str):
    """Look up filament details from a manufacturer's code/SKU (e.g. Numakers).

    Fills the Add form from the maker's own catalog instead of typing it in.
    Material/finish/weight are reliable; color is a best guess to confirm.
    """
    try:
        details = suppliers.lookup_sku(brand, code)
    except Exception:
        # Network down, catalog moved, parse error — tell the UI to fall back to manual.
        raise HTTPException(status_code=502, detail=f"Couldn't reach {brand} to look that up.")
    if details is None:
        raise HTTPException(status_code=404, detail=f"No {brand} match for '{code}'.")
    return details


@app.post("/api/ocr")
def ocr_label(image: UploadFile = File(...)):
    """Read filament details from a photo of the box label (OCR).

    Fills the Add form from the printed label — handy for brands like Bambu that
    put everything on the box but have no clean code lookup. Runs on the server
    (Tesseract), no internet needed. Returns 422 if the label isn't recognized.
    """
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=415, detail="Upload a photo of the label.")
    data = image.file.read(MAX_LABEL_BYTES + 1)
    if len(data) > MAX_LABEL_BYTES:
        raise HTTPException(
            status_code=413,
            detail="That photo is too large. Use one under 10 MB.",
        )
    try:
        fields = labels.read_label(data)
    except Exception:
        raise HTTPException(status_code=500, detail="OCR failed on the server.")
    if not fields:
        raise HTTPException(
            status_code=422,
            detail="Couldn't read that label. Try a straight-on, well-lit photo filling the frame.",
        )
    return fields


@app.get("/api/products")
def list_products(session: Session = Depends(get_session)):
    """Every remembered product (barcode -> details). Handy for a future
    management view or an OpenSpool / NFC integration."""
    rows = session.exec(select(Product).order_by(Product.brand, Product.material, Product.color)).all()
    return [r.model_dump() for r in rows]


@app.post("/api/filaments")
def create_filament(payload: FilamentCreate, session: Session = Depends(get_session)):
    """Add a new spool."""
    f = Filament.model_validate(payload)
    f.remaining_g = clamp_remaining(f.remaining_g, f.spool_weight_g)
    session.add(f)
    upsert_product(session, f, commit=False)   # remember this product behind its barcode
    session.commit()                          # spool + product land together
    session.refresh(f)
    return serialize(f)


@app.patch("/api/filaments/{filament_id}")
def update_filament(
    filament_id: int,
    payload: FilamentUpdate,
    session: Session = Depends(get_session),
):
    """Edit an existing spool. Only the fields that were sent get changed."""
    f = session.get(Filament, filament_id)
    if not f:
        raise HTTPException(status_code=404, detail="Spool not found")
    changes = payload.model_dump(exclude_unset=True)
    for key, value in changes.items():
        setattr(f, key, value)
    f.remaining_g = clamp_remaining(f.remaining_g, f.spool_weight_g)
    f.updated_at = datetime.now(timezone.utc)
    session.add(f)
    upsert_product(session, f, commit=False)   # keep the remembered product in step
    session.commit()                          # spool + product land together
    session.refresh(f)
    return serialize(f)


@app.delete("/api/filaments/{filament_id}")
def delete_filament(filament_id: int, session: Session = Depends(get_session)):
    """Remove a spool from the catalog.

    The remembered Product is intentionally left in place, so scanning the
    barcode after a refill still re-imports everything.
    """
    f = session.get(Filament, filament_id)
    if not f:
        raise HTTPException(status_code=404, detail="Spool not found")
    session.delete(f)
    session.commit()
    return {"ok": True}
