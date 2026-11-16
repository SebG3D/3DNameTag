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
    text_temp: float = 0.0        # wiper mode: nozzle temperature for the text colour
    nozzle: float = 0.0           # nozzle diameter of the profile (the printer must report the same)
    material: str = ""            # filament_type of the profile, lower case ("petg", "pla")

    @property
    def text_layers(self) -> int:
        return round(self.text_h / self.text_layer_h)

    def scad_defines(self) -> dict:
        return {"s": self.scale, "base_h": self.base_h, "text_h": self.text_h,
                "text_overlap": self.text_overlap, "hole_d": self.hole_d, "text_grow": self.text_grow}


def _ini_str(profile: Path, key: str) -> str:
    m = re.search(rf"^{key} = (.*)$", profile.read_text(), re.M)
    if not m:
        raise ValueError(f"{key} missing in {profile}")
    return m[1].split(",")[0].strip()         # per-extruder lists ("0.25,0.25"): first tool


def _ini_value(profile: Path, key: str) -> float:
    return float(_ini_str(profile, key))


def setup_materials(e: dict) -> list[str]:
    """Materials a print.json setup entry can print: its own profile's
    filament + the variants under "materials" (e.g. {"pla": {"profile": ...}})."""
    own = _ini_str(PROFILE_DIR / e["profile"], "filament_type").lower()
    return [own] + [m for m in e.get("materials", {}) if m != own]


def load_setup(name: str | None = None, config: Path = CONFIG, material: str | None = None) -> PrintSetup:
    """material: filament to print with (None = the setup's own profile). A
    variant only swaps the profile (+ e.g. text_temp_delta); layer heights and
    nozzle must stay the same, so already rendered tags stay valid."""
    cfg = json.loads(config.read_text())
    name = name or cfg["active"]
    e = cfg["setups"][name]
    own = PROFILE_DIR / e["profile"]
    if material and material != _ini_str(own, "filament_type").lower():
        variant = e.get("materials", {}).get(material)
        if variant is None:
            raise ValueError(f"{name}: kein {material.upper()}-Profil (print.json materials)")
        e = {**e, **variant}
        p = PROFILE_DIR / e["profile"]
        for key in ("layer_height", "first_layer_height", "nozzle_diameter"):
            if _ini_value(p, key) != _ini_value(own, key):
                raise ValueError(f"{name}: {material} profile {p.name} has another {key} than {own.name}")
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
                      cc, float(e.get("wiper_z", -0.6)),
                      _ini_value(profile, "temperature") + float(e.get("text_temp_delta", 0)),
                      _ini_value(profile, "nozzle_diameter"),
                      _ini_str(profile, "filament_type").lower())


def list_setups(config: Path = CONFIG) -> tuple[str, dict]:
    """(active name, {name: raw setup dict}) from print.json."""
    cfg = json.loads(config.read_text())
    return cfg["active"], cfg["setups"]
