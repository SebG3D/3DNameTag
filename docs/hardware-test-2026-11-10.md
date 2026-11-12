# Hardware test 2026-11-10 – Core One+ (Gen 2), PrusaLink, PETG

First real prints from the booth pipeline. Printer: Prusa Core One+ (Gen 2) on the
home LAN, firmware 7.0.0, PrusaLink 2.1.2, **0.25 nozzle** (from the hero figure
project), Prusament PETG, USB stick in the printer.

## PrusaLink client (`booth/printer.py`)
- Auth: HTTP digest, user `maker` + password from the printer's network menu → works.
  Wrong password → clean "Zugangsdaten falsch" status.
- `status()` / `check()` (incl. "USB ok"), upload with `PUT` + `Print-After-Upload` → work.
  Upload speed ~30 KB/s: 200 KB in 7.5 s, a 1.26 MB plate in ~40 s.
- **FINISHED does not return 409.** A job uploaded while the printer shows FINISHED
  starts immediately, on top of the previous plate. The only protection is the
  backend's staff step "Platte leer" (a printed plate stays active until then) –
  staff must only tap it when the bed is really empty.
- `ATTENTION` covers every printer dialog (calibration prompt, tool mapping, M600);
  the backend shows all of them as "color_change" (label only).

## Printer dialogs before a job
- **Calibration prompt on every job start** – printer not fully calibrated yet. To fix
  on the printer (open).
- **"Tool mapping" dialog** – appeared with the two-tool G-code (see wipe tower). Cause:
  the G-code footer lists filament for two tools (`; filament used [mm] = a, b`) and
  `nozzle_diameter = 0.25,0.25`. Fixed in `slicer.single_tool_metadata()` (footer
  merged to one tool) – verified: dialog gone on the next plate.

## Colour change
PrusaSlicer builds a wipe tower only for a tool change, not for a single-extruder
M600 (tested). So the profiles are set up as **two tools on one nozzle**
(`tools/make_profile.py` OVERRIDES): base on tool 1, text on tool 2 (3MF layer range),
`toolchange_gcode` = M600. `slicer.finish_gcode()` strips the `T0`/`T1` lines and checks
there is exactly one M600, in the first layer above the base.
- SEMM mode ("single extruder multi material") was rejected: it adds MMU unload/load
  moves (~45 mm retract and re-push) around the M600.
- PrusaSlicer 2.9 ignores `wipe_tower_x/y` from the config; the tower position goes into
  the 3MF (`Metadata/Prusa_Slicer_wipe_tower_information.xml`).

Two modes per setup (`config/print.json`, `"color_change"`):
- **`tower`** (default): small tower (12 mm wide, 15 mm³ purge, ~16 × 14 mm with brim)
  in the back-right corner (X220 Y190); plate packing keeps that corner free,
  `slicer.check_tower()` checks the real tower against it. **Printed, works.**
- **`wiper`** (setup `nozzle025petg_b3w`): no tower, colour change at the Core One+
  nozzle wiper – **not yet printed, test planned for 2026-11-11.** See below.

Observation (user): the main problem with a colour change is filament flowing out
of the nozzle until printing resumes – a tower gives a defined path to use it up.
Wiping alone only solves half of it; the wiper sequence therefore purges, retracts
and wipes right before going back to the part.

## Core One+ (Gen 2) nozzle wiper
From the firmware source (Prusa-Firmware-Buddy v7.0.0,
`src/feature/nozzle_cleaner_lite/nozzle_cleaner_lite.cpp`, `src/marlin_stubs/G12.cpp`):
- Enabled in *Settings → Hardware → Nozzle Wiper*; firmware G-code `G12`
  (`S` = cleaning temperature, `C0` = no cool-down on the touchpoint).
- Touchpoint (Z reference) at **X206.5 Y-15**; pad along X from **196.5 to 166.5**,
  used band Y -16.5 … -13.5. G12 probes the touchpoint with the load cell, wipes
  0.3 mm below it (pad top is 0.2 mm above the touchpoint), 5 fast + 2 slow
  zigzag strokes – thorough but slow for a mid-print colour change.
- **Measured** (G12 at 170 °C, Z polled over PrusaLink, `out/wiper_test/`):
  touchpoint at **Z -0.3** → wipe height **Z -0.6** (with the current sheet; Z 0 is the
  sheet surface, so another sheet can shift it → `wiper_z` in `print.json`).
- Core One `Z_MIN_POS` = 0 with software endstops → the wipe pass needs `M211 S0` /
  `M211 S1` around it (M211 is in the firmware).
- Excess filament can fall down in front of the bed, left of the wiper.

