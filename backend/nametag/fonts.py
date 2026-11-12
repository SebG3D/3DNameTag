"""Font registry (fonts/fonts.json, built by tools/build_fonts.py)."""
import json
from dataclasses import dataclass
from pathlib import Path

from . import FONT_DIR


@dataclass(frozen=True)
class Font:
    id: str
    label: str
    openscad: str       # "Family:style=Style" as OpenSCAD knows it
    ttf: Path
    woff2: Path
    spacing: float = 1.0        # OpenSCAD text(spacing=), > 1 for tight fonts
    min_text_add: float = 0.0   # mm added to the setup's min_text_size (fat fonts)


def load_fonts(font_dir: Path = FONT_DIR) -> dict[str, Font]:
    fonts = {}
    for e in json.loads((font_dir / "fonts.json").read_text()):
        f = Font(e["id"], e["label"], e["openscad"],
                 font_dir / "ttf" / f"{e['id']}.ttf", font_dir / "woff2" / f"{e['id']}.woff2",
                 float(e.get("spacing", 1.0)), float(e.get("min_text_add", 0.0)))
        if not f.ttf.exists():
            raise FileNotFoundError(f"{f.ttf} missing - run tools/build_fonts.py")
        fonts[f.id] = f
    return fonts
