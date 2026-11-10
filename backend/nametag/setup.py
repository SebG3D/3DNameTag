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
    layer_h: float        # base layers (profile layer_height)
    first_layer_h: float
    text_layer_h: float   # text layers (layer range in the plate 3MF)
    color_change: str = "tower"   # "tower": purge on a wipe tower | "wiper": purge + wipe on the Core One+ wiper
    wiper_z: float = -0.6         # wiper mode: Z of the wipe pass (pad top ~0.2 above the touchpoint, measured with G12)

    @property
    def text_layers(self) -> int:
        return round(self.text_h / self.text_layer_h)

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
    text_layer = e.get("text_layer_h", layer)
    m = e["text_h"] / text_layer
    if m < 1 or abs(m - round(m)) > 1e-6:
        raise ValueError(f"{name}: text_h {e['text_h']} is not n * text_layer_h {text_layer}")
    if e["text_overlap"] > layer + 1e-9:
        raise ValueError(f"{name}: text_overlap must not exceed one base layer ({layer})")
    cc = e.get("color_change", "tower")
    if cc not in ("tower", "wiper"):
        raise ValueError(f"{name}: color_change must be 'tower' or 'wiper'")
    return PrintSetup(name, profile, e["scale"], e["min_text_size"], e["base_h"], e["text_h"],
                      e["text_overlap"], e["hole_d"], e["text_grow"], layer, first, text_layer,
                      cc, float(e.get("wiper_z", -0.6)))


def list_setups(config: Path = CONFIG) -> tuple[str, dict]:
    """(active name, {name: raw setup dict}) from print.json."""
    cfg = json.loads(config.read_text())
    return cfg["active"], cfg["setups"]