Wiper colour change (`slicer.WIPER_TOOLCHANGE`): lift Z+3 → X110 Y-15 (front middle)
→ `M600 X110 Y-15` (unload + swap there; the firmware then loads + purges at its fixed
load position X202 Y-13 and returns) → `M211 S0`
→ Z `wiper_z` → purge 24 mm → fast retract 1.5 mm @ 60 mm/s → one pass X110→X195 at pad height (shears the
purge off at the pad edge) (stops 10 mm before the touchpoint) → lift → `M211 S1` → undo the
retract (the slicer retracts/deretracts again around the travel back).
Risk for the first run: mid-print the mesh bed levelling is active and extrapolates
a small correction to Y-15 → watch the first pass, adjust `wiper_z` if needed.

### Wiper run 2026-11-11 (5 tags, `nozzle025petg_b3w`, cold bed)
- 40.1 min total, of which 15.2 min waiting at the M600 → **~27 min with a 2.3 min swap**
  (tower version: 34.7 min). Prep 8.1 min (bed from 17 °C), base 13.1 min, wipe + text
  ~2.5 min, end G-code ~1.2 min.
- Wipe pass at `wiper_z` -0.6 touched the pad fine; text crisp; tags stuck.
- Issues: 6 mm purge too little (filament still hung on the nozzle); purge at X160 landed
  next to the pad and stuck to the nozzle. Fix: purge position moved to X110 Y-15, purge
  4× (24 mm).
- 1-tag check (EMMA, warm bed): 11.8 min (prep 5.3, base 2.4, swap 2.3, purge+wipe+text
  ~1.0, end 1.2). Purge + wipe worked, but the firmware's own M600 load purge still
  landed on the pad (it purges at the M600 park position, not at our X110). Fix: park via
  `M600 X110 Y-15`, our purge moved to X146 at `wiper_z` so the pass shears it off.
