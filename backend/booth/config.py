"""Booth config (config/booth.json).

Edited by hand or on the staff page (Einstellungen); the staff page saves
the whole file back (atomically) and the backend applies it live.
"""
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from nametag import REPO

CONFIG = REPO / "config" / "booth.json"
COMMENT = ("Booth settings, edited by staff in the morning (staff page: Einstellungen, applied live). "
           "Prices in euro cents. Printer: type sim | prusalink. print_setup: null = 'active' from print.json.")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ID = re.compile(r"^[a-z0-9_-]{1,20}$")


@dataclass
class BoothConfig:
    event_name: str
    base_color: dict
    text_colors: list[dict]
    free_tags: int
    price_per_extra_cents: int
    max_tags_per_order: int
    queue_limit: int
    plate_max_tags: int
    plate_max_wait_min: float
    plate_change_min: float          # staff time between plates (bed + filament)
    staff_pin: str
    printer: dict
    disabled_fonts: list[str] = field(default_factory=list)
    disabled_shapes: list[str] = field(default_factory=list)
    plate_prep_min: float = 6.5      # printer time per plate outside the slicer estimate
                                     # (heat-up, mesh levelling, end G-code; Core One, warm bed)
    kiosk_idle_s: int = 90
    kiosk_sound: bool = True
    print_setup: str | None = None
    data_dir: Path = field(default_factory=lambda: REPO / "backend" / "data")
    path: Path | None = None         # file it was loaded from (save target)
    file_pin: str | None = None      # set when BOOTH_PIN overrides the file PIN (kept in the file)

    def color(self, color_id: str) -> dict:
        for c in self.text_colors:
            if c["id"] == color_id:
                return c
        raise KeyError(color_id)

    def price_cents(self, n_tags: int) -> int:
        return max(0, n_tags - self.free_tags) * self.price_per_extra_cents


class ConfigError(ValueError):
    pass


def _int(d: dict, key: str, lo: int, hi: int) -> int:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or not lo <= v <= hi:
        raise ConfigError(f"{key}: ganze Zahl {lo}..{hi} erwartet")
    return int(v)


def _num(d: dict, key: str, lo: float, hi: float) -> float:
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ConfigError(f"{key}: Zahl {lo}..{hi} erwartet")
    return float(v)


def _str(d: dict, key: str, max_len: int = 60, empty: bool = False) -> str:
    v = d.get(key, "")
    if not isinstance(v, str) or len(v) > max_len or (not empty and not v.strip()):
        raise ConfigError(f"{key}: Text erwartet (max. {max_len} Zeichen)")
    return v.strip()


def _color(c, what: str) -> dict:
    if not isinstance(c, dict) or not _HEX.match(str(c.get("hex", ""))):
        raise ConfigError(f"{what}: Farbe #RRGGBB erwartet")
    name = c.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 20:
        raise ConfigError(f"{what} {c['hex'].upper()}: Name fehlt (max. 20 Zeichen)")
    return {"name": name.strip(), "hex": c["hex"].upper()}


def parse_config(c: dict) -> BoothConfig:
    """Validate a booth.json dict (file or staff page) -> BoothConfig."""
    try:
        colors = []
        for t in c["text_colors"]:
            col = _color(t, "Textfarbe")
            if not _ID.match(str(t.get("id", ""))):
                raise ConfigError(f"Textfarbe {col['name']}: ungültige id")
            colors.append({"id": t["id"], **col})
        if not colors:
            raise ConfigError("mindestens eine Textfarbe nötig")
        if len({t["id"] for t in colors}) != len(colors):
            raise ConfigError("doppelte Textfarben-id")
        pr, pl, k = c["pricing"], c["plate"], c.get("kiosk", {})
        p = dict(c["printer"])
        if p.get("type") not in ("sim", "prusalink"):
            raise ConfigError("printer.type: sim oder prusalink")
        if p["type"] == "prusalink" and not str(p.get("host", "")).strip():
            raise ConfigError("Drucker: Host/IP fehlt")
        pin = str(c["staff_pin"])
        if not re.fullmatch(r"\d{4,8}", pin):
            raise ConfigError("PIN: 4 bis 8 Ziffern")
        cfg = BoothConfig(
            event_name=_str(c, "event_name", 60, empty=True),
            base_color=_color(c["base_color"], "Grundfarbe"),
            text_colors=colors,
            free_tags=_int(pr, "free_tags", 0, 10),
            price_per_extra_cents=_int(pr, "price_per_extra_cents", 0, 10000),
            max_tags_per_order=_int(c, "max_tags_per_order", 1, 20),
            queue_limit=_int(c, "queue_limit", 1, 500),
            plate_max_tags=_int(pl, "max_tags", 1, 40),
            plate_max_wait_min=_num(pl, "max_wait_min", 0, 240),
            plate_change_min=_num(pl, "change_min", 0, 60),
            plate_prep_min=_num({"prep_min": pl.get("prep_min", 6.5)}, "prep_min", 0, 30),
            staff_pin=pin,
            printer=p,
            disabled_fonts=[str(x) for x in c.get("disabled_fonts", [])],
            disabled_shapes=[str(x) for x in c.get("disabled_shapes", [])],
            kiosk_idle_s=_int({"idle_s": k.get("idle_s", 90)}, "idle_s", 20, 600),
            kiosk_sound=bool(k.get("sound", True)),
            print_setup=c.get("print_setup") or None,
        )
    except KeyError as e:
        raise ConfigError(f"Einstellung fehlt: {e.args[0]}") from None
    return cfg


def config_dict(cfg: BoothConfig) -> dict:
    """BoothConfig -> booth.json structure."""
    return {
        "_comment": COMMENT,
        "event_name": cfg.event_name,
        "base_color": cfg.base_color,
        "text_colors": cfg.text_colors,
        "pricing": {"free_tags": cfg.free_tags, "price_per_extra_cents": cfg.price_per_extra_cents},
        "max_tags_per_order": cfg.max_tags_per_order,
        "queue_limit": cfg.queue_limit,
        "plate": {"max_tags": cfg.plate_max_tags, "max_wait_min": cfg.plate_max_wait_min,
                  "change_min": cfg.plate_change_min, "prep_min": cfg.plate_prep_min},
        "kiosk": {"idle_s": cfg.kiosk_idle_s, "sound": cfg.kiosk_sound},
        "disabled_fonts": cfg.disabled_fonts,
        "disabled_shapes": cfg.disabled_shapes,
        "print_setup": cfg.print_setup,
        "staff_pin": cfg.file_pin or cfg.staff_pin,
        "printer": cfg.printer,
    }


def save_config(cfg: BoothConfig) -> None:
    """Write cfg to cfg.path atomically."""
    if not cfg.path:
        return
    d = config_dict(cfg)
    tmp = cfg.path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    tmp.replace(cfg.path)


def load_config(path: Path = CONFIG, data_dir: Path | None = None) -> BoothConfig:
    c = json.loads(path.read_text())
    env_pin = os.environ.get("BOOTH_PIN")
    cfg = parse_config(c)
    cfg.path = path
    if env_pin:
        cfg.file_pin, cfg.staff_pin = cfg.staff_pin, env_pin
    if data_dir or os.environ.get("BOOTH_DATA"):
        cfg.data_dir = Path(data_dir or os.environ["BOOTH_DATA"])
    return cfg
