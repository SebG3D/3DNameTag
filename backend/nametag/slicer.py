"""Plate slicing with PrusaSlicer CLI. The text is on tool 2, so PrusaSlicer
itself emits the colour change (toolchange_gcode = M600) at a wipe tower; here
we strip the T0/T1 lines (single-tool printer) and check the result."""
import re
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .plate import TOWER_KEEP_OUT
from .setup import PrintSetup

PRUSA_SLICER = os.environ.get("PRUSA_SLICER") or shutil.which("prusa-slicer") or "prusa-slicer"
COLOR_CHANGE = "M600 ; booth: text colour"
COLOR_CHANGE_RE = r"^M600(?: [^;\n]*?)? ; booth: text colour$"   # wiper variant carries a park position

# Colour change on the Core One+ (Gen 2) nozzle wiper instead of a wipe tower.
# Positions from the firmware (nozzle_cleaner_lite.cpp, v7.0.0): touchpoint
# X206.5 Y-15, pad along X from 196.5 to 166.5 around Y-15. M600 X/Y only sets
# where the head waits for unload + swap (front middle, X110). Once new filament is
# inserted, firmware 7.0.0 always moves to its load position X202 Y-13 (just right
# of the pad) and loads + purges there - hard-coded (pause.cpp await_filament_process,
# ParkPosition::load), no parameter. Afterwards it returns to X110, where we purge
# again at pad height (drags the firmware strand along), fast retract, and one pass into the pad
# (shears the purge off at its edge, stops 10 mm short of the touchpoint), lift.
# Purge and pass dip below Z=0, so the software endstops are off (M211). wiper_z depends on the
# sheet (Z=0 is the sheet surface): measured -0.3 touchpoint -> -0.6 wipe.
WIPER_TOOLCHANGE = (
    "{{if previous_extruder >= 0}}\n"
    "; booth: colour change at the nozzle wiper\n"
    "G1 Z{{layer_z + 3}} F720 ; lift off the tags\n"
    "G1 X110 Y-15 F12000 ; purge spot, front middle, well left of the wiper pad\n"
    "; swap here; the firmware still loads + purges at its own load position X202 Y-13\n"
    "M600 X110 Y-15" + COLOR_CHANGE[4:] + "\n"
    "M211 S0 ; purge and pass dip below Z=0\n"
    "G1 Z{wiper_z} F720 ; down to pad height (firmware has returned to the purge spot)\n"
    "G1 E24 F200 ; purge (hangs in front of the bed)\n"
    "G1 E-1.5 F3600 ; fast retract right after the purge: helps shear it off\n"
    "G1 X195 F8000 ; into the pad: shears the purge off at its edge, one pass\n"
    "G1 Z{{layer_z + 3}} F720 ; up\n"
    "M211 S1\n"
    "G1 E1.5 F2700 ; undo our retract: the slicer retracts/deretracts again around the travel\n"
    "{{endif}}"
)


class SliceError(RuntimeError):
    pass


@dataclass
class PlateResult:
    gcode: Path
    estimated_s: int
    color_change_z: float


