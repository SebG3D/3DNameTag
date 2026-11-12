"""PrusaLink client + booth flow against the fake printer (booth/fakelink.py)."""
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from booth.config import load_config                       # noqa: E402
from booth.fakelink import FakePrinter, serve              # noqa: E402
from booth.printer import PrinterNotReady, PrusaLinkPrinter  # noqa: E402
from booth.service import Booth                            # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def fake():
    clock = Clock()
    f = FakePrinter(password="secret", duration_s=600, clock=clock)
    srv = serve(f)
    host = f"127.0.0.1:{srv.server_address[1]}"
    yield f, host, clock
    srv.shutdown()


def ctl(host, cmd):
    httpx.post(f"http://{host}/fake/{cmd}")


GCODE = b"G28\n" + b"G1 X1\n" * 50 + b"M600 ; booth: text colour\n" + b"G1 X2\n" * 50


def test_auth(fake, tmp_path):
    f, host, _ = fake
    assert PrusaLinkPrinter(host, password="secret").status().state == "idle"
    bad = PrusaLinkPrinter(host, password="wrong").status()
    assert bad.state == "offline" and "Zugangsdaten" in bad.message
    f.api_key = "k1"
    assert PrusaLinkPrinter(host, api_key="k1").status().state == "idle"
    st = PrusaLinkPrinter("127.0.0.1:9").status()
    assert st.state == "offline" and "nicht erreichbar" in st.message


def test_print_cycle_states(fake, tmp_path):
    f, host, clock = fake
    pr = PrusaLinkPrinter(host, password="secret")
    g = tmp_path / "plate_001.gcode"
    g.write_bytes(GCODE)
    pr.start(g, 600)
    assert f.files["plate_001.gcode"] == GCODE
    clock.advance(100)
    st = pr.status()
    assert st.state == "printing" and 10 < st.progress < 30 and st.remaining_s == 500
    clock.advance(400)
    assert pr.status().state == "attention"                     # M600 at ~half the file
    with pytest.raises(PrinterNotReady, match="409"):           # busy printer refuses a new job
        pr.start(g, 600)
    ctl(host, "resume")
    clock.advance(1000)
    assert pr.status().state == "finished"
    ctl(host, "tap")
    assert pr.status().state == "idle"


def test_check_usb_and_abort(fake, tmp_path):
    f, host, clock = fake
    pr = PrusaLinkPrinter(host, password="secret")
    assert "USB ok" in pr.check().message
    ctl(host, "no_usb/1")
    assert "USB-Stick" in pr.check().message
    g = tmp_path / "p.gcode"
    g.write_bytes(GCODE)
    with pytest.raises(PrinterNotReady, match="USB"):
        pr.start(g, 600)
    ctl(host, "no_usb/0")
    pr.start(g, 600)
    clock.advance(10)
    pr.abort()
    assert pr.status().state == "idle"                          # STOPPED maps to idle


def test_offline_mid_print(fake, tmp_path):
    f, host, clock = fake
    pr = PrusaLinkPrinter(host, password="secret", timeout=1)
    g = tmp_path / "p.gcode"
    g.write_bytes(GCODE)
    pr.start(g, 600)
    ctl(host, "offline/1")
    assert pr.status().state == "offline"
    with pytest.raises(PrinterNotReady):
        pr.start(g, 600)
    ctl(host, "offline/0")
    clock.advance(100)
    assert pr.status().state == "printing"


@pytest.fixture
def booth_fake(fake, tmp_path):
    f, host, clock = fake
    cfg = load_config(data_dir=tmp_path)
    cfg.printer = {"type": "prusalink", "host": host, "user": "maker", "password": "secret", "storage": "usb"}
    cfg.path = None                                             # never write the repo config
    booth = Booth(cfg, setup_name="nozzle040s", clock=clock)
    return booth, f, host, clock


def order(booth, *tags):
    items = []
    for name, color in tags:
        p = booth.preview(name, "baloo", "stadium")
        items.append({"preview_id": p.id, "text_color": color})
    return booth.place_order(items)


def start(booth):
    """Staff press start on the (only) waiting plate."""
    booth.staff_plate_start(booth.db.q1("SELECT id FROM plates WHERE status='waiting' ORDER BY id")["id"])
    booth.tick()


def plate(booth):
    return booth.db.plate(booth.db.q("SELECT id FROM plates ORDER BY id DESC LIMIT 1")[0]["id"])


def test_booth_full_plate_over_prusalink(booth_fake):
    booth, f, host, clock = booth_fake
    order(booth, ("EMMA", "red"))
    order(booth, ("OPA", "red"))
    start(booth)
    assert plate(booth)["status"] == "printing" and f.state == "PRINTING"
    assert any(n.startswith("plate_") for n in f.files)
    clock.advance(400)
    booth.tick()
    assert plate(booth)["status"] == "color_change"
    ctl(host, "resume")
    clock.advance(100)
    booth.tick()
    assert plate(booth)["status"] == "printing"
    clock.advance(1000)
    booth.tick()
    p = plate(booth)
    assert p["status"] == "done" and f.state == "FINISHED"
    booth.staff_plate_start(p["id"])                          # restart from FINISHED: same G-code
    booth.tick()
    assert plate(booth)["status"] == "printing" and f.state == "PRINTING"


def test_missed_finish_is_not_reprinted(booth_fake, tmp_path):
    """Backend down while the plate finishes and staff confirm on the printer:
    the plate counts as printed (no duplicate tags)."""
    booth, f, host, clock = booth_fake
    order(booth, ("EMMA", "red"))
    start(booth)
    clock.advance(400)
    booth.tick()                                               # colour change at ~50 %
    ctl(host, "resume")
    clock.advance(297)
    booth.tick()                                               # last poll sees ~99.5 %
    assert booth._progress[plate(booth)["id"]] >= 99
    clock.advance(1000)
    ctl(host, "tap")                                           # finished + confirmed, never polled
    booth2 = Booth(booth.cfg, setup_name="nozzle040s", clock=clock)   # backend restart
    clock.advance(200)
    booth2.tick()
    assert plate(booth2)["status"] == "done"


def test_abort_on_printer_fails_plate(booth_fake):
    booth, f, host, clock = booth_fake
    order(booth, ("EMMA", "red"))
    start(booth)
    clock.advance(60)
    booth.tick()
    ctl(host, "abort")                                         # someone stops it on the printer
    ctl(host, "tap")
    clock.advance(120)
    booth.tick()
    p = plate(booth)
    assert p["status"] == "failed"
    assert [t["name"] for t in p["tags"]] == ["EMMA"]          # stays on the plate for a restart


def test_upload_refused_gives_clear_reason(booth_fake):
    booth, f, host, clock = booth_fake
    ctl(host, "no_usb/1")
    order(booth, ("EMMA", "red"))
    start(booth)
    p = plate(booth)
    assert p["status"] == "failed" and "USB-Stick" in p["error"]
