import json
from decimal import ROUND_HALF_UP, Decimal
from sqlalchemy.orm import Session
from .models import Setting

DEFAULT_PRICING = {
    "currency": "PHP",
    "per_page": {"bw": 2.0, "color": 8.0},
    "paper_multiplier": {"A4": 1.0, "Letter": 1.0, "Legal": 1.2, "A3": 2.5},
    "duplex_discount_pct": 10,
    "binding": {"none": 0, "staple": 3, "spiral": 35, "clear_cover": 20},
}
COLOR_MODES = ("bw", "color")
SIDES = ("single", "double")


def get_pricing(db: Session) -> dict:
    row = db.get(Setting, "pricing")
    return json.loads(row.value) if row else DEFAULT_PRICING


def validate_pricing(p: dict) -> dict:
    try:
        out = {
            "currency": str(p.get("currency", "PHP"))[:5],
            "per_page": {k: float(p["per_page"][k]) for k in COLOR_MODES},
            "paper_multiplier": {str(k): float(v) for k, v in p["paper_multiplier"].items()},
            "duplex_discount_pct": float(p["duplex_discount_pct"]),
            "binding": {str(k): float(v) for k, v in p["binding"].items()},
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("Pricing is incomplete or contains a non-numeric value.")
    if "none" not in out["binding"]:
        out["binding"]["none"] = 0.0
    if not out["paper_multiplier"]:
        raise ValueError("At least one paper size is required.")
    if not 0 <= out["duplex_discount_pct"] <= 100:
        raise ValueError("Back-to-back discount must be between 0 and 100.")
    for group in (out["per_page"], out["paper_multiplier"], out["binding"]):
        if any(v < 0 for v in group.values()):
            raise ValueError("Prices cannot be negative.")
    return out


def _money(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def validate_options(opts: dict, pricing: dict):
    if opts["paper_size"] not in pricing["paper_multiplier"]:
        raise ValueError("Unsupported paper size.")
    if opts["color_mode"] not in COLOR_MODES:
        raise ValueError("Unsupported color mode.")
    if opts["sides"] not in SIDES:
        raise ValueError("Unsupported sides option.")
    if opts["binding"] not in pricing["binding"]:
        raise ValueError("Unsupported binding option.")
    if not 1 <= int(opts["copies"]) <= 500:
        raise ValueError("Copies must be between 1 and 500.")


def estimate(pages: int, opts: dict, pricing: dict) -> dict:
    """Instant cost estimator: pages x copies x rate, minus back-to-back discount, plus binding per copy."""
    validate_options(opts, pricing)
    copies = int(opts["copies"])
    rate = Decimal(str(pricing["per_page"][opts["color_mode"]])) * Decimal(str(pricing["paper_multiplier"][opts["paper_size"]]))
    printing = rate * pages * copies
    discount = printing * Decimal(str(pricing["duplex_discount_pct"])) / 100 if opts["sides"] == "double" else Decimal(0)
    binding = Decimal(str(pricing["binding"][opts["binding"]])) * copies
    return {
        "pages": pages, "copies": copies, "rate_per_page": float(_money(rate)),
        "printing": float(_money(printing)), "duplex_discount": float(_money(discount)),
        "binding": float(_money(binding)), "total": float(_money(printing - discount + binding)),
        "currency": pricing["currency"],
    }
