#!/usr/bin/env python3
"""Build a test plate G-code from the command line (for real test prints).

  python3 tools/make_plate.py -o out/ EMMA:baloo:stadium "OMA:titan:tree" LEON:chewy:bell
  python3 tools/make_plate.py -o out/ --all-shapes EMMA      # one per shape
  python3 tools/make_plate.py -o out/ --all-fonts WEIHNACHTEN

Writes out/plate.3mf (text layer range, open in PrusaSlicer to inspect) and
out/plate.gcode (M600 at the first text layer, plain G-code for the
Core One via USB stick or PrusaLink upload) and prints the plate map.
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from nametag.fonts import load_fonts                 # noqa: E402
from nametag.names import clean_name                 # noqa: E402
from nametag.plate import build_plate                # noqa: E402
from nametag.render import render_tag                # noqa: E402
from nametag.setup import load_setup                 # noqa: E402
from nametag.shapes import load_shapes               # noqa: E402
from nametag.slicer import slice_plate               # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*", help="NAME[:font[:shape]]")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--all-shapes", action="store_true", help="each name once per shape")
    ap.add_argument("--all-fonts", action="store_true", help="each name once per font (stadium)")
    ap.add_argument("--setup", help="setup name from config/print.json (default: active)")
    a = ap.parse_args()
    setup = load_setup(a.setup)
    fonts, shapes = load_fonts(), load_shapes()
    specs = []
    for t in a.tags:
        name, font, shape = (t.split(":") + ["baloo", "stadium"][len(t.split(":")) - 1:])[:3]
        if a.all_shapes:
            specs += [(name, font, s) for s in shapes]
        elif a.all_fonts:
            specs += [(name, f, shape) for f in fonts]
        else:
            specs.append((name, font, shape))
    if not specs:
        ap.error("no tags")
    a.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    stls, labels = {}, {}
    for i, (raw, font, shape) in enumerate(specs):
        name = clean_name(raw)
        r = render_tag(name, fonts[font], shapes[shape], setup, a.out / "tags", f"t{i:02d}")
        stls[f"t{i:02d}"] = r["files"]["tag"]
        labels[f"t{i:02d}"] = f"{name} ({font}, {shape}, text {r['layout'].printed_size:.1f} mm)"
    placed, rest = build_plate(stls, a.out / "plate.3mf", setup)
    res = slice_plate([a.out / "plate.3mf"], a.out / "plate.gcode", setup)
    print(f"setup {setup.name} ({setup.profile.name}, scale {setup.scale})")
    print(f"plate: {len(placed)} tags, est. {res.estimated_s / 60:.0f} min, M600 at Z={res.color_change_z}, "
          f"built in {time.time() - t0:.1f} s -> {res.gcode}")
    for p in sorted(placed, key=lambda p: (p.y, p.x)):
        print(f"  x={p.x:6.1f} y={p.y:6.1f}  {p.w:5.1f} x {p.h:5.1f} mm  {labels[p.key]}")
    for k in rest:
        print(f"  DID NOT FIT: {labels[k]}")


if __name__ == "__main__":
    main()
