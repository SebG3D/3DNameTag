"""Shape plugin registry.

Every folder in scad/shapes/ with a shape.json + shape.scad is one shape.
shape.scad defines  module outline(tw, th)  and  function hole_pos(tw, th).
shape.json:
  id, label {de, en}, order, mode ("grow" | "fit"),
  text: grow -> {size, max_w, min_size}
        fit  -> {size, min_size, box {cx, cy, w, h}, k_max}
"""
import json
from dataclasses import dataclass
from pathlib import Path

from . import SCAD_DIR


class ShapeError(ValueError):
    pass


@dataclass(frozen=True)
class Shape:
    id: str
    label: dict
    order: int
    mode: str
    text: dict
    scad: Path
    dir: Path


def _check(meta: dict, folder: Path) -> None:
    need = {"id", "label", "mode", "text"}
    if missing := need - meta.keys():
        raise ShapeError(f"{folder.name}: shape.json misses {sorted(missing)}")
    if meta["id"] != folder.name:
        raise ShapeError(f"{folder.name}: id {meta['id']!r} must equal folder name")
    t = meta["text"]
    if meta["mode"] == "grow":
        keys = {"size", "max_w", "min_size"}
    elif meta["mode"] == "fit":
        keys = {"size", "min_size", "box", "k_max"}
        if set(t.get("box", {})) != {"cx", "cy", "w", "h"}:
            raise ShapeError(f"{folder.name}: text.box needs cx, cy, w, h")
    else:
        raise ShapeError(f"{folder.name}: mode must be grow or fit")
    if missing := keys - t.keys():
        raise ShapeError(f"{folder.name}: text misses {sorted(missing)}")


def load_shapes(shape_dir: Path = SCAD_DIR / "shapes") -> dict[str, Shape]:
    shapes = []
    for folder in sorted(p for p in shape_dir.iterdir() if p.is_dir()):
        meta_file, scad = folder / "shape.json", folder / "shape.scad"
        if not (meta_file.exists() and scad.exists()):
            continue
        meta = json.loads(meta_file.read_text())
        _check(meta, folder)
        shapes.append(Shape(meta["id"], meta["label"], meta.get("order", 100),
                            meta["mode"], meta["text"], scad, folder))
    shapes.sort(key=lambda s: (s.order, s.id))
    return {s.id: s for s in shapes}
