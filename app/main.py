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

Run it with:  uvicorn app.main:app --host 0.0.0.0 --port 8077
"""

from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from sqlmodel import Session, select

from .database import init_db, get_session, engine
from .models import Filament, FilamentCreate, FilamentUpdate, Product

# Fill-level thresholds (percent of a full spool):
#   > CAUTION_PCT          -> "good"    (green)
#   LOW_STOCK_PCT .. 50    -> "caution" (amber, getting low)
#   <= LOW_STOCK_PCT       -> "low"     (red, reorder soon)
# "low_stock" (the filter, the sort-to-top, the reorder flag) means <= LOW_STOCK_PCT.
LOW_STOCK_PCT = 25
CAUTION_PCT = 50

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Filament Catalog")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


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
                upsert_product(session, f)
                known.add(f.barcode)


def upsert_product(session: Session, f: Filament) -> None:
    """Save (or refresh) the product behind a spool's barcode. No-op without one."""
    if not f.barcode:
        return
    prod = session.exec(select(Product).where(Product.barcode == f.barcode)).first()
    if prod is None:
        prod = Product(barcode=f.barcode, material=f.material, color=f.color)
    prod.material = f.material
    prod.color = f.color
    prod.finish = f.finish
    prod.brand = f.brand
    prod.spool_weight_g = f.spool_weight_g
    prod.nozzle_temp = f.nozzle_temp
    prod.bed_temp = f.bed_temp
    prod.updated_at = datetime.now(timezone.utc)
    session.add(prod)
    session.commit()


def serialize(f: Filament) -> dict:
    """Turn a Filament row into a dict with the two computed fields the page needs."""
    weight = f.spool_weight_g or 0
    pct = round((f.remaining_g / weight) * 100) if weight else 0
    if pct <= LOW_STOCK_PCT:
        level = "low"
    elif pct < CAUTION_PCT:
        level = "caution"
    else:
        level = "good"
    data = f.model_dump()
    data["remaining_pct"] = pct
    data["level"] = level
    data["low_stock"] = pct <= LOW_STOCK_PCT
    return data


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """Serve the single-page catalog UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/meta")
def meta(session: Session = Depends(get_session)):
    """Distinct materials/brands/finishes (for filter dropdowns) + settings."""
    rows = session.exec(select(Filament)).all()
    materials = sorted({r.material for r in rows if r.material})
    brands = sorted({r.brand for r in rows if r.brand})
    finishes = sorted({r.finish for r in rows if r.finish})
    return {
        "materials": materials,
        "brands": brands,
        "finishes": finishes,
        "low_stock_pct": LOW_STOCK_PCT,
    }


@app.get("/api/filaments")
def list_filaments(
    q: Optional[str] = None,
    material: Optional[str] = None,
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
    session.add(f)
    session.commit()
    session.refresh(f)
    result = serialize(f)
    upsert_product(session, f)   # remember this product behind its barcode
    return result


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
    f.updated_at = datetime.now(timezone.utc)
    session.add(f)
    session.commit()
    session.refresh(f)
    result = serialize(f)
    upsert_product(session, f)   # keep the remembered product in step with edits
    return result


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
