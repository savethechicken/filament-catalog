"""FastAPI application for the filament catalog.

Routes:
  GET  /                      -> the web page (templates/index.html)
  GET  /api/filaments         -> list spools, with optional search/filter
  POST /api/filaments         -> add a spool
  PATCH/api/filaments/{id}    -> edit a spool
  DELETE /api/filaments/{id}  -> remove a spool
  GET  /api/meta              -> dropdown values + the low-stock threshold

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

from .database import init_db, get_session
from .models import Filament, FilamentCreate, FilamentUpdate

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
    """Make sure the database table exists before the first request."""
    init_db()


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


@app.post("/api/filaments")
def create_filament(payload: FilamentCreate, session: Session = Depends(get_session)):
    """Add a new spool."""
    f = Filament.model_validate(payload)
    session.add(f)
    session.commit()
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
    f.updated_at = datetime.now(timezone.utc)
    session.add(f)
    session.commit()
    session.refresh(f)
    return serialize(f)


@app.delete("/api/filaments/{filament_id}")
def delete_filament(filament_id: int, session: Session = Depends(get_session)):
    """Remove a spool from the catalog."""
    f = session.get(Filament, filament_id)
    if not f:
        raise HTTPException(status_code=404, detail="Spool not found")
    session.delete(f)
    session.commit()
    return {"ok": True}