- 2nd 1-tag check: 12.1 min. M600 park position works (firmware purge went to X110);
  purge at pad height + shear worked, no contact at Z -0.6 at X146. Changed: park at
  X146 too (all purge in one spot), retract after our purge 0.8 → 1.5 mm at 60 mm/s
  (the old one wasn't visible).
- 3rd 1-tag check (park X146): firmware purge seemed to land on the pad again. Firmware
  7.0.0 source (non-INDX Core One): M600 default park = X202 Y-13 (`X_MAX_POS-50`,
  `Y_MIN_POS+6`, over the pad), park Z 60, load purge happens at the park position
  (waste-bin purge only on INDX/iX). X146 is likely too close given the 6 cm fall →
  both purges moved to X110, move into the pad at `wiper_z` from there.
- 4th 1-tag check (park X110): unload + swap at X110 as intended, but after inserting the
  filament the head moved to X202 Y-13 and purged there. Firmware 7.0.0
  `Pause::await_filament_process` always parks at `ParkPosition::load` (= X202 Y-13 on the
  Core One) before loading; not configurable. Every firmware load (M600, M701, autoload)
  purges there. **Decision: accept it** (option 1). The blob lands just right of the pad,
  outside our pass (X110→X195); leftover purge is handled by hand, no staff step.
  Result: the strand was dragged off and fell down in front of the bed. A custom unload/M601/manual-load sequence was rejected as too fragile
  (autoload, filament sensor) for the booth.

## Timing (5 tags: EMMA, OMA, LEON, MAXIMILIAN, SOPHIE)
| | 1 tag, 7 base layers | 5 tags, 7 base layers, cold bed | **5 tags, 3 base layers, warm bed** |
|---|---|---|---|
| Slicer estimate | 5 min | 40 min | 24 min |
| Dialogs | – | 5.5 min | 20 s |
| Heat-up, homing, MBL, nozzle to 250 °C | ~10 min | ~9 min (bed 22→85 °C ~4 min) | ~7.4 min |
| Base | | ~37 min | ~21 min |
| M600 incl. swap | ~4 min | 2.7 min | 2.3 min |
| Tower + text | ~1.5 min | ~4 min | ~3.8 min |
| **Total** | 17.5 min | ~53 min after dialogs | **34.7 min** |

- The base dominates: on the 0.25 nozzle every base layer is a full solid fill
  (~4 min per layer for 5 tags). Fewer/thicker layers help little on 0.25; the nozzle
  is the real lever. Slicer comparison of the same plate:
  0.25 / 0.15 mm / base 1.1 = 40 min, 0.25 / 0.20 mm / base 1.2 = 37 min,
  0.25 / 0.20 mm / base 1.0 = 33 min, **0.4 / 0.20 mm / base 1.0 = 15 min**.
- Keeping the bed hot between plates (`M140 S0` removed from the end G-code, all
  profiles) saved only ~1.5 min; the remaining ~7 min prep is mostly MBL and the
  nozzle waiting at 150/170 °C in Prusa's start G-code.
- Slicer estimate vs real: 3.5× for a single tag (fixed prep), ~1.3–1.4× for a 5-tag
  plate. `service._learn_time()` ignores factors > 3, so single-tag plates teach it nothing.

## Print quality
- 7 base layers (1.1 mm), first plate: some tags came loose and printed badly; EMMA
  printed best. Cause: dirty sheet → cleaning fixed it (or another build surface).
- **3 base layers (0.5 mm, setup `nozzle025petg_b3`): tags crisp and nice**, stuck fine
  on the cleaned sheet. Slight stringing → maybe lower PETG temperature (250 °C now),
  filament dependent → should become a per-setup setting.
- Wipe tower worked.

## Setups added (`config/print.json`)
| Setup | Profile | Base | Colour change |
|---|---|---|---|
| `nozzle025petg` | `coreone_025_petg.ini` (Prusament PETG, 250/85 °C) | 1.1 mm | tower |
| `nozzle025petg_b3` | same | 0.5 mm (3 layers) | tower |
| `nozzle025petg_b3w` | same | 0.5 mm (3 layers) | wiper |
`active` is still `nozzle040s` (PLA, 0.4).

## Nozzle decision and capacity (2026-11-11)
- 0.4 test plate (`nozzle040petg_w`, same 5 names, base 0.6 mm): 22.1 min with a cold bed
  (prep ~8.5, base ~5.5, swap wait 5.2, text + end ~2). **Text not nice enough → booth
  stays on the 0.25.** The 0.4 setup and `coreone_040_petg.ini` stay as a fallback only.
- Time model: real ≈ fixed prep (`plate.prep_min`, 6.5 min: heat-up, MBL, end G-code)
  + slicer estimate × `real_factor` + wait at the colour change. The forecast adds the prep;
  `real_factor` now learns from printing time only (prep and colour-change wait removed).
- Day simulation (6 h open, queue limit 30, realistic mix of names/shapes), 0.25 nozzle:
  | | scale 0.75 | **scale 0.6** | 0.4 nozzle, scale 0.75 |
  |---|---|---|---|
  | 70 kids: turned away / tags | 20 / 71 | **14 / 81** | 8 / 95 |
  | median wait | ~2 h 55 | **~2 h 05** | ~1 h 35 |
  | 150 kids: tags | 75 | **91** | 106 |
  Queue limit 15 at scale 0.6 printed fewer tags (69, emptier plates) and still ~1 h 40
  wait → keep 30.
- Booth setup `nozzle025petg_b3w` now at **scale 0.6** (20 % smaller; stadium ~32 × 12 mm,
  6 mm text). Some long names no longer fit bell / Pacifico (kiosk offers other shapes).
- New shape **wave** ("Welle"): band with a sine edge (amp 2.2, period 34 design units).

## 2026-11-12: long names at scale 0.6, one text layer

- Printer menu still had nozzle 0.40 after the swap → set to 0.25 (PrusaLink `/api/v1/info`
  `nozzle_diameter` shows it; the G-code checks `M862.1 P0.25`).
- Plate `wave_long` (8 wave tags, worst-case long names, text 4.6–6.0 mm): base up to the
  M600 29.5 min, swap 12.5 min. Stopped after the 1st text layer because of a **layer shift
  on the 2nd text layer**; one text layer is enough → `text_h` 0.3 → **0.15** (est. 33 → 29 min).
- Look: baloo, fredoka 4.9 mm, pacifico 4.6–4.7 mm, titan 5.2 mm nice. Titan 4.7 mm too fat;
  WWWW/MMMM in chewy/bangers letters too close.
- Fixes: `fonts.json` per font `min_text_add` (titan +0.6 → min 5.1 mm) and `spacing`
  (chewy, bangers 1.1, OpenSCAD `text(spacing=)`, used for measuring, preview and print);
  Z-hop `retract_lift` 0.15 → **0.4** in all profiles (`make_profile.py` OVERRIDES).
- Plate `spacing_test` (5 tags): 22.8 min to the M600, swap 6.5 min, text 3.5 min,
  **33 min** total. Spacing, titan and text all nice, no shift.

- Purge spot X110 → **X140** (26.5 mm before the pad) and text at **240 °C** (setup
  `text_temp_delta` −10: `M104` before the M600 so the firmware loads with it, `M109` after):
  purge wiped off cleanly, text sticks. Plate `purge140_test` (5 tags, cold bed): prep 7.3 min,
  base 11.8, swap 2.5, text 2.7 → **24 min**.
- **Skipping MBL on successive plates rejected:** without probing the nozzle crashed into
  the bed (only Z homing at the sheet edge, mesh from the previous plate not applied). It would
  only have saved ~1.5–2 min (prep 5 min vs 6.5–7.4).

## Open
1. Shorter prep between booth plates: MBL stays; little else left to gain.
2. `config/booth.json` still points at the booth address `192.168.10.2`; set the
   printer password there (not in git) for the booth.
