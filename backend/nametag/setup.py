"""Print setup (config/print.json): nozzle profile + geometry that depends on it."""
import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import REPO

CONFIG = REPO / "config" / "print.json"
PROFILE_DIR = REPO / "slicer" / "profiles"


@dataclass(frozen=True)
class PrintSetup:
    name: str
    profile: Path
    scale: float          # all shapes and their text, not the hole
    min_text_size: float  # absolute font size below which a name "does not fit"
    base_h: float
    text_h: float
    text_overlap: float
    hole_d: float
    text_grow: float
    layer_h: float
    first_layer_h: float

    def scad_defines(self) -> dict:
        return {"s": self.scale, "base_h": self.base_h, "text_h": self.text_h,
                "text_overlap": self.text_overlap, "hole_d": self.hole_d, "text_grow": self.text_grow}


def _ini_value(profile: Path, key: str) -> float:
    m = re.search(rf"^{key} = (.*)$", profile.read_text(), re.M)
    if not m:
        raise ValueError(f"{key} missing in {profile}")
    return float(m[1])


def load_setup(name: str | None = None, config: Path = CONFIG) -> PrintSetup:
    cfg = json.loads(config.read_text())
    name = name or cfg["active"]
    e = cfg["setups"][name]
    profile = PROFILE_DIR / e["profile"]
    layer, first = _ini_value(profile, "layer_height"), _ini_value(profile, "first_layer_height")
    n = (e["base_h"] - first) / layer
    if n < 1 or abs(n - round(n)) > 1e-6:
        raise ValueError(f"{name}: base_h {e['base_h']} is not first_layer {first} + n * layer {layer}")
    return PrintSetup(name, profile, e["scale"], e["min_text_size"], e["base_h"], e["text_h"],
                      e["text_overlap"], e["hole_d"], e["text_grow"], layer, first)
