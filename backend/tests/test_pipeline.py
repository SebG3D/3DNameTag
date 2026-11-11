import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nametag.fonts import load_fonts                    # noqa: E402
from nametag.names import clean_name                    # noqa: E402
from nametag.plate import pack, BED, MARGIN, GAP, TOWER_KEEP_OUT  # noqa: E402
from nametag.render import layout                       # noqa: E402
from nametag.setup import load_setup                    # noqa: E402
from nametag.shapes import load_shapes                  # noqa: E402
from nametag.slicer import check_tower, finish_gcode, parse_time, SliceError  # noqa: E402


def test_clean_name():
    assert clean_name("  emma  ") == "EMMA"
    assert clean_name("straße") == "STRAßE"
    assert clean_name("jan  - ole") == "JAN - OLE"
    for bad in ["", "   ", "A" * 13, "EMMA!", 'A"B', "Ž"]:
        with pytest.raises(ValueError):
            clean_name(bad)


def test_parse_time():
    assert parse_time("11m 10s") == 670
    assert parse_time("1h 2m 3s") == 3723
    assert parse_time("1d 0h 0m 1s") == 86401


GCODE = """T0
;LAYER_CHANGE\n;Z:2.4\n;HEIGHT:0.2\nG1 Z2.4\n;AFTER_LAYER_CHANGE\nG1 X1
;LAYER_CHANGE\n;Z:2.6\n;HEIGHT:0.2\nG1 Z2.6\n;AFTER_LAYER_CHANGE\n;TYPE:Wipe tower\nM600 ; booth: text colour\nT1\nG1 X2\n"""


def test_finish_gcode():
    out, z = finish_gcode(GCODE, 2.4)
    assert z == 2.6
    assert "T0" not in out and "T1" not in out
    assert out.count("M600") == 1
    meta = finish_gcode(GCODE + "; filament used [mm] = 2395.46, 76.95\n; nozzle_diameter = 0.25,0.25\n", 2.4)[0]
    assert "; filament used [mm] = 2472.41" in meta and "; nozzle_diameter = 0.25\n" in meta
    with pytest.raises(SliceError):                 # colour change not right above the base
        finish_gcode(GCODE, 2.2)
    with pytest.raises(SliceError):                 # no colour change at all
        finish_gcode(GCODE.replace("M600 ; booth: text colour\n", ""), 2.4)


def test_check_tower():
    x0, y0 = TOWER_KEEP_OUT[0] + 2, TOWER_KEEP_OUT[1] + 2
    ok = f";TYPE:Wipe tower\nG1 X{x0} Y{y0} E1\nG1 X{x0 + 10} E1\n;TYPE:Perimeter\nG1 X5 Y5 E1\n"
    check_tower(ok)
    with pytest.raises(SliceError):
        check_tower(ok.replace(f"X{x0 + 10}", "X100"))
    with pytest.raises(SliceError):
        check_tower(";TYPE:Perimeter\nG1 X5 Y5 E1\n")


def test_pack_stays_on_bed():
    items = [(f"t{i}", 60 + i * 5, 20 + (i % 3) * 30) for i in range(12)]
    placed, rest = pack(items)
    assert placed and len(placed) + len(rest) == 12
    for p in placed:
        assert p.x >= MARGIN and p.y >= MARGIN
        assert p.x + p.w <= BED[0] - MARGIN + 1e-9 and p.y + p.h <= BED[1] - MARGIN + 1e-9
    kx0, ky0, kx1, ky1 = TOWER_KEEP_OUT
    for p in placed:            # wipe tower corner stays free (plus gap)
        assert (p.x + p.w + GAP <= kx0 + 1e-9 or p.x >= kx1 + GAP - 1e-9
                or p.y + p.h + GAP <= ky0 + 1e-9 or p.y >= ky1 + GAP - 1e-9), p
    for a in placed:            # no overlaps
        for b in placed:
            if a is not b:
                assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


