#!/usr/bin/env python3
"""Render every shape with test names (and every font once) into a contact
sheet, print layout numbers. Use after adding or changing a shape plugin.

  python3 tools/check_shapes.py [out.png] [--stl] [--setup nozzle040]
Sizes on the sheet are printed mm (setup scale applied).
"""
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from nametag.fonts import load_fonts          # noqa: E402
from nametag.render import layout, render_svg, render_tag, svg_bbox  # noqa: E402
from nametag.setup import load_setup           # noqa: E402
from nametag.shapes import load_shapes         # noqa: E402

NAMES = ["LI", "EMMA", "MAXIMILIAN", "ÄÖÜ-ß 1234AB"]
CELL_W, CELL_H, MM = 300, 260, 2.6   # px per cell, px per mm


def cell(x, y, outline, text, label, ok):
    bx0, by0, bx1, by1 = svg_bbox(f'<path d="{outline}"/>')
    cx, cy = (bx0 + bx1) / 2, -(by0 + by1) / 2          # centre in SVG coords
    tr = f"translate({x + CELL_W / 2 - cx * MM},{y + CELL_H / 2 - 10 - cy * MM}) scale({MM})"
    col = "#222" if ok else "#c00"
    return (f'<g transform="{tr}"><path d="{outline}" fill="#1565C0" fill-rule="evenodd"/>'
            f'<path d="{text}" fill="#FDD835" stroke="#000" stroke-width="0.15"/></g>'
            f'<text x="{x + 6}" y="{y + CELL_H - 8}" font-size="13" fill="{col}">{label}</text>'
            f'<text x="{x + 6}" y="{y + CELL_H - 24}" font-size="11" fill="#666">'
            f'{bx1 - bx0:.0f} x {by1 - by0:.0f} mm</text>')


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else Path("shapes_check.png")
    setup = load_setup(sys.argv[sys.argv.index("--setup") + 1] if "--setup" in sys.argv else None)
    print(f"setup {setup.name}: scale {setup.scale}, min text {setup.min_text_size} mm, {setup.profile.name}")
    fonts, shapes = load_fonts(), load_shapes()
    jobs = [(s, fonts["baloo"], n) for s in shapes.values() for n in NAMES]
    jobs += [(shapes["stadium"], f, "WEIHNACHTEN") for f in fonts.values()]
    cols = len(NAMES)
    parts, tmp = [], Path(tempfile.mkdtemp())
    for i, (shape, font, name) in enumerate(jobs):
        lay = layout(name, font, shape, setup)
        o, t = render_svg(name, font, shape, setup, tmp / "c.svg")
        label = f"{shape.id}/{font.id} {name} {lay.printed_size:.1f}mm k={lay.k:.2f}" + ("" if lay.fits else " NO FIT")
        print(label)
        parts.append(cell((i % cols) * CELL_W, (i // cols) * CELL_H, o, t, label, lay.fits))
    rows = (len(jobs) + cols - 1) // cols
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{cols * CELL_W}" height="{rows * CELL_H}">'
           f'<rect width="100%" height="100%" fill="#fff"/>' + "".join(parts) + "</svg>")
    (tmp / "sheet.svg").write_text(svg)
    subprocess.run(["rsvg-convert", "-o", str(out), str(tmp / "sheet.svg")], check=True)
    print(f"sheet: {out}")
    if "--stl" in sys.argv:
        for shape in shapes.values():
            t0 = time.time()
            r = render_tag("MAXIMILIAN", fonts["pacifico"], shape, setup, tmp / "stl", shape.id)
            sizes = {k: f"{v.stat().st_size // 1024} KiB" for k, v in r["files"].items()}
            print(f"stl {shape.id}: {time.time() - t0:.2f} s {sizes}")
        print(f"stl dir: {tmp / 'stl'}")


if __name__ == "__main__":
    main()
