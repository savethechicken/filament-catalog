"""Read filament usage out of a sliced file.

OrcaSlicer (and its PrusaSlicer / Bambu Studio ancestors) writes the slicer's
own per-filament estimate into every sliced file:

  * a raw ``.gcode`` ends with comments such as
    ``; filament used [g] = 14.21, 4.25``
  * a sliced ``.gcode.3mf`` stores ``Metadata/slice_info.config`` (XML) with
    ``<filament id="1" type="PLA" color="#FF0000" used_g="14.21"/>``

This module only reads those numbers. Nothing is subtracted until the user
picks a spool and confirms in the Use dialog.
"""

from __future__ import annotations

import json
import re
import zipfile
from typing import BinaryIO
from xml.etree import ElementTree

# Comment keys we read, mapped to the field they fill in.
_USAGE_KEYS = {
    "filament used [g]": "grams",
    "filament used [mm]": "mm",
    "filament used [cm3]": "cm3",
}
_TOTAL_KEY = "total filament used [g]"
_CONFIG_KEYS = {
    "filament_type": "type",
    "filament_colour": "color",   # PrusaSlicer/OrcaSlicer spelling
    "filament_color": "color",    # tolerated variant
    "filament_density": "density",
    "filament_settings_id": "profile",
}

# Cross-sectional area of 1.75 mm filament, in mm². The slicer uses the same
# constant when it turns length into weight.
_FILAMENT_AREA_MM2 = 2.4052


class SliceUsageError(ValueError):
    """The uploaded file didn't contain usable slicer usage information."""


def parse_slice_usage(stream: BinaryIO, filename: str = "") -> dict:
    """Return ``{source, name, total_g, filaments}`` for a sliced file.

    ``stream`` must be seekable. ZIP magic wins over the extension, so a
    ``.gcode.3mf`` (which ends in ``.3mf``) is handled automatically.
    """
    stream.seek(0)
    magic = stream.read(4)
    stream.seek(0)
    if magic.startswith(b"PK"):
        return _parse_3mf(stream, filename)
    return _parse_gcode(stream, filename)


# ---- Raw G-code -----------------------------------------------------------


def _parse_gcode(stream: BinaryIO, filename: str) -> dict:
    usage: dict[str, list[float]] = {}
    config: dict[str, list[str]] = {}

    for raw in stream:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
        if not line.startswith(";"):
            continue
        key, sep, value = line[1:].partition("=")
        if not sep:
            continue
        key = key.strip().lower()
        value = value.strip()

        if key in _USAGE_KEYS:
            usage[_USAGE_KEYS[key]] = _floats(value)
        elif key == _TOTAL_KEY:
            usage["total"] = _first_float(value)
        elif key in _CONFIG_KEYS:
            config[_CONFIG_KEYS[key]] = _values(value)

    return _result(
        source="gcode",
        filename=filename,
        grams=usage.get("grams", []),
        mm=usage.get("mm", []),
        types=config.get("type", []),
        colors=config.get("color", []),
        profiles=config.get("profile", []),
        densities=config.get("density", []),
        total=usage.get("total"),
    )


# ---- Sliced 3MF -----------------------------------------------------------


def _parse_3mf(stream: BinaryIO, filename: str) -> dict:
    try:
        archive = zipfile.ZipFile(stream)
    except zipfile.BadZipFile:
        raise SliceUsageError("That file isn't a valid 3MF or ZIP archive.")

    with archive:
        names = {name.lower(): name for name in archive.namelist()}
        slice_name = _find(names, "slice_info.config")
        if slice_name:
            return _parse_slice_info(archive, slice_name, filename, names)

        # No slice_info.config: fall back to the embedded plate G-code.
        gcode_name = _find(names, ".gcode")
        if gcode_name:
            with archive.open(gcode_name) as gcode:
                result = _parse_gcode(gcode, filename)
            result["source"] = "3mf"
            return result

    raise SliceUsageError(
        "That 3MF has no sliced G-code. Export it as .gcode.3mf after slicing."
    )


