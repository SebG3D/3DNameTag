"""OpenSCAD rendering: text measuring, layout, tag STL/SVG export."""
import re
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, asdict
from functools import lru_cache
from pathlib import Path

from . import SCAD_DIR
from .fonts import Font
from .setup import PrintSetup
from .shapes import Shape

OPENSCAD = os.environ.get("OPENSCAD") or shutil.which("openscad") or "openscad"
MEASURE_SIZE = 10.0
_NUM = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Layout:
    fits: bool
    size: float      # font size in design units (printed: size * setup.scale)
    tx: float        # centres the text bbox at the origin (text frame)
    ty: float
    rot: float       # text rotation in degrees (0 or 90)
    cx: float        # text box centre on the tag (design units, incl. k)
    cy: float
    tw: float        # text bbox on the tag (design units)
    th: float
    k: float         # outline scale (fit shapes)
    printed_size: float
    reason: str = ""

    def defines(self) -> dict:
        return {k: v for k, v in asdict(self).items()
                if k in ("size", "tx", "ty", "rot", "cx", "cy", "tw", "th", "k")}


def _wrapper(font: Font, shape: Shape | None) -> str:
    lines = [f"use <{font.ttf}>"]
    if shape:
        lines.append(f"use <{shape.scad}>")
    lines.append(f"include <{SCAD_DIR / 'lib' / 'tag.scad'}>")
    return "\n".join(lines) + "\n"


def _scad_value(v) -> str:
    if isinstance(v, str):
        if '"' in v or "\\" in v:
            raise RenderError("quote in string value")
        return f'"{v}"'
    return repr(float(v))


def run_openscad(font: Font, shape: Shape | None, out: Path, defines: dict) -> str:
    """Render the tag wrapper to `out` (format by suffix). Returns stderr (echo output)."""
    with tempfile.TemporaryDirectory(prefix="tag_") as tmp:
        wrapper = Path(tmp) / "tag.scad"
        wrapper.write_text(_wrapper(font, shape))
        cmd = [OPENSCAD, "-q", "-o", str(out)]
        for k, v in defines.items():
            cmd += ["-D", f"{k}={_scad_value(v)}"]
        cmd.append(str(wrapper))
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not out.exists() or "ERROR" in r.stderr:
        raise RenderError(f"openscad failed ({r.returncode}): {r.stderr.strip()[-500:]}")
    return r.stderr


def svg_bbox(svg: str) -> tuple[float, float, float, float]:
    """Bounding box (x0, y0, x1, y1) in OpenSCAD coordinates of an OpenSCAD SVG
    export (paths only contain M/L/z with absolute coordinates, y flipped)."""
    xs, ys = [], []
    for d in re.findall(r'd="([^"]*)"', svg):
        nums = [float(n) for n in _NUM.findall(d)]
        xs += nums[0::2]
        ys += [-y for y in nums[1::2]]
    if not xs:
        raise RenderError("empty SVG")
    return min(xs), min(ys), max(xs), max(ys)


@lru_cache(maxsize=512)
def _measure_cached(name: str, font: Font) -> tuple[float, float, float, float]:
    with tempfile.TemporaryDirectory(prefix="measure_") as tmp:
        out = Path(tmp) / "text.svg"
        run_openscad(font, None, out, {"name": name, "font": font.openscad,
                                       "size": MEASURE_SIZE, "part": "measure2d"})
        return svg_bbox(out.read_text())


def measure_text(name: str, font: Font) -> tuple[float, float, float, float]:
    """Text bbox at MEASURE_SIZE, exactly as OpenSCAD shapes it."""
    return _measure_cached(name, font)


def layout(name: str, font: Font, shape: Shape, setup: PrintSetup) -> Layout:
    """Text size, position and outline scale for one tag (design units)."""
    x0, y0, x1, y1 = measure_text(name, font)
    w10, h10 = x1 - x0, y1 - y0
    t = shape.text
    rot = float(t.get("rotate", 0))
    if rot % 180 == 90:
        ow, oh = h10, w10               # text bbox as it lies on the tag
    elif rot % 180 == 0:
        ow, oh = w10, h10
    else:
        raise ValueError(f"{shape.id}: rotate must be a multiple of 90")
    target = t["size"]
    if shape.mode == "grow":
        k, cx, cy = 1.0, 0.0, 0.0
        size = min(target, t["max_w"] * MEASURE_SIZE / ow)
    else:
        box = t["box"]
        fit1 = min(box["w"] / ow, box["h"] / oh) * MEASURE_SIZE   # size that fits at k=1
        k = min(t["k_max"], max(1.0, target / fit1))
        size = min(target, fit1 * k)
        cx, cy = box["cx"] * k, box["cy"] * k
    sc = size / MEASURE_SIZE
    printed = size * setup.scale
    fits = printed >= setup.min_text_size - 1e-6
    reason = "" if fits else f"text too long for {shape.id} ({printed:.1f} mm < {setup.min_text_size} mm)"
    r = lambda v: round(v, 4)
    return Layout(fits, r(size), r(-(x0 + x1) / 2 * sc), r(-(y0 + y1) / 2 * sc), rot, r(cx), r(cy),
                  r(ow * sc), r(oh * sc), r(k), r(printed), reason)


def _stl_facets(path: Path) -> str:
    body = path.read_text()
    start = body.index("\n") + 1                 # after "solid ..."
    end = body.rindex("endsolid")
    return body[start:end]


def render_tag(name: str, font: Font, shape: Shape, setup: PrintSetup, out_dir: Path, stem: str = "tag") -> dict:
    """Render base + text STLs and the joined tag STL (two shells, the text
    overlapping the base by one layer). Returns paths and the layout."""
    lay = layout(name, font, shape, setup)
    if not lay.fits:
        raise RenderError(lay.reason)
    out_dir.mkdir(parents=True, exist_ok=True)
    common = {"name": name, "font": font.openscad, **lay.defines(), **setup.scad_defines()}
    files = {}
    for part in ("base", "text"):
        p = out_dir / f"{stem}_{part}.stl"
        run_openscad(font, shape, p, {**common, "part": part})
        files[part] = p
    joined = out_dir / f"{stem}.stl"
    joined.write_text(f"solid {stem}\n" + _stl_facets(files["base"]) + _stl_facets(files["text"])
                      + f"endsolid {stem}\n")
    files["tag"] = joined
    return {"layout": lay, "files": files}


def render_svg(name: str, font: Font, shape: Shape, setup: PrintSetup, out: Path) -> tuple[str, str]:
    """2D outline and text as SVG path data (for the kiosk preview and checks)."""
    lay = layout(name, font, shape, setup)
    common = {"name": name, "font": font.openscad, **lay.defines(), **setup.scad_defines()}
    res = []
    for part in ("outline2d", "text2d"):
        p = out.with_name(f"{out.stem}_{part}.svg")
        run_openscad(font, shape, p, {**common, "part": part})
        res.append(" ".join(" ".join(re.findall(r'd="([^"]*)"', p.read_text())).split()))
        p.unlink()
    return res[0], res[1]
