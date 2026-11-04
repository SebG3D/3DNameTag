"""Plate building: pack tags on the bed and merge them into one 3MF.

The 3MF carries a PrusaSlicer layer range so the text gets its own layer
height (setup.text_layer_h) while the base uses the profile's layer height.

Own packing instead of PrusaSlicer's arrange: positions are known (plate map
on the staff page for sorting at pickup) and `--merge` crashes in 2.9 CLI.
"""
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .setup import PrintSetup

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


_3MF_TYPES = ('<?xml version="1.0" encoding="UTF-8"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
              '</Types>')
_3MF_RELS = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
             'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')


def write_3mf(path: Path, tris: np.ndarray, layer_ranges: list[tuple[float, float, float]] = ()) -> None:
    """One object, vertices in bed coordinates (identity transform; slice with
    --dont-arrange). layer_ranges: (min_z, max_z, layer_height) as PrusaSlicer
    height-range modifiers (Metadata/Prusa_Slicer_layer_config_ranges.xml)."""
    v, idx = np.unique(np.round(tris.reshape(-1, 3), 5), axis=0, return_inverse=True)
    idx = idx.reshape(-1, 3)
    idx = idx[(idx[:, 0] != idx[:, 1]) & (idx[:, 1] != idx[:, 2]) & (idx[:, 0] != idx[:, 2])]
    verts = "".join(f'<vertex x="{x:.5f}" y="{y:.5f}" z="{z:.5f}"/>' for x, y, z in v)
    faces = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in idx)
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<resources><object id="1" type="model"><mesh><vertices>{verts}</vertices>'
             f'<triangles>{faces}</triangles></mesh></object></resources>'
             '<build><item objectid="1" transform="1 0 0 0 1 0 0 0 1 0 0 0" printable="1"/></build></model>')
    ranges = "".join(f'<range min_z="{z0:g}" max_z="{z1:g}"><option opt_key="extruder">0</option>'
                     f'<option opt_key="layer_height">{lh:g}</option></range>' for z0, z1, lh in layer_ranges)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _3MF_TYPES)
        z.writestr("_rels/.rels", _3MF_RELS)
        z.writestr("3D/3dmodel.model", model)
        if layer_ranges:
            z.writestr("Metadata/Prusa_Slicer_layer_config_ranges.xml",
                       f'<?xml version="1.0" encoding="utf-8"?><objects><object id="1">{ranges}</object></objects>')


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


def build_plate(tags: dict[str, Path], out: Path, setup: PrintSetup) -> tuple[list[Placed], list[str]]:
    """tags: key -> joined tag STL. Writes the plate to `out` (.3mf with the
    text layer range, or .stl without)."""
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
    tris = np.concatenate(parts)
    if out.suffix == ".3mf":
        rng = []
        if abs(setup.text_layer_h - setup.layer_h) > 1e-9:
            rng = [(setup.base_h, round(setup.base_h + setup.text_h, 4), setup.text_layer_h)]
        write_3mf(out, tris, rng)
    else:
        write_stl(out, tris)
    return placed, rest