def _parse_slice_info(archive: zipfile.ZipFile, name: str, filename: str, names: dict) -> dict:
    try:
        root = ElementTree.fromstring(archive.read(name))
    except ElementTree.ParseError:
        raise SliceUsageError("Couldn't read the slice metadata in that 3MF.")

    # Sum each filament slot across plates (a multi-plate project has one
    # <plate> per plate, each repeating the same filament ids).
    slots: dict[str, dict] = {}
    for element in root.iter():
        tag = element.tag.split("}")[-1].lower()
        if tag != "filament":
            continue
        slot_id = element.attrib.get("id")
        if not slot_id:
            continue
        entry = slots.setdefault(
            slot_id,
            {"grams": 0.0, "mm": 0.0, "type": None, "color": None, "profile": None},
        )
        grams = _first_float(element.attrib.get("used_g"))
        metres = _first_float(element.attrib.get("used_m"))
        if grams:
            entry["grams"] += grams
        if metres:
            entry["mm"] += metres * 1000.0
        entry["type"] = entry["type"] or element.attrib.get("type")
        entry["color"] = entry["color"] or element.attrib.get("color")
        entry["profile"] = entry["profile"] or element.attrib.get("profile")

    if not slots:
        raise SliceUsageError("That 3MF's slice metadata has no filament usage.")

    settings: dict = {}
    settings_name = _find(names, "project_settings.config")
    if settings_name:
        try:
            settings = json.loads(archive.read(settings_name))
        except (ValueError, OSError):
            settings = {}

    ordered = sorted(
        slots,
        key=lambda value: (not value.isdigit(), int(value) if value.isdigit() else 0, value),
    )
    grams = [slots[slot]["grams"] for slot in ordered]
    mm = [slots[slot]["mm"] for slot in ordered]
    types = []
    colors = []
    profiles = []
    for index, slot in enumerate(ordered):
        entry = slots[slot]
        types.append(entry["type"] or _setting(settings, "filament_type", index))
        colors.append(entry["color"] or _setting(settings, "filament_colour", index))
        profiles.append(entry["profile"] or _setting(settings, "filament_settings_id", index))

    return _result(
        source="3mf",
        filename=filename,
        grams=grams,
        mm=mm,
        types=types,
        colors=colors,
        profiles=profiles,
        densities=_setting_list(settings, "filament_density"),
        total=None,
    )


# ---- Shared assembly ------------------------------------------------------


def _result(
    *,
    source: str,
    filename: str,
    grams: list[float],
    mm: list[float],
    types: list,
    colors: list,
    profiles: list,
    densities: list,
    total: float | None,
) -> dict:
    count = max(len(grams), len(mm), len(types), len(colors), len(profiles))
    if count == 0 and total is not None:
        grams, count = [total], 1
    if count == 0:
        raise SliceUsageError(
            "Couldn't find filament usage in this file. Slice it first, or pick "
            "a .gcode / .gcode.3mf that contains the slicer's summary."
        )

    if not any(grams):
        # Some files carry length but not weight; convert with the profile density
        # using the same 1.75 mm area factor the slicer uses.
        derived = []
        for index in range(count):
            density = _at(densities, index, repeat=True)
            length = _at(mm, index)
            if density and length:
                derived.append(round(length * _FILAMENT_AREA_MM2 * float(density) * 0.001, 2))
            else:
                derived.append(0.0)
        if any(derived):
            grams = derived
        elif total is not None and count == 1:
            grams = [total]
        else:
            raise SliceUsageError(
                "This file only reports filament length, not grams. Add a "
                "filament density to the slicer profile, then slice again."
            )

    filaments = []
    for index in range(count):
        value = _at(grams, index)
        if value is None or value <= 0:
            continue
        filaments.append(
            {
                "slot": len(filaments) + 1,
                "type": _string_at(types, index),
                "color": _string_at(colors, index),
                "profile": _string_at(profiles, index),
                "grams": round(value, 2),
                "mm": round(mm[index], 1) if index < len(mm) and mm[index] else None,
            }
        )

    if not filaments:
        raise SliceUsageError("That file reports zero filament usage.")

    reported = total if total is not None and total > 0 else None
    return {
        "source": source,
        "name": filename or "",
        "total_g": round(reported if reported is not None else sum(f["grams"] for f in filaments), 2),
        "filaments": filaments,
    }


# ---- Small parsing helpers ------------------------------------------------


def _find(names: dict[str, str], suffix: str) -> str | None:
    suffix = suffix.lower()
    for lower, original in names.items():
        if lower.endswith(suffix):
            return original
    return None


def _floats(value: str) -> list[float]:
    return [float(number) for number in re.findall(r"-?\d+(?:\.\d+)?", value)]


def _first_float(value: str | None) -> float | None:
    if value is None:
        return None
    numbers = _floats(value)
    return numbers[0] if numbers else None


def _values(value: str) -> list[str]:
    return [part.strip().strip('"').strip() for part in value.split(";") if part.strip()]


def _at(values: list, index: int, repeat: bool = False):
    if not values:
        return None
    if index < len(values):
        return values[index]
    return values[-1] if repeat else None


def _string_at(values: list, index: int):
    value = _at(values, index)
    return str(value) if value else None


def _setting(settings: dict, key: str, index: int):
    value = _setting_list(settings, key)
    return _string_at(value, index)


def _setting_list(settings: dict, key: str) -> list:
    candidates = [key, key.replace("colour", "color"), key.replace("color", "colour")]
    for candidate in candidates:
        if candidate in settings:
            value = settings[candidate]
            if isinstance(value, str):
                return _values(value)
            if isinstance(value, (list, tuple)):
                return list(value)
            return [value]
    return []
