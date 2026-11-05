#!/usr/bin/env python3
"""Booth self-check: is this machine ready for the booth? Run after install
and on the morning of the booth (the Pi install script runs it at the end).

  backend/.venv/bin/python tools/selfcheck.py [--config /data/nametag/booth.json] [--data /data/nametag]
                                              [--no-printer] [--quick]

Checks: OpenSCAD + PrusaSlicer (version), fonts, booth.json, data dir writable,
kiosk build, a real tag render per shape and a sliced test plate (with
timings and the M600 colour change), printer connection + USB stick.
Exit code 1 if something is broken.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

OK, WARN, BAD = "\033[32m✓\033[0m", "\033[33m!\033[0m", "\033[31m✗\033[0m"
results: list[tuple[str, str, str]] = []


def report(status: str, what: str, detail: str = "") -> None:
    results.append((status, what, detail))
    print(f" {status} {what}" + (f" – {detail}" if detail else ""), flush=True)


def version(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return (r.stdout + r.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError) as e:
        return f"ERROR {e}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=os.environ.get("BOOTH_CONFIG"))
    ap.add_argument("--data", type=Path, default=os.environ.get("BOOTH_DATA"))
    ap.add_argument("--no-printer", action="store_true")
    ap.add_argument("--quick", action="store_true", help="one shape only, no slicing")
    a = ap.parse_args()

    print("Tools")
    from nametag.render import OPENSCAD
    from nametag.slicer import PRUSA_SLICER
    v = version([OPENSCAD, "--version"])
    report(OK if v.startswith("OpenSCAD") else BAD, "OpenSCAD", v)
    v = version([PRUSA_SLICER, "--help"])
    m = re.search(r"PrusaSlicer-(\d+)\.(\d+)", v)
    if not m:
        report(BAD, "PrusaSlicer", v)
    else:
        good = (int(m[1]), int(m[2])) >= (2, 9)
        report(OK if good else BAD, "PrusaSlicer", v.split(" based")[0] + ("" if good else " – need 2.9 or newer"))

    print("Config and data")
    from booth.config import CONFIG, ConfigError, load_config
    try:
        cfg = load_config(a.config or CONFIG, data_dir=a.data)
        report(OK, "booth.json", f"{cfg.path} – {len(cfg.text_colors)} text colours, base {cfg.base_color['name']}, "
                                 f"printer {cfg.printer.get('type')}")
    except (OSError, ValueError, ConfigError) as e:
        report(BAD, "booth.json", str(e))
        cfg = None
    if cfg:
        try:
            cfg.data_dir.mkdir(parents=True, exist_ok=True)
            probe = cfg.data_dir / ".selfcheck"
            probe.write_text("x")
            probe.unlink()
            free = os.statvfs(cfg.data_dir)
            gb = free.f_bavail * free.f_frsize / 1e9
            report(OK if gb > 0.5 else WARN, "data dir", f"{cfg.data_dir}, {gb:.1f} GB free")
        except OSError as e:
            report(BAD, "data dir", f"{cfg.data_dir}: {e}")
        if cfg.path and not os.access(cfg.path, os.W_OK):
            report(WARN, "booth.json writable", "no – staff settings cannot be saved")
    dist = ROOT / "frontend" / "dist" / "index.html"
    report(OK if dist.exists() else BAD, "kiosk build", str(dist.parent) if dist.exists()
           else "missing: cd frontend && npm ci && npm run build")

    print("Rendering")
    from nametag.fonts import load_fonts
    from nametag.render import render_tag
    from nametag.setup import load_setup
    from nametag.shapes import load_shapes
    try:
        fonts, shapes = load_fonts(), load_shapes()
        setup = load_setup(cfg.print_setup if cfg else None)
        report(OK, "fonts / shapes / setup", f"{len(fonts)} fonts, {len(shapes)} shapes, setup {setup.name}")
    except Exception as e:                                  # noqa: BLE001
        report(BAD, "fonts / shapes / setup", str(e))
        return summary()
    tmp = Path(tempfile.mkdtemp(prefix="selfcheck-"))
    stls = {}
    font = fonts.get("baloo") or next(iter(fonts.values()))
    for sid, shape in list(shapes.items())[:1 if a.quick else None]:
        t0 = time.perf_counter()
        try:
            r = render_tag("EMMA", font, shape, setup, tmp / sid, "tag")
            dt = time.perf_counter() - t0
            stls[sid] = r["files"]["tag"]
            report(OK if dt < 8 else WARN, f"render {sid}", f"{dt:.1f} s" + ("" if dt < 8 else " – slow, kids wait"))
        except Exception as e:                              # noqa: BLE001
            report(BAD, f"render {sid}", str(e)[-300:])
    for fid, f in fonts.items():
        if fid == font.id or a.quick:
            continue
        try:
            render_tag("ÄÖÜß", f, next(iter(shapes.values())), setup, tmp / f"font_{fid}", "tag")
        except Exception as e:                              # noqa: BLE001
            report(BAD, f"font {fid}", str(e)[-300:])
    if not a.quick:
        report(OK, "umlauts in all fonts", "ÄÖÜß rendered")

    if not a.quick and stls:
        print("Slicing")
        from nametag.plate import build_plate
        from nametag.slicer import slice_plate
        try:
            t0 = time.perf_counter()
            placed, rest = build_plate({k: Path(v) for k, v in stls.items()}, tmp / "plate.3mf", setup)
            res = slice_plate([tmp / "plate.3mf"], tmp / "plate.gcode", setup)
            dt = time.perf_counter() - t0
            text = (tmp / "plate.gcode").read_text()
            n600 = text.count("\nM600")
            report(OK if n600 == 1 else BAD, "test plate", f"{len(placed)} tags, sliced in {dt:.0f} s, "
                   f"print time {res.estimated_s // 60} min, M600 x{n600}")
        except Exception as e:                              # noqa: BLE001
            report(BAD, "test plate", str(e)[-400:])

    if cfg and not a.no_printer:
        print("Printer")
        from booth.printer import make_printer
        pr = make_printer(cfg.printer)
        st = pr.check() if hasattr(pr, "check") else pr.status()
        if pr.kind == "sim":
            report(WARN, "printer", "simulator configured (staff page › Einstellungen › Drucker)")
        else:
            bad = st.state in ("offline", "error") or "fehlt" in st.message
            report(BAD if bad else OK, "printer", f"{cfg.printer.get('host')}: {st.state} {st.message}")
    return summary()


def summary() -> int:
    bad = [r for r in results if r[0] == BAD]
    warn = [r for r in results if r[0] == WARN]
    print(f"\n{len(results) - len(bad) - len(warn)} ok, {len(warn)} warnings, {len(bad)} problems")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
