# 3DNameTagBooth

Kiosk for the Christmas booth: kids type a name, pick font, shape and text
colour; tags are printed in batches on a Prusa Core One (base colour of the
day + text colour via M600). Plan: `docs/PLAN.md`.

## Layout
- `fonts/` – six OFL/Apache fonts: `src/` upstream, `ttf/` + `woff2/` built by `tools/build_fonts.py`, list in `fonts.json`
- `scad/lib/tag.scad` – tag core (base, text, hole); `scad/shapes/<id>/` – shape plugins (`shape.json` + `shape.scad`, see `backend/nametag/shapes.py`)
- `slicer/profiles/` – flat PrusaSlicer profiles (`tools/make_profile.py`): Core One 0.4 (0.20 mm BALANCED) and 0.25 (0.15 mm SPEED), Prusament PLA, plain G-code
- `config/print.json` – print setups (profile, scale, base/text height, hole, min text size); `active` is used by default, tools take `--setup`
- `backend/nametag/` – pipeline: names → layout/render (OpenSCAD) → plate packing (3MF with text layer range) → slicing + M600
- `backend/booth/` – booth backend: `service.py` (previews, orders, payment, plate scheduler, time model), `db.py` (SQLite), `printer.py` (simulator + PrusaLink), `server.py` (FastAPI), `static/staff/` (staff page for the phone)
- `frontend/` – kiosk app (Vite + React + TS), built to `frontend/dist/`, served by the backend at `/kiosk/`
- `config/booth.json` – booth settings (colours, prices, plate size/wait, PIN, printer)

## Tools
```
python3 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
backend/.venv/bin/python -m pytest -q backend/tests
python3 tools/check_shapes.py sheet.png           # contact sheet of all shapes/fonts
python3 tools/make_plate.py -o out/ EMMA:baloo:stadium OMA:titan:tree
python3 tools/make_plate.py -o out/ --all-shapes EMMA
backend/.venv/bin/python tools/selfcheck.py      # is this machine booth-ready? (tools, render, slice, printer)
backend/.venv/bin/python tools/simulate_day.py   # a whole booth day in fast-forward: waits, ETA accuracy, capacity
backend/.venv/bin/python -m booth.fakelink       # fake Core One (PrusaLink) on :8081 for dry runs
```
Pi setup (kiosk, service, network, read-only): `deploy/pi/README.md`.
Needs `openscad`, `prusa-slicer`, `rsvg-convert` (contact sheet only).

## Backend
```
cd backend && .venv/bin/python -m booth.server --port 8080      # simulated printer by default
```
Staff page: `http://<pi>:8080/staff/` (PIN from `config/booth.json` or env `BOOTH_PIN`).
"⚙ Einstellungen" on the staff page edits `config/booth.json` and applies it live (no restart): event name,
base/text colours, prices, order/queue limits, plate size/wait, fonts/shapes on/off, kiosk idle time + sound,
printer (sim/PrusaLink, connection test), print setup (only with an empty queue), staff PIN. The kiosk
picks changes up the next time it is on its start screen. `--config <file>` / `BOOTH_CONFIG` selects another booth.json.
Kiosk API: `GET /api/config`, `GET /api/status`, `POST /api/fit`, `POST /api/preview`, `POST /api/orders`.
For the real printer set `"printer": {"type": "prusalink", "host": ..., "api_key": ...}` – a USB stick must be
in the printer (upload target), the PrusaLink client is not yet tested on hardware.

Staff page "📊 Tag": today's numbers (orders, printed, money, colours), CSV export, backups
(hourly, `data/backups/`), "Tag abschließen" at the end of the day, clock + shutdown on the Pi.

Flow: order → first tag queued, extra tags wait for "Bezahlt" → tags grouped by text colour → plate when
`plate.max_tags` are waiting, after `plate.max_wait_min`, or "Jetzt starten" → colour change: staff load the
text colour and confirm on the printer → plate done: take tags off (plate map with order numbers), load the
base colour again, tap "Platte leer" → next plate.

## Kiosk frontend
```
cd frontend && npm install
npm run build                  # -> frontend/dist, backend serves it at /kiosk/ (restart backend after the first build)
npm run dev                    # dev server on :5173, proxies /api and /fonts to the backend on :8080
```
Flow: start → name (own keyboard) → font → shape (shapes that don't fit the name are greyed out) →
text colour (real preview from the backend, rendered as SVG) → review ("+ Noch einen Anhänger", price) →
order number + ETA. Idle 90 s → "Bist du noch da?" → reset. Backend unreachable → pause screen with auto-retry.
5 taps in the top-left corner within 3 s open the staff page.
Shape icons come from `GET /api/shapes/<id>/icon` (rendered once, cached in `backend/data/icons/` – delete after changing a shape).

## New shape
Copy a folder in `scad/shapes/`, keep the folder name = `id` in `shape.json`,
define `module outline(tw, th)` and `function hole_pos(tw, th)` in `shape.scad`,
run `tools/check_shapes.py` and look at the sheet. Restart the backend.
