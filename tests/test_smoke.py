"""End-to-end smoke tests for the catalog API, UI shell, and CSV export.

These run the real FastAPI app through TestClient with a temporary database
(see conftest.py), so they cover routing, serialization, and the SQLite session
without needing Docker or Tesseract.
"""

import csv
import io

from app.main import CSV_FIELDS

CSV_HEADERS = [header for _, header in CSV_FIELDS]


def make_spool(client, **overrides):
    """POST a valid spool, applying overrides, and return the saved JSON."""
    payload = {
        "material": "PLA",
        "color": "Forest Green",
        "finish": "Matte",
        "brand": "Inland",
        "barcode": "0123456789012",
        "spool_weight_g": 1000,
        "remaining_g": 1000,
        "nozzle_temp": 210,
        "bed_temp": 60,
        "notes": "smoke test spool",
    }
    payload.update(overrides)
    response = client.post("/api/filaments", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def read_export(response):
    """Decode a CSV export response and return its rows as dicts."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert ".csv" in response.headers["content-disposition"]
    # Excel-friendly BOM at the start of the file.
    assert response.content.startswith(b"\xef\xbb\xbf")
    text = response.content.decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


# ---- Page + meta ---------------------------------------------------------


def test_home_page_and_footer(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Filament Catalog" in response.text
    assert "Filament Catalog v" in response.text
    assert "testsha" in response.text          # BUILD_SHA shortened to 7 chars
    assert "Export CSV" in response.text
    assert "Known products" in response.text
    assert 'id="use-dialog"' in response.text


def test_meta(client):
    response = client.get("/api/meta")
    assert response.status_code == 200
    body = response.json()
    assert body["low_stock_pct"] == 25
    assert {"materials", "families", "brands", "finishes"} <= body.keys()


# ---- Spool CRUD + clamping ----------------------------------------------


def test_create_and_list(client):
    created = make_spool(client)
    assert created["remaining_pct"] == 100
    assert created["level"] == "good"

    rows = client.get("/api/filaments").json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]
    assert rows[0]["color"] == "Forest Green"


def test_remaining_grams_are_clamped(client):
    over = make_spool(client, remaining_g=5000)
    assert over["remaining_g"] == 1000
    assert over["remaining_pct"] == 100

    negative = client.patch(
        f"/api/filaments/{over['id']}", json={"remaining_g": -50}
    ).json()
    assert negative["remaining_g"] == 0
    assert negative["remaining_pct"] == 0
    assert negative["low_stock"] is True

    low = client.patch(
        f"/api/filaments/{over['id']}", json={"remaining_g": 250}
    ).json()
    assert low["remaining_pct"] == 25
    assert low["level"] == "low"


def test_edit_and_delete(client):
    spool = make_spool(client)
    response = client.patch(
        f"/api/filaments/{spool['id']}",
        json={"color": "Silver", "notes": "edited"},
    )
    assert response.status_code == 200
    assert response.json()["color"] == "Silver"

    assert client.delete(f"/api/filaments/{spool['id']}").status_code == 200
    assert client.get("/api/filaments").json() == []
    assert client.delete(f"/api/filaments/{spool['id']}").status_code == 404


def test_low_stock_filter(client):
    make_spool(client, color="Full", remaining_g=1000)
    make_spool(client, color="Empty", remaining_g=0, barcode=None)

    rows = client.get("/api/filaments", params={"low_stock": "true"}).json()
    assert [r["color"] for r in rows] == ["Empty"]


def test_use_grams_quick_action(client):
    spool = make_spool(client, remaining_g=1000)

    response = client.post(f"/api/filaments/{spool['id']}/use", json={"grams": 250})
    assert response.status_code == 200
    body = response.json()
    assert body["remaining_g"] == 750
    assert body["remaining_pct"] == 75

    # Logging more than is left empties the spool instead of going negative.
    response = client.post(f"/api/filaments/{spool['id']}/use", json={"grams": 9999})
    assert response.status_code == 200
    assert response.json()["remaining_g"] == 0
    assert response.json()["low_stock"] is True

    assert client.post(
        f"/api/filaments/{spool['id']}/use", json={"grams": 0}
    ).status_code == 422
    assert client.post(
        f"/api/filaments/{spool['id']}/use", json={"grams": -5}
    ).status_code == 422
    assert client.post("/api/filaments/99999/use", json={"grams": 10}).status_code == 404


# ---- Barcode memory ------------------------------------------------------


def test_barcode_memory_survives_deleting_spools(client):
    spool = make_spool(client)
    assert client.get("/api/barcode/0123456789012").json()["color"] == "Forest Green"

    # Saving the same product again refreshes the remembered details.
    second = make_spool(client, color="Silver", remaining_g=500)
    remembered = client.get("/api/barcode/0123456789012").json()
    assert remembered["color"] == "Silver"

    for filament_id in (spool["id"], second["id"]):
        assert client.delete(f"/api/filaments/{filament_id}").status_code == 200

    # The product outlives its spools so a refill scan still fills the form.
    still_there = client.get("/api/barcode/0123456789012")
    assert still_there.status_code == 200
    assert still_there.json()["color"] == "Silver"


def test_unknown_barcode_returns_404(client):
    assert client.get("/api/barcode/does-not-exist").status_code == 404


def test_known_products_can_be_edited_and_forgotten(client):
    make_spool(client)

    products = client.get("/api/products").json()
    assert len(products) == 1
    assert products[0]["barcode"] == "0123456789012"
    assert products[0]["material"] == "PLA"

    response = client.patch(
        "/api/products/0123456789012",
        json={"color": "Ocean Blue", "finish": "Silk", "brand": "Overture"},
    )
    assert response.status_code == 200
    assert response.json()["color"] == "Ocean Blue"

    # Future scans see the correction...
    remembered = client.get("/api/barcode/0123456789012").json()
    assert remembered["color"] == "Ocean Blue"
    assert remembered["brand"] == "Overture"

    # ...but the existing spool keeps its own values.
    assert client.get("/api/filaments").json()[0]["color"] == "Forest Green"

    # Required fields can't be blanked by an accidental null.
    response = client.patch(
        "/api/products/0123456789012", json={"material": None, "brand": "Inland"}
    )
    assert response.status_code == 200
    assert response.json()["material"] == "PLA"
    assert response.json()["brand"] == "Inland"

    assert client.delete("/api/products/0123456789012").status_code == 200
    assert client.get("/api/products").json() == []
    assert client.get("/api/barcode/0123456789012").status_code == 404

    # Editing or forgetting a barcode we don't know is a 404.
    assert client.patch("/api/products/nope", json={"color": "x"}).status_code == 404
    assert client.delete("/api/products/nope").status_code == 404
    # Weight must stay positive.
    make_spool(client)
    assert client.patch(
        "/api/products/0123456789012", json={"spool_weight_g": 0}
    ).status_code == 422


# ---- CSV export ----------------------------------------------------------


def test_csv_export_matches_the_list(client):
    make_spool(
        client,
        color="Moss, Green",          # comma must survive CSV quoting
        notes='He said "dry it" first',
    )

    response = client.get("/api/export.csv")
    rows = read_export(response)
    assert len(rows) == 1

    text = response.content.decode("utf-8-sig")
    assert text.splitlines()[0] == ",".join(CSV_HEADERS)

    row = rows[0]
    assert row["material"] == "PLA"
    assert row["color"] == "Moss, Green"
    assert row["notes"] == 'He said "dry it" first'
    assert row["remaining_g"] == "1000"
    assert row["remaining_pct"] == "100"
    assert row["created_at"]          # timestamps are present
    assert row["updated_at"]


def test_csv_export_respects_filters(client):
    make_spool(client, material="PLA", color="Green", barcode=None)
    make_spool(
        client,
        material="PETG",
        color="Black",
        brand="Overture",
        barcode=None,
        remaining_g=0,
    )

    pla = read_export(client.get("/api/export.csv", params={"family": "PLA"}))
    assert [r["material"] for r in pla] == ["PLA"]

    low = read_export(client.get("/api/export.csv", params={"low_stock": "true"}))
    assert [r["color"] for r in low] == ["Black"]

    search = read_export(client.get("/api/export.csv", params={"q": "overture"}))
    assert [r["brand"] for r in search] == ["Overture"]

    none = read_export(client.get("/api/export.csv", params={"q": "no-such-thing"}))
    assert none == []


def test_csv_export_empty_catalog_has_header_only(client):
    response = client.get("/api/export.csv")
    assert response.status_code == 200
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 1
    assert lines[0] == ",".join(CSV_HEADERS)


# ---- OCR upload guards (no Tesseract needed) -----------------------------


def test_ocr_rejects_non_image(client):
    response = client.post(
        "/api/ocr", files={"image": ("label.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 415


def test_ocr_rejects_oversized_upload(client):
    response = client.post(
        "/api/ocr",
        files={"image": ("huge.jpg", b"\xff" * (10 * 1024 * 1024 + 10), "image/jpeg")},
    )
    assert response.status_code == 413


def test_ocr_rejects_unreadable_image(client):
    response = client.post(
        "/api/ocr", files={"image": ("bad.png", b"not an image", "image/png")}
    )
    assert response.status_code == 422


# ---- SQLite settings -----------------------------------------------------


def test_sqlite_uses_wal_and_busy_timeout(client):
    from sqlmodel import Session

    from app.database import engine

    with Session(engine) as session:
        connection = session.connection()
        mode = connection.exec_driver_sql("PRAGMA journal_mode").first()[0]
        timeout = connection.exec_driver_sql("PRAGMA busy_timeout").first()[0]
    assert str(mode).lower() == "wal"
    assert int(timeout) == 5000
