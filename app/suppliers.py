"""Look up filament details from a manufacturer's code/SKU.

Right now this supports Numakers, whose store runs on Shopify and exposes its
whole catalog as JSON at /products.json. We fetch that (cached), index every
variant by its SKU, and turn a matched variant into material/finish/color/weight
so the Add form can be pre-filled instead of typed by hand.

Numakers' data is a little inconsistent: some variants carry the SKU in Shopify's
`sku` field, others only in the product image filename, and the color is
sometimes a placeholder in the option while the real name lives in the image
name. So material/finish/weight are reliable; color is a best guess the user
confirms. Each brand is its own small resolver, added to RESOLVERS below.
"""

import re
import time
import json
import urllib.request

_TIMEOUT = 15
_CATALOG_TTL = 6 * 3600  # re-fetch a brand's catalog at most this often

# Finish words we lift out of a product title so material stays a base type.
_FINISHES = [
    "Glow in the Dark", "Matte", "Silk", "Metallic", "Marble", "Wood",
    "Starlight", "Translucent", "Glow", "CF", "Tri-Color", "Dual",
]

# Tokens to drop when recovering a color from an image filename: brand, material,
# finish, packaging and marketing words. Deliberately excludes real color words.
_NOISE = {
    "numakers", "printzy", "spool", "spl", "with", "w", "the", "lab", "of",
    "filament", "reusable", "refill", "pack", "without",
    "pla", "pla+", "petg", "abs", "asa", "pp", "tpu", "pctg", "pa", "hs", "cf",
    "matte", "silk", "metallic", "marble", "wood", "starlight", "translucent",
    "glow", "dual", "tri", "tricolor", "color", "colour",
    "hueforge", "nubox", "swatch", "kg", "mm", "1kg", "175", "set",
}

# Numakers SKU shape, e.g. PLMT11KPAA / PLSK11KPDV / PPNA11KPBJ -> letters digits letters.
_SKU_RE = re.compile(r"[A-Z]{3,}\d{2}[A-Z]{3,}")


def _fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "FilamentCatalog/1.0"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---- Numakers ------------------------------------------------------------

_numakers_cache = {"ts": 0.0, "by_sku": {}}
NUMAKERS_BASE = "https://numakers.com"


def _parse_material_finish(product_title: str):
    """'PLA Matte' -> ('PLA', 'Matte'); 'PLA+ Filament' -> ('PLA+', None)."""
    text = re.sub(r"\bfilament\b", "", product_title, flags=re.I).strip()
    finish = None
    for f in _FINISHES:
        if re.search(re.escape(f), text, flags=re.I):
            finish = f
            text = re.sub(re.escape(f), "", text, flags=re.I)
            break
    material = re.sub(r"\s+", " ", text).strip(" -/") or product_title.strip()
    return material, finish


def _weight_g(variant: dict) -> int:
    for opt in (variant.get("option1"), variant.get("option2"), variant.get("option3")):
        if opt and "kg" in opt.lower():
            m = re.search(r"([\d.]+)\s*kg", opt.lower())
            if m:
                return int(float(m.group(1)) * 1000)
    return 1000


def _image_filename(variant: dict) -> str:
    src = (variant.get("featured_image") or {}).get("src", "") or ""
    return src.split("/")[-1].split("?")[0]


def _color_from(variant: dict) -> str | None:
    """Best-effort color: recover it from the image filename, else a color-ish option."""
    # Strip the extension and any SKU token; keep mixed case so camelCase survives.
    name = re.sub(r"\.(jpe?g|png|webp|gif)$", "", _image_filename(variant), flags=re.I)
    name = _SKU_RE.sub("", name)
    words = []
    for part in re.split(r"[-_\s]+", name):
        for w in re.findall(r"[A-Z][a-z]+|[A-Z]+(?![a-z])|[a-z]+|\d+", part):
            if w.lower() not in _NOISE and not w.isdigit() and len(w) > 1:
                words.append(w)
    color = " ".join(words).strip()
    if color:
        return color
    for opt in (variant.get("option3"), variant.get("option2"), variant.get("option1")):
        if opt and not re.search(r"mm|kg", opt, flags=re.I):
            return opt
    return None


def _variant_skus(variant: dict):
    skus = set()
    if variant.get("sku"):
        skus.add(variant["sku"].strip().upper())
    skus.update(m.upper() for m in _SKU_RE.findall(_image_filename(variant).upper()))
    return skus


def _numakers_index(force: bool = False) -> dict:
    now = time.time()
    if not force and _numakers_cache["by_sku"] and now - _numakers_cache["ts"] < _CATALOG_TTL:
        return _numakers_cache["by_sku"]

    index = {}
    for page in range(1, 11):  # Shopify pages of 250; plenty for this catalog
        data = _fetch_json(f"{NUMAKERS_BASE}/products.json?limit=250&page={page}")
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            material, finish = _parse_material_finish(p.get("title", ""))
            for v in p.get("variants", []):
                entry = {
                    "brand": "Numakers",
                    "material": material,
                    "finish": finish,
                    "color": _color_from(v),
                    "spool_weight_g": _weight_g(v),
                    "source_url": f"{NUMAKERS_BASE}/products/{p.get('handle', '')}",
                }
                for sku in _variant_skus(v):
                    entry_sku = dict(entry, sku=sku)
                    index.setdefault(sku, entry_sku)
    _numakers_cache["by_sku"] = index
    _numakers_cache["ts"] = now
    return index


def _lookup_numakers(code: str):
    return _numakers_index().get(code.strip().upper())


# ---- Dispatch ------------------------------------------------------------

RESOLVERS = {
    "numakers": _lookup_numakers,
}


def lookup_sku(brand: str, code: str):
    """Return details for a brand's code, or None if not found. Raises on a
    network/parse failure so the caller can tell 'not found' from 'lookup broke'."""
    resolver = RESOLVERS.get(brand.strip().lower())
    if resolver is None:
        return None
    return resolver(code)


if __name__ == "__main__":
    import sys
    brand = sys.argv[1] if len(sys.argv) > 1 else "numakers"
    for code in (sys.argv[2:] or ["PLMT11KPAA", "PLSK11KPDV", "PPNA11KPBJ"]):
        print(code, "->", lookup_sku(brand, code))