@pytest.mark.parametrize("setup_name", ["nozzle040", "nozzle040s", "nozzle025"])
def test_shapes_and_layout(setup_name):
    setup = load_setup(setup_name)
    fonts, shapes = load_fonts(), load_shapes()
    assert list(shapes) == ["stadium", "wave", "star", "tree", "bell"]
    for s in shapes.values():
        for name in ["A", "MAXIMILIAN", "ÄÖÜ-ß 1234AB"]:
            lay = layout(name, fonts["baloo"], s, setup)
            assert lay.fits, (s.id, name, lay.reason)
            assert 1 <= lay.k <= s.text.get("k_max", 1)
    assert layout("EMMA", fonts["baloo"], shapes["tree"], setup).rot == 90


def test_pack_fills_around_tower():
    """Small tags still use the shelf next to the tower."""
    placed, rest = pack([(f"t{i}", 40, 15) for i in range(60)])
    assert not rest or len(placed) >= 40
    assert any(p.y + p.h > TOWER_KEEP_OUT[1] for p in placed)


def test_setups_on_layer_boundary():
    for name in ["nozzle040", "nozzle040s", "nozzle025", "nozzle025petg"]:
        s = load_setup(name)
        assert s.profile.exists()


@pytest.mark.parametrize("setup_name", ["nozzle040s", "nozzle025petg", "nozzle025petg_b3w"])
def test_plate_text_layers(tmp_path, setup_name):
    """Full pipeline: base on tool 1, text on tool 2 in text_layer_h layers,
    M600 at the wipe tower between, no T lines left."""
    from nametag.plate import build_plate
    from nametag.render import render_tag
    from nametag.slicer import slice_plate
    setup = load_setup(setup_name)
    fonts, shapes = load_fonts(), load_shapes()
    r = render_tag("EMMA", fonts["baloo"], shapes["stadium"], setup, tmp_path, "t")
    build_plate({"t": r["files"]["tag"]}, tmp_path / "plate.3mf", setup)
    res = slice_plate([tmp_path / "plate.3mf"], tmp_path / "plate.gcode", setup)
    assert res.color_change_z == pytest.approx(setup.base_h + setup.text_layer_h)
    lines = res.gcode.read_text().splitlines()
    m600 = [ln for ln in lines if ln.startswith("M600")]
    assert m600 == ["M600 X110 Y-15 ; booth: text colour" if setup.color_change == "wiper" else "M600 ; booth: text colour"]
    assert not [ln for ln in lines if ln.strip() in ("T0", "T1")]
    i = lines.index(m600[0])
    if setup.color_change == "tower":
        assert ";TYPE:Wipe tower" in lines[i - 30:i]            # colour change happens at the tower
    else:
        assert not [ln for ln in lines if ln == ";TYPE:Wipe tower"]
        end = next(j for j in range(i, len(lines)) if lines[j].startswith("G1 E1.5 F2700 ; undo our retract"))
        block = lines[i - 3:end + 1]
        assert any(ln.startswith("G1 X110 Y-15 F12000") for ln in block)
        assert any(ln.startswith("G1 E24 F200") for ln in block)
        assert any(ln.startswith(f"G1 Z{setup.wiper_z:g}") for ln in block)
        at = [next(k for k, ln in enumerate(block) if ln.startswith(c)) for c in ("M211 S0", f"G1 Z{setup.wiper_z:g}", "M211 S1")]
        assert at == sorted(at)                                 # endstops off only around the dip
        # extrusion inside the block is purge only: retract and its undo cancel out
        e = [float(m[1]) for ln in block if (m := re.match(r"G1 E(-?[\d.]+)", ln))]
        assert sum(e) == pytest.approx(24.0)
    assert not [ln for ln in lines if re.match(r"; (filament used \[\w+\]|nozzle_diameter) = .*,", ln)]  # one tool
