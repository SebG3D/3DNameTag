#!/usr/bin/env python3
"""Build the booth font set from fonts/src (upstream Google Fonts files).

Writes for every font in fonts/fonts.json:
  fonts/ttf/<id>.ttf     static TTF (variable fonts instanced) for OpenSCAD
  fonts/woff2/<id>.woff2 same font for the kiosk UI
and checks that every character the kiosk keyboard can type has a glyph.

Run after changing fonts/fonts.json:  python3 tools/build_fonts.py
"""
import json
import sys
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
# must match the kiosk keyboard (A-Z, digits, umlauts, ß, space, hyphen)
CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ÄÖÜß -"


def build(entry):
    font = TTFont(FONTS / "src" / entry["src"])
    if "fvar" in font:
        axes = {a.axisTag: a.defaultValue for a in font["fvar"].axes}
        axes.update(entry.get("axes", {}))
        font = instancer.instantiateVariableFont(font, axes, updateFontNames=True)
    cmap = font.getBestCmap()
    missing = [c for c in CHARSET if ord(c) not in cmap]
    if missing:
        raise SystemExit(f"{entry['id']}: missing glyphs {''.join(missing)!r}")
    (FONTS / "ttf").mkdir(exist_ok=True)
    (FONTS / "woff2").mkdir(exist_ok=True)
    font.flavor = None
    font.save(FONTS / "ttf" / f"{entry['id']}.ttf")
    font.flavor = "woff2"
    font.save(FONTS / "woff2" / f"{entry['id']}.woff2")
    name = font["name"]
    family = name.getDebugName(16) or name.getDebugName(1)
    style = name.getDebugName(17) or name.getDebugName(2)
    actual = f"{family}:style={style}"
    if actual != entry["openscad"]:
        raise SystemExit(f"{entry['id']}: font names itself {actual!r}, "
                         f"fonts.json says {entry['openscad']!r}")
    print(f"ok  {entry['id']:9} {actual}")


def main():
    entries = json.loads((FONTS / "fonts.json").read_text())
    for e in entries:
        build(e)


if __name__ == "__main__":
    sys.exit(main())
