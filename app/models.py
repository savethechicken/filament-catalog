"""Database models and the shapes used for creating/updating rows.

We use SQLModel, which lets one class describe both the database table and the
data validation. `Filament` (table=True) is the stored row; `FilamentCreate`
and `FilamentUpdate` describe what the web page is allowed to send in.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import SQLModel, Field


def _now() -> datetime:
    """Current UTC time. Used as the default for the timestamp columns."""
    return datetime.now(timezone.utc)


class FilamentBase(SQLModel):
    """Fields shared by the stored row and the incoming create/update data."""

    material: str = Field(index=True)          # PLA, PLA+, PETG, PLA Pro, HSPLA+ ...
    color: str                                 # "Forest Green", "Silver" ...
    finish: Optional[str] = Field(default=None, index=True)  # Silk, Matte, Color Shift ...
    brand: Optional[str] = Field(default=None, index=True)   # Inland, Cookie CAD ...
    barcode: Optional[str] = Field(default=None, index=True)  # UPC/EAN off the spool label

    spool_weight_g: int = 1000                 # net weight of a full spool
    remaining_g: int = 1000                    # grams left on the spool right now

    nozzle_temp: Optional[int] = None          # suggested hotend temp (C)
    bed_temp: Optional[int] = None             # suggested bed temp (C)
    notes: Optional[str] = None


class Filament(FilamentBase, table=True):
    """A single spool in the catalog."""

    id: Optional[int] = Field(default=None, primary_key=True)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class FilamentCreate(FilamentBase):
    """What the Add form sends. Same fields as the base."""
    pass


class FilamentUpdate(SQLModel):
    """What the Edit form sends. Every field optional so you can change just one."""

    material: Optional[str] = None
    color: Optional[str] = None
    finish: Optional[str] = None
    brand: Optional[str] = None
    barcode: Optional[str] = None
    spool_weight_g: Optional[int] = None
    remaining_g: Optional[int] = None
    nozzle_temp: Optional[int] = None
    bed_temp: Optional[int] = None
    notes: Optional[str] = None
