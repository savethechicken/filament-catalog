"""Read filament details from a photo of the box label (OCR).

The phone sends a photo, the server OCRs it with Tesseract, and a per-brand
parser pulls out material/finish/color/weight/temp. Labels differ by brand, so
each brand has its own parser in BRAND_PARSERS; read_label tries each until one
recognizes the text. Bambu Lab is supported now.

Runs entirely on the server (no internet needed). Tesseract must be installed:
it's in the Docker image; for local dev set TESSERACT_CMD to tesseract's path.
"""

import io
import os
import re

import pytesseract
from PIL import Image, ImageOps

_cmd = os.environ.get("TESSERACT_CMD")
if _cmd:
    pytesseract.pytesseract.tesseract_cmd = _cmd


def ocr_image(data: bytes) -> str:
    """OCR raw image bytes into text, with light cleanup for phone photos."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)            # honor the phone's rotation
    img = img.convert("L")                        # grayscale
    if img.width < 1200:                          # upscale small photos
        scale = 1200 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)))
    img = ImageOps.autocontrast(img)
    return pytesseract.image_to_string(img)


# ---- Bambu Lab -----------------------------------------------------------

_MATERIALS = ["PAHT", "PETG", "PET", "PLA", "ABS", "ASA", "TPU", "PVA", "PC", "PA", "PP", "HIPS"]
_FINISHES = [
    "Matte", "Silk", "Marble", "Metal", "Glow", "Translucent", "Sparkle",
    "Wood", "Gradient", "Galaxy", "Aero", "Luminous", "Dynamic", "Tough",
    "Support", "CF", "GF",
]

# Words a line must NOT contain to be considered a color name.
_NOT_COLOR = {
    "bambu", "lab", "made", "in", "china", "model", "diameter", "length",
    "printing", "temp", "net", "weight", "filament", "code", "mm", "kg",
    "roll", "spool", "pla", "petg", "pet", "abs", "asa", "tpu", "pva", "pc",
    "pa", "pp", "hips",
} | {f.lower() for f in _FINISHES}


def _looks_like_color(line: str) -> bool:
    """A color line is 1–3 Title-case words, none of them label/brand keywords."""
    tokens = line.strip().split()
    if not (1 <= len(tokens) <= 3):
        return False
    for t in tokens:
        if not re.fullmatch(r"[A-Z][a-z]+", t):   # First-upper, rest lowercase
            return False
        if t.lower() in _NOT_COLOR:
            return False
    return True


def parse_bambu(text: str):
    """Pull fields from a Bambu Lab box label's OCR text, or None if not one."""
    if "bambu" not in text.lower():
        return None

    material = next((m for m in _MATERIALS if re.search(rf"\b{m}\b", text, re.I)), None)
    finish = next((f for f in _FINISHES if re.search(rf"\b{f}\b", text, re.I)), None)
    color = next((ln.strip() for ln in text.splitlines() if _looks_like_color(ln)), None)

    fields = {
        "brand": "Bambu Lab",
        "material": material,
        "finish": finish,
        "color": color,
        "spool_weight_g": 1000,
    }

    w = re.search(r"net\s*weight[^0-9]*(\d+(?:\.\d+)?)\s*kg", text, re.I)
    if w:
        fields["spool_weight_g"] = int(float(w.group(1)) * 1000)

    # The only 12–13 digit number on the label is the UPC barcode; grab it so the
    # "remember this spool" memory and future barcode scans line up.
    bc = re.search(r"\b(\d{12,13})\b", text)
    if bc:
        fields["barcode"] = bc.group(1)

    note_bits = []
    t = re.search(r"printing\s*temp[^0-9]*(\d{2,3})\s*[-–]\s*(\d{2,3})", text, re.I)
    if t:
        lo, hi = int(t.group(1)), int(t.group(2))
        fields["nozzle_temp"] = round((lo + hi) / 2)
        note_bits.append(f"Printing temp {lo}-{hi}°C")

    code = re.search(r"filament\s*code[^0-9]*(\d{3,6})", text, re.I)
    if code:
        note_bits.append(f"Bambu filament code {code.group(1)}")

    model = re.search(r"model[:\s]*([A-Z0-9][A-Z0-9][A-Z0-9\-.]+)", text, re.I)
    if model:
        note_bits.append(f"Model {model.group(1)}")

    if note_bits:
        fields["notes"] = "; ".join(note_bits)

    # Only count it as a hit if we got the basics.
    return fields if fields["material"] else None


BRAND_PARSERS = [parse_bambu]


def parse_label(text: str):
    """Try each brand parser; return the first that recognizes the label."""
    for parser in BRAND_PARSERS:
        result = parser(text)
        if result:
            return result
    return None


def read_label(data: bytes):
    """OCR an image and parse it into filament fields, or None if unrecognized."""
    return parse_label(ocr_image(data))


if __name__ == "__main__":
    import sys, json
    with open(sys.argv[1], "rb") as f:
        text = ocr_image(f.read())
    print("--- OCR TEXT ---")
    print(text)
    print("--- PARSED ---")
    print(json.dumps(parse_label(text), indent=2))
