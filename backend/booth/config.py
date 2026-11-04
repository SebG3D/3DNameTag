"""Booth config (config/booth.json)."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from nametag import REPO

CONFIG = REPO / "config" / "booth.json"


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
    data_dir: Path = field(default_factory=lambda: REPO / "backend" / "data")

    def color(self, color_id: str) -> dict:
        for c in self.text_colors:
            if c["id"] == color_id:
                return c
        raise KeyError(color_id)

    def price_cents(self, n_tags: int) -> int:
        return max(0, n_tags - self.free_tags) * self.price_per_extra_cents


def load_config(path: Path = CONFIG, data_dir: Path | None = None) -> BoothConfig:
    c = json.loads(path.read_text())
    pin = os.environ.get("BOOTH_PIN", c["staff_pin"])
    cfg = BoothConfig(c["event_name"], c["base_color"], c["text_colors"],
                      c["pricing"]["free_tags"], c["pricing"]["price_per_extra_cents"],
                      c["max_tags_per_order"], c["queue_limit"],
                      c["plate"]["max_tags"], c["plate"]["max_wait_min"], c["plate"]["change_min"],
                      pin, c["printer"])
    if data_dir or os.environ.get("BOOTH_DATA"):
        cfg.data_dir = Path(data_dir or os.environ["BOOTH_DATA"])
    if len({t["id"] for t in cfg.text_colors}) != len(cfg.text_colors):
        raise ValueError("duplicate text colour id")
    return cfg
