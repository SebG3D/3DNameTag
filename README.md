# 3DNameTagBooth

Kiosk for the Christmas booth: kids type a name, pick font, shape and text
colour; tags are printed in batches on a Prusa Core One (base colour of the
day + text colour via M600). Plan: `docs/PLAN.md`.

## Layout
- `fonts/` – six OFL/Apache fonts: `src/` upstream, `ttf/` + `woff2/` built by `tools/build_fonts.py`, list in `fonts.json`
- `scad/lib/tag.scad` – tag core (base, text, hole); `scad/shapes/<id>/` – shape plugins (`shape.json` + `shape.scad`, see `backend/nametag/shapes.py`)
- `slicer/profiles/` – flat PrusaSlicer profiles (`tools/make_profile.py`): Core One 0.4 (0.20 mm BALANCED) and 0.25 (0.15 mm SPEED), Prusament PLA, plain G-code
- `config/print.json` – print setups (profile, scale, base/text height, hole, min text size); `active` is used by default, tools take `--setup`
- `backend/nametag/` – pipeline: names → layout/render (OpenSCAD) → plate packing → slicing + M600

## Tools
```
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
backend/.venv/bin/python -m pytest -q backend/tests
python3 tools/check_shapes.py sheet.png           # contact sheet of all shapes/fonts
python3 tools/make_plate.py -o out/ EMMA:baloo:stadium OMA:titan:tree
python3 tools/make_plate.py -o out/ --all-shapes EMMA
```
Needs `openscad`, `prusa-slicer`, `rsvg-convert` (contact sheet only).

## New shape
Copy a folder in `scad/shapes/`, keep the folder name = `id` in `shape.json`,
define `module outline(tw, th)` and `function hole_pos(tw, th)` in `shape.scad`,
run `tools/check_shapes.py` and look at the sheet. Restart the backend.