def parse_time(text: str) -> int:
    """'1h 2m 3s' / '11m 10s' / '2d 1h 3m 4s' -> seconds."""
    units = {"d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * units[u] for n, u in re.findall(r"(\d+)([dhms])", text))


def single_tool_metadata(gcode: str) -> str:
    """The firmware reads the G-code footer and shows a 'tool mapping' dialog
    when it sees filament for two tools. Merge the per-tool values into one
    tool: sum the filament amounts, single nozzle_diameter."""
    def summed(m):
        vals = [float(v) for v in m[2].split(",")]
        return f"; filament used [{m[1]}] = {sum(vals):.2f}"
    gcode = re.sub(r"^; filament used \[(mm|cm3|g)\] = ([\d., ]+)$", summed, gcode, flags=re.M)
    return re.sub(r"^; nozzle_diameter = ([\d.]+)(?:,[\d.]+)+$", r"; nozzle_diameter = \1", gcode, flags=re.M)


def finish_gcode(gcode: str, base_h: float) -> tuple[str, float]:
    """Strip the tool-select lines (T0/T1: the Core One has one tool) and check
    there is exactly one colour change, in the first layer above the base.
    Returns (gcode, Z of that layer)."""
    gcode = re.sub(r"^T\d+[ \t]*(;.*)?\n", "", gcode, flags=re.M)
    gcode = single_tool_metadata(gcode)
    hits = [m.start() for m in re.finditer(COLOR_CHANGE_RE, gcode, re.M)]
    if len(hits) != 1:
        raise SliceError(f"expected one colour change, found {len(hits)}")
    zs = re.findall(r"^;LAYER_CHANGE\n;Z:([\d.]+)$", gcode[:hits[0]], re.M)
    z = float(zs[-1]) if zs else 0.0
    want = min((float(v) for v in re.findall(r"^;LAYER_CHANGE\n;Z:([\d.]+)$", gcode, re.M)
                if float(v) > base_h + 1e-3), default=None)
    if want is None or abs(z - want) > 1e-3:
        raise SliceError(f"colour change at Z={z}, expected first layer above base ({want})")
    return gcode, z


def check_tower(gcode: str, keep_out=TOWER_KEEP_OUT) -> None:
    """The wipe tower (incl. brim) must stay inside the area packing keeps free."""
    xs, ys, tower = [], [], False
    for line in gcode.splitlines():
        if line.startswith(";TYPE:"):
            tower = line == ";TYPE:Wipe tower"
        elif tower and line.startswith("G1 ") and " E" in line:
            if m := re.search(r" X([-\d.]+)", line):
                xs.append(float(m[1]))
            if m := re.search(r" Y([-\d.]+)", line):
                ys.append(float(m[1]))
    if not xs or not ys:
        raise SliceError("no wipe tower in G-code")
    box = (min(xs), min(ys), max(xs), max(ys))
    if box[0] < keep_out[0] or box[1] < keep_out[1] or box[2] > keep_out[2] or box[3] > keep_out[3]:
        raise SliceError(f"wipe tower {tuple(round(v, 1) for v in box)} outside keep-out {keep_out}")


def check_layers(gcode: str, setup: PrintSetup) -> None:
    """The sliced layers must match the setup: base on base_h, then exactly
    text_layers layers of text_layer_h (catches a lost 3MF layer range)."""
    zs = [float(z) for z in re.findall(r"^;LAYER_CHANGE\n;Z:([\d.]+)$", gcode, re.M)]
    if not any(abs(z - setup.base_h) < 1e-3 for z in zs):
        raise SliceError(f"no layer ends at base_h={setup.base_h}: {zs[:12]}")
    text = [z for z in zs if z > setup.base_h + 1e-3]
    want = [round(setup.base_h + (i + 1) * setup.text_layer_h, 4) for i in range(setup.text_layers)]
    if [round(z, 4) for z in text] != want:
        raise SliceError(f"text layers {text} != expected {want}")


def slice_plate(models: list[Path], out: Path, setup: PrintSetup) -> PlateResult:
    """Slice with the setup's profile (plate 3MF from nametag.plate)."""
    if not models:
        raise SliceError("empty plate")
    profile, base_h = setup.profile, setup.base_h
    raw = out.with_suffix(".raw.gcode")
    cmd = [PRUSA_SLICER, "--load", str(profile)]
    if setup.color_change == "wiper":
        extra = out.with_suffix(".wiper.ini")
        extra.write_text("wipe_tower = 0\n"
                         "toolchange_gcode = " + WIPER_TOOLCHANGE.format(wiper_z=f"{setup.wiper_z:g}").replace("\n", "\\n") + "\n")
        cmd += ["--load", str(extra)]
    cmd += ["--dont-arrange", "--export-gcode", "-o", str(raw), *map(str, models)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not raw.exists():
        raise SliceError(f"prusa-slicer failed ({r.returncode}): {(r.stderr or r.stdout).strip()[-800:]}")
    text = raw.read_text()
    raw.unlink()
    m = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", text, re.M)
    if not m:
        raise SliceError("no time estimate in G-code")
    check_layers(text, setup)
    if setup.color_change == "tower":
        check_tower(text)
    text, z = finish_gcode(text, base_h)
    out.write_text(text)
    return PlateResult(out, parse_time(m[1]), z)
