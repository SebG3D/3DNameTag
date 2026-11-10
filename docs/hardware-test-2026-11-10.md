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

Wiper colour change (`slicer.WIPER_TOOLCHANGE`): lift Z+3 → X160 Y-15 (left of the
pad) → M600 → purge 6 mm (~15 mm³) → retract 0.8 → X168 → `M211 S0` → Z `wiper_z` →
one pass to X195 (stops 10 mm before the touchpoint) → lift → `M211 S1` → undo the
retract (the slicer retracts/deretracts again around the travel back).
Risk for the first run: mid-print the mesh bed levelling is active and extrapolates
a small correction to Y-15 → watch the first pass, adjust `wiper_z` if needed.

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

## Open
1. Test print with `nozzle025petg_b3w` (wiper) – watch the first wipe pass.
2. Decide the booth nozzle: 0.4 (≈2.6× faster) vs 0.25; then a 0.4 PETG profile + setup
   and set `active`.
3. Fix the calibration prompt on the printer.
4. Shorter prep between booth plates (skip/limit MBL? Prusa start G-code).
5. PETG temperature per setup (stringing).
6. `config/booth.json` still points at the booth address `192.168.10.2`; set the
   printer password there (not in git) for the booth.
