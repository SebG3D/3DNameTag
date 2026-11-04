# 3DNameTagBooth – Plan

Christmas booth: kids type a name on a touch kiosk (own Pi 5), tags are printed
on a Prusa Core One in two colours (base colour of the day + text colour via M600).
Booth date: ~2026-11-18 → keep v1 basic, foundation solid and modular.

UI details: `frontend-spezifikation.md` (this plan overrides it where they differ),
clickable mock: `kiosk-preview.jsx`.

## Decisions (2026-11-04)

| Topic | Decision |
|---|---|
| Hardware | Separate Pi 5 + touchscreen, not shared with the star booth |
| Printing | Several tags per plate ("Druckrunde"); one text colour per plate |
| Orders | An order = 1..N tags; names may differ (tags for relatives). First tag free, further tags paid |
| Shapes | Tag (stadium), star, Christmas tree, bell; bone removed. Shapes are plugins (one folder each) |
| Printer link | LAN/PrusaLink (Pi ↔ printer, direct cable possible); USB stick as fallback |
| Preview v1 | 2D SVG (as in the mock); Three.js preview postponed |

## Architecture

```
Kiosk (Chromium, React)  ──HTTP──►  FastAPI backend on Pi  ──PrusaLink HTTP──►  Core One
Staff phone (/admin)     ──HTTP──►     │
                                       ├─ shapes/   (plugin dir, scanned at start)
                                       ├─ fonts/    (TTF for OpenSCAD + woff2 for UI)
                                       ├─ OpenSCAD  (tag → STL)
                                       ├─ PrusaSlicer CLI (plate → G-code, time estimate)
                                       └─ SQLite    (orders, tags, plates)
```

Modules (backend): `shapes` (registry), `render` (OpenSCAD), `slicer` (plate
→ G-code + M600), `queue` (orders/plates), `printer` (PrusaLink client behind an
interface, so a USB-stick/manual "printer" and a simulator fit the same slot).

## Shape plugins

```
shapes/
  stadium/  shape.json  shape.scad  [icon.svg]
  star/     ...
  tree/     ...
  bell/     ...
```

- `shape.json`: id, label DE/EN, order, text box mode (`grow` = outline grows
  with the name, `fit` = fixed outline, text scaled into a box), max text box,
  hole position.
- `shape.scad`: exactly one module `outline(text_w, text_h)` returning the 2D outline.
- Common `lib/tag.scad` does the rest: base extrude (same thickness for every shape,
  so M600 is at the same layer for all tags on a plate), raised text, keyring hole,
  min-wall checks via `assert`.
- OpenSCAD can't `include` a path from a variable → the backend writes a tiny
  wrapper per render (`use <shapes/star/shape.scad>; include <lib/tag.scad>; ...`).
- Text size is measured in Python with fontTools from the same TTF and passed via
  `-D` (OpenSCAD 2021.01 has no `textmetrics`).
- Drop a new folder in → appears after backend restart (icon rendered from the
  outline if `icon.svg` is missing). A validation script renders each shape with
  short/long test names.

## Order and plate flow

1. Kid builds tag 1 (name, font, shape, text colour) → "Noch einen Anhänger?" →
   more tags (max per order in config). Summary shows: 1 free + n × price.
2. Free-only order → queued at once. Order with paid tags → status
   "awaiting payment"; staff taps "paid" on the phone (or deletes the extra tags).
3. Queue groups tags by text colour into plates (max tags per plate from config,
   e.g. 6). A plate is started when it is full, or by staff ("start now"), or
   after a max-wait time.
4. Plate start: arrange STLs → slice → insert M600 at first text layer → upload
   + start via PrusaLink. Staff page: "Plate 3: load WHITE at colour change".
5. Plate done → staff page lists tags by order number for pickup sorting →
   "bed cleared" → next plate.
6. Kiosk shows order number + rough ETA (plate-based estimate).

## Status (2026-11-04)
- P1 done: fonts, shape plugins (tag/star/tree/bell, tree+bell text vertical), setups per nozzle
  (active `nozzle040s`: scale 0.75, base 1.0 mm in 0.2 layers, text 2 x 0.15 mm), own plate packing, 3MF
  layer range, M600 insert. Test prints pending.
- P2 done (sim only): backend, staff page, simulated printer; PrusaLink client written, untested.
- P3 done (v1): kiosk frontend in `frontend/` (2D SVG preview from backend paths, multi-tag orders, idle
  guard, offline screen, staff corner). Tested headless against the sim backend; not yet on the Pi touchscreen.
- After a plate the printer holds the text colour: staff reload the base colour before the next plate.

## Phases

**P1 – Print pipeline (desktop + real prints), first priority**
- Fonts into repo (6 OFL fonts, TTF + woff2).
- `lib/tag.scad` + 4 shape plugins + validation script.
- Core One profile exported from PrusaSlicer GUI into repo (`slicer/coreone.ini`).
- `slicer` module: multi-STL arrange, M600 insert, read estimated time.
- Test prints: min text size per font, plate time for 4/6/8 tags, release from
  sheet, colour change. → fix base/text heights and plate size.

**P2 – Backend**: config.json, shape registry, SQLite queue (orders, tags,
plates, payment), API from the spec (+ orders/plates), PrusaLink client +
simulator, staff page (phone).

**P3 – Kiosk frontend**: Vite/React from the mock, shapes/colours/fonts from
`/api/config`, multi-tag order + price summary, idle timeout, offline screen,
kiosk hardening. (Needs Node on the dev machine.)

**P4 – Pi**: install script + kiosk service (adapted from Nihtlight
`TestFixture/Booth/pi`), PrusaLink network setup, full dry run with a real plate.

**Later**: Three.js 3D preview, sound, English UI, MMU/INDX (would remove M600 step).

## Open points
- Price per extra tag, max tags per order, max tags per plate.
- Pickup number format (counter per day?).
- Check on the Pi: OpenSCAD render time for text (2021.01 CGAL is slow; a newer
  build with Manifold may be needed).
- Core One PrusaLink API key / network setup at the booth.
