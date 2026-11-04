"""Plate building: pack tags on the bed and merge them into one STL.

Own packing instead of PrusaSlicer's arrange: positions are known (plate map
on the staff page for sorting at pickup) and `--merge` crashes in 2.9 CLI.
"""
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

BED = (250.0, 220.0)    # Core One bed, mm
MARGIN = 12.0           # keep clear of the bed edge (purge line at the front)
GAP = 6.0               # between tags

_VERTEX = re.compile(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)")


def load_stl(path: Path) -> np.ndarray:
    """ASCII STL -> (n, 3, 3) float array."""
    v = np.array(_VERTEX.findall(path.read_text()), dtype=float)
    return v.reshape(-1, 3, 3)


def write_stl(path: Path, tris: np.ndarray, name: str = "plate") -> None:
    """Binary STL (normals left zero, slicers recompute them)."""
    n = len(tris)
    rec = np.zeros(n, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["v"] = tris
    with open(path, "wb") as f:
        f.write(name.encode()[:80].ljust(80, b"\0"))
        f.write(np.uint32(n).tobytes())
        f.write(rec.tobytes())


@dataclass
class Placed:
    key: str
    x: float          # min corner on the bed after placement
    y: float
    w: float
    h: float
    rotated: bool = False


def pack(items: list[tuple[str, float, float]], bed=BED, margin=MARGIN, gap=GAP) -> tuple[list[Placed], list[str]]:
    """Shelf packing, tallest first. items: (key, w, h). Returns placed items and
    keys that did not fit. Wide tags lying across a shelf are fine; tags are
    never rotated (kept simple, text stays readable on the plate map)."""
    W, H = bed[0] - 2 * margin, bed[1] - 2 * margin
    order = sorted(items, key=lambda it: (-it[2], -it[1]))
    placed, rest = [], []
    x = y = shelf_h = 0.0
    for key, w, h in order:
        if w > W or h > H:
            rest.append(key)
            continue
        if x + w > W:                       # next shelf
            x, y, shelf_h = 0.0, y + shelf_h + gap, 0.0
        if y + h > H:
            rest.append(key)
            continue
        placed.append(Placed(key, margin + x, margin + y, w, h))
        x += w + gap
        shelf_h = max(shelf_h, h)
    return placed, rest


def build_plate(tags: dict[str, Path], out: Path) -> tuple[list[Placed], list[str]]:
    """tags: key -> joined tag STL. Writes the merged plate STL to `out`."""
    meshes, items = {}, []
    for key, stl in tags.items():
        t = load_stl(stl)
        lo, hi = t.reshape(-1, 3).min(0), t.reshape(-1, 3).max(0)
        meshes[key] = (t, lo)
        items.append((key, hi[0] - lo[0], hi[1] - lo[1]))
    placed, rest = pack(items)
    if not placed:
        raise ValueError("nothing fits on the plate")
    parts = []
    for p in placed:
        t, lo = meshes[p.key]
        parts.append(t + np.array([p.x - lo[0], p.y - lo[1], -lo[2]]))
    write_stl(out, np.concatenate(parts))
    return placed, rest
