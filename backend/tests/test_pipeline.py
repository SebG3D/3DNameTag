import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nametag.fonts import load_fonts                    # noqa: E402
from nametag.names import clean_name                    # noqa: E402
from nametag.plate import pack, BED, MARGIN             # noqa: E402
from nametag.render import layout                       # noqa: E402
from nametag.setup import load_setup                    # noqa: E402
from nametag.shapes import load_shapes                  # noqa: E402
from nametag.slicer import insert_color_change, parse_time, SliceError  # noqa: E402


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


GCODE = """;LAYER_CHANGE\n;Z:2.4\n;HEIGHT:0.2\nG1 Z2.4\n;AFTER_LAYER_CHANGE\nG1 X1
;LAYER_CHANGE\n;Z:2.6\n;HEIGHT:0.2\nG1 Z2.6\n;AFTER_LAYER_CHANGE\nG1 X2\n"""


def test_color_change_position():
    out, z = insert_color_change(GCODE, 2.4)
    assert z == 2.6
    assert out.count("M600") == 1
    assert out.index("G1 Z2.6") < out.index("M600") < out.index(";AFTER_LAYER_CHANGE\nG1 X2")
    with pytest.raises(SliceError):
        insert_color_change(GCODE, 3.0)


def test_pack_stays_on_bed():
    items = [(f"t{i}", 60 + i * 5, 20 + (i % 3) * 30) for i in range(12)]
    placed, rest = pack(items)
    assert placed and len(placed) + len(rest) == 12
    for p in placed:
        assert p.x >= MARGIN and p.y >= MARGIN
        assert p.x + p.w <= BED[0] - MARGIN + 1e-9 and p.y + p.h <= BED[1] - MARGIN + 1e-9
    for a in placed:            # no overlaps
        for b in placed:
            if a is not b:
                assert a.x + a.w <= b.x or b.x + b.w <= a.x or a.y + a.h <= b.y or b.y + b.h <= a.y


@pytest.mark.parametrize("setup_name", ["nozzle040", "nozzle040s", "nozzle025"])
def test_shapes_and_layout(setup_name):
    setup = load_setup(setup_name)
    fonts, shapes = load_fonts(), load_shapes()
    assert list(shapes) == ["stadium", "star", "tree", "bell"]
    for s in shapes.values():
        for name in ["A", "MAXIMILIAN", "ÄÖÜ-ß 1234AB"]:
            lay = layout(name, fonts["baloo"], s, setup)
            assert lay.fits, (s.id, name, lay.reason)
            assert 1 <= lay.k <= s.text.get("k_max", 1)
    assert layout("EMMA", fonts["baloo"], shapes["tree"], setup).rot == 90


def test_setups_on_layer_boundary():
    for name in ["nozzle040", "nozzle040s", "nozzle025"]:
        s = load_setup(name)
        assert s.profile.exists()
