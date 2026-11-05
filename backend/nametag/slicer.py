"""Plate slicing with PrusaSlicer CLI + M600 colour change at the text layer."""
import re
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .setup import PrintSetup

PRUSA_SLICER = os.environ.get("PRUSA_SLICER") or shutil.which("prusa-slicer") or "prusa-slicer"
COLOR_CHANGE = "M600 ; booth: text colour\nG1 E0.3 F1500 ; prime after colour change\n"


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


def insert_color_change(gcode: str, base_h: float) -> tuple[str, float]:
    """Insert COLOR_CHANGE in the first layer above the base, after the travel
    to that layer and before ;AFTER_LAYER_CHANGE (where PrusaSlicer itself puts
    colour changes). Layer header: ;LAYER_CHANGE / ;Z: / ;HEIGHT:."""
    pat = re.compile(r"^;LAYER_CHANGE\n;Z:([\d.]+)\n", re.M)
    for m in pat.finditer(gcode):
        z = float(m[1])
        if z > base_h + 1e-3:
            at = gcode.find(";AFTER_LAYER_CHANGE\n", m.end())
            nxt = gcode.find(";LAYER_CHANGE\n", m.end())
            if at < 0 or (0 <= nxt < at):
                raise SliceError(f"no ;AFTER_LAYER_CHANGE in layer Z={z}")
            return gcode[:at] + COLOR_CHANGE + gcode[at:], z
    raise SliceError(f"no layer above base_h={base_h}")


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
    cmd = [PRUSA_SLICER, "--load", str(profile), "--dont-arrange", "--export-gcode", "-o", str(raw), *map(str, models)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0 or not raw.exists():
        raise SliceError(f"prusa-slicer failed ({r.returncode}): {(r.stderr or r.stdout).strip()[-800:]}")
    text = raw.read_text()
    raw.unlink()
    m = re.search(r"^; estimated printing time \(normal mode\) = (.+)$", text, re.M)
    if not m:
        raise SliceError("no time estimate in G-code")
    check_layers(text, setup)
    text, z = insert_color_change(text, base_h)
    out.write_text(text)
    return PlateResult(out, parse_time(m[1]), z)
