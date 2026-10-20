"""Load the starting catalog from your handwritten log.

Run once:  python -m app.seed
It only adds the rows if the table is empty, so it is safe to re-run.
"""

from sqlmodel import Session, select

from .database import engine, init_db
from .models import Filament

# Fractions translated to grams of a 1 KG spool.
FULL, HALF, THIRD, QUARTER, EIGHTH = 1000, 500, 333, 250, 125

# (material, color, finish, brand, remaining_g)
SPOOLS = [
    ("PLA",    "Silver",          "Silk",        "Inland",     THIRD),     # ~1/3 roll
    ("PLA",    "Forest Green",    None,          "Inland",     QUARTER),
    ("PLA",    "Yellow",          None,          "Snapmaker",  HALF),
    ("PLA",    "Grey",            "Matte",       "Inland",     HALF),
    ("PLA",    "Illuminated Blue",None,          "Inland",     EIGHTH),
    ("HSPLA+", "Milk White",      None,          "Inland",     QUARTER),
    ("PLA",    "White",           "Matte",       "Inland",     QUARTER),
    ("PLA Pro","Green",           None,          "Inland",     FULL),
    ("PLA",    "Bark Magic",      None,          "Cookie CAD", FULL),
    ("PLA",    "Rainbow",         "Color Shift", "Ambrosia",   FULL),
    ("PETG",   "Black",           None,          "Inland",     FULL),
    ("PLA+",   "Gray",            None,          "Inland",     QUARTER),
    ("PLA+",   "Orange",          None,          "Inland",     FULL),
    ("PLA+",   "Dark Blue",       None,          "Inland",     FULL),
    ("PLA+",   "Pink",            None,          "Inland",     FULL),
]


def seed() -> None:
    init_db()
    with Session(engine) as session:
        existing = session.exec(select(Filament)).first()
        if existing:
            print("Catalog already has data - skipping seed.")
            return
        for material, color, finish, brand, remaining in SPOOLS:
            session.add(Filament(
                material=material,
                color=color,
                finish=finish,
                brand=brand,
                spool_weight_g=1000,
                remaining_g=remaining,
            ))
        session.commit()
        print(f"Seeded {len(SPOOLS)} spools.")


if __name__ == "__main__":
    seed()
