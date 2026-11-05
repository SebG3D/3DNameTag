"""Booth flow end to end with a fake clock and the simulated printer
(real OpenSCAD rendering and PrusaSlicer slicing)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from booth.config import load_config            # noqa: E402
from booth.printer import SimPrinter            # noqa: E402
from booth.service import Booth, BoothError     # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def env(tmp_path):
    clock = Clock()
    cfg = load_config(data_dir=tmp_path)
    printer = SimPrinter(speed=1.0, clock=clock)
    booth = Booth(cfg, printer=printer, setup_name="nozzle040s", clock=clock)
    return booth, printer, clock


def order(booth, *tags):
    items = []
    for name, font, shape, color in tags:
        p = booth.preview(name, font, shape)
        items.append({"preview_id": p.id, "text_color": color})
    return booth.place_order(items)


def run_until(booth, clock, cond, step=30, limit=20000):
    for _ in range(limit):
        booth.tick()
        if cond():
            return
        clock.advance(step)
    raise AssertionError("condition not reached")


def test_preview_and_fit(env):
    booth, _, _ = env
    fit = booth.fit("emma", "baloo")
    assert fit == {"stadium": True, "star": True, "tree": True, "bell": True}
    p = booth.preview("emma", "baloo", "star")
    assert p.name == "EMMA" and p.stl.exists() and p.area_mm2 > 500
    assert p.outline.startswith("M") and p.text.startswith("M")
    for bad in [("EMMA!", "baloo", "star"), ("EMMA", "nope", "star"), ("EMMA", "baloo", "bone")]:
        with pytest.raises(BoothError):
            booth.preview(*bad)


def test_order_payment_and_plate_flow(env):
    booth, printer, clock = env
    o = order(booth, ("emma", "baloo", "stadium", "white"), ("oma", "titan", "tree", "white"))
    assert o["number"] == 1 and o["needs_payment"] and o["price_cents"] == 200
    tags = booth.db.order(o["order_id"])["tags"]
    assert [t["status"] for t in tags] == ["queued", "held"]

    booth.tick()                                    # nothing ready yet (1 tag, no wait)
    assert booth.db.active_plate() is None
    clock.advance(booth.cfg.plate_max_wait_min * 60 + 1)
    booth.tick()                                    # waited long enough -> plate
    plate = booth.db.active_plate()
    assert plate and plate["status"] == "printing" and plate["text_color"] == "white"
    assert [t["name"] for t in booth.db.plate(plate["id"])["tags"]] == ["EMMA"]
    gcode = Path(plate["gcode"]).read_text()
    assert [ln for ln in gcode.splitlines() if ln.startswith("M600")]

    run_until(booth, clock, lambda: booth.db.plate(plate["id"])["status"] == "color_change")
    printer.resume()
    run_until(booth, clock, lambda: booth.db.plate(plate["id"])["status"] == "printed")
    assert booth.db.order(o["order_id"])["tags"][0]["status"] == "printed"
    booth.tick()
    assert booth.db.active_plate()["status"] == "printed"   # waits for staff

    booth.staff_paid(o["order_id"])
    assert booth.db.order(o["order_id"])["tags"][1]["status"] == "queued"
    booth.staff_plate_cleared(plate["id"])
    assert booth.db.active_plate() is None
    booth.staff_start_now("white")
    booth.tick()
    p2 = booth.db.active_plate()
    assert p2["id"] != plate["id"] and [t["name"] for t in booth.db.plate(p2["id"])["tags"]] == ["OMA"]

    ov = booth.staff_overview()
    assert ov["orders"][0]["number"] == 1 and not ov["orders"][0]["ready"]


def test_colors_grouped_full_plate_starts(env):
    booth, _, _ = env
    booth.cfg.plate_max_tags = 3
    for name in ["A", "B"]:
        order(booth, (name, "baloo", "stadium", "red"))
    order(booth, ("C", "baloo", "stadium", "white"))
    booth.tick()
    assert booth.db.active_plate() is None          # red has 2 < 3
    order(booth, ("D", "baloo", "stadium", "red"))
    booth.tick()
    p = booth.db.plate(booth.db.active_plate()["id"])
    assert p["text_color"] == "red" and sorted(t["name"] for t in p["tags"]) == ["A", "B", "D"]
    assert len(p["map"]) == 3


def test_cancel_and_limits(env):
    booth, _, _ = env
    o = order(booth, ("A", "baloo", "stadium", "red"), ("B", "baloo", "stadium", "red"))
    held = booth.db.order(o["order_id"])["tags"][1]
    booth.staff_cancel_tag(held["id"])
    o2 = booth.db.order(o["order_id"])
    assert o2["price_cents"] == 0 and o2["paid"] == 1
    with pytest.raises(BoothError):
        booth.place_order([])
    booth.cfg.queue_limit = 1
    with pytest.raises(BoothError) as e:
        order(booth, ("C", "baloo", "stadium", "red"))
    assert e.value.code == "queue_full"


def test_failed_plate_requeues_and_pauses(env):
    booth, printer, clock = env
    order(booth, ("A", "baloo", "stadium", "red"))
    booth.staff_start_now("red")
    booth.tick()
    pid = booth.db.active_plate()["id"]
    printer.abort()                                 # someone stopped it on the printer
    clock.advance(200)
    booth.tick()
    assert booth.db.plate(pid)["status"] == "failed"
    assert booth.db.get_state("paused") is True
    assert booth.db.queued_tags()[0]["name"] == "A"


def test_api(tmp_path):
    from fastapi.testclient import TestClient
    from booth.server import create_app
    booth = Booth(load_config(data_dir=tmp_path), printer=SimPrinter(), setup_name="nozzle040s")
    with TestClient(create_app(booth, run_loop=False)) as c:
        cfg = c.get("/api/config").json()
        assert [s["id"] for s in cfg["shapes"]] == ["stadium", "star", "tree", "bell"]
        assert c.get(cfg["fonts"][0]["url"]).status_code == 200
        icon = c.get("/api/shapes/tree/icon").json()
        assert icon["outline"].startswith("M") and icon["text"].startswith("M")
        assert (tmp_path / "icons" / "tree.json").exists()
        assert c.get("/api/shapes/bone/icon").json()["error"] == "bad_shape"
        assert c.post("/api/fit", json={"name": "emma", "font": "baloo"}).json()["star"] is True
        p = c.post("/api/preview", json={"name": "emma", "font": "baloo", "shape": "bell"}).json()
        assert p["name"] == "EMMA" and p["estimated_min"] > 0
        r = c.post("/api/orders", json={"tags": [{"preview_id": p["preview_id"], "text_color": "red"}]}).json()
        assert r["number"] == 1 and not r["needs_payment"]
        assert c.post("/api/orders", json={"tags": [{"preview_id": "p_x", "text_color": "red"}]}).json()["error"] \
            == "preview_expired"
        assert c.get("/api/status").json()["queue_length"] == 1
        assert c.get("/api/staff/overview").status_code == 401
        assert c.post("/api/staff/login", json={"pin": "0000"}).status_code == 403
        tok = c.post("/api/staff/login", json={"pin": booth.cfg.staff_pin}).json()["token"]
        h = {"X-Staff-Token": tok}
        ov = c.get("/api/staff/overview", headers=h).json()
        assert ov["orders"][0]["tags"][0]["name"] == "EMMA"
        assert c.post("/api/staff/start_now/red", headers=h).json()["ok"]
        assert c.get("/api/staff/stats", headers=h).json()["today"]["orders"] == 1
        r = c.get(f"/api/staff/export.csv?token={tok}")
        assert r.status_code == 200 and "EMMA" in r.text and "attachment" in r.headers["content-disposition"]
        assert c.get("/api/staff/export.csv?day=x", headers=h).status_code == 400
        assert c.post("/api/staff/backup", headers=h).json()["file"].endswith(".sqlite")
        assert c.get("/staff/").status_code == 200


@pytest.fixture
def cfg_env(tmp_path):
    import shutil
    from booth.config import CONFIG
    path = tmp_path / "booth.json"
    shutil.copy(CONFIG, path)
    clock = Clock()
    booth = Booth(load_config(path, data_dir=tmp_path), printer=SimPrinter(speed=1.0, clock=clock), clock=clock)
    return booth, path


def test_settings_roundtrip_and_live_apply(cfg_env):
    import json
    booth, path = cfg_env
    s = booth.staff_settings()
    assert s["settings"]["staff_pin"] == "" and "api_key" not in s["settings"]["printer"]
    d = s["settings"]
    d["event_name"] = "Adventsbasar"
    d["pricing"]["price_per_extra_cents"] = 150
    d["text_colors"].append({"id": "pink", "name": "Pink", "hex": "#ec407a"})
    d["disabled_shapes"] = ["bell"]
    d["kiosk"] = {"idle_s": 60, "sound": False}
    rev = booth.config_rev
    booth.staff_update_settings(d)
    assert booth.config_rev == rev + 1
    pub = booth.public_config()
    assert pub["event_name"] == "Adventsbasar" and pub["pricing"]["price_per_extra_cents"] == 150
    assert "bell" not in [x["id"] for x in pub["shapes"]] and pub["kiosk"] == {"idle_s": 60, "sound": False}
    saved = json.loads(path.read_text())
    assert saved["text_colors"][-1]["hex"] == "#EC407A" and saved["staff_pin"] == "2468"   # empty PIN = unchanged


def test_settings_guards(cfg_env):
    booth, _ = cfg_env
    p = booth.preview("EMMA", "baloo", "star")
    booth.place_order([{"preview_id": p.id, "text_color": "red"}])
    d = booth.staff_settings()["settings"]
    d["text_colors"] = [c for c in d["text_colors"] if c["id"] != "red"]
    with pytest.raises(BoothError, match="Rot"):
        booth.staff_update_settings(d)
    d = booth.staff_settings()["settings"]
    d["print_setup"] = "nozzle040"
    with pytest.raises(BoothError, match="Setup"):
        booth.staff_update_settings(d)
    for bad in ({"staff_pin": "12"}, {"queue_limit": 0}, {"base_color": {"name": "X", "hex": "blue"}},
                {"disabled_fonts": [f for f in booth.fonts]}):
        d = {**booth.staff_settings()["settings"], **bad}
        with pytest.raises(BoothError):
            booth.staff_update_settings(d)
    d = booth.staff_settings()["settings"]
    d["staff_pin"] = "1357"
    booth.staff_update_settings(d)
    assert booth.cfg.staff_pin == "1357"


def test_settings_setup_and_printer_switch(cfg_env):
    booth, _ = cfg_env
    d = booth.staff_settings()["settings"]
    d["print_setup"] = "nozzle040"
    d["printer"] = {**d["printer"], "type": "prusalink", "host": "127.0.0.1:9", "api_key": "secret"}
    booth.staff_update_settings(d)
    assert booth.setup.name == "nozzle040" and booth.printer.kind != "sim"
    assert booth.cfg.printer["api_key"] == "secret"
    d = booth.staff_settings()["settings"]
    assert d["printer"]["has_api_key"] is True
    booth.staff_update_settings(d)                                  # empty api_key = keep
    assert booth.cfg.printer["api_key"] == "secret"
    assert booth.staff_test_printer(d["printer"])["state"] == "offline"


def test_stats_close_day_backup_csv(env, tmp_path):
    booth, printer, clock = env
    order(booth, ("EMMA", "baloo", "star", "red"))
    o2 = order(booth, ("OMA", "baloo", "stadium", "red"), ("OPA", "titan", "tree", "red"))
    order(booth, ("LEO", "baloo", "bell", "gold"), ("MIA", "baloo", "bell", "gold"))      # unpaid, stays held
    booth.staff_paid(o2["order_id"])
    booth.staff_start_now("red")
    run_until(booth, clock, lambda: booth.db.active_plate() and booth.db.active_plate()["status"] == "color_change")
    printer.resume()
    run_until(booth, clock, lambda: booth.db.active_plate()["status"] == "printed")
    st = booth.stats()
    assert st["orders"] == 3 and st["tags_printed"] == 3 and st["paid_cents"] == 200 and st["due_cents"] == 200
    assert st["by_color"] == {"red": 3} and st["tags_open"] == 2 and st["free_tags"] == 3
    with pytest.raises(BoothError):                                  # plate still on the bed
        booth.staff_close_day()
    pv = booth.close_day_preview()
    assert pv["tags_unprinted"] == 2 and pv["orders_unpaid"] == 1
    booth.staff_plate_cleared(booth.db.active_plate()["id"])
    assert booth.close_day_preview()["orders_waiting_pickup"] == 2
    res = booth.staff_close_day()
    assert Path(res["backup"]).exists() and res["removed_files"] >= 3
    assert booth.db.q1("SELECT COUNT(*) AS n FROM orders WHERE status='open'")["n"] == 0
    assert booth.open_tag_count() == 0
    assert booth.db.q1("SELECT status FROM orders WHERE number=3")["status"] == "cancelled"
    csv = booth.export_csv(booth._day())
    assert csv.count("\n") == 6 and "EMMA" in csv and "2,00" in csv
    clock.advance(86400)                                             # next day: numbers restart
    assert order(booth, ("NEU", "baloo", "star", "red"))["number"] == 1


def test_auto_backup_rotates(env):
    booth, _, clock = env
    import booth.service as svc
    for _ in range(svc.BACKUP_KEEP + 3):
        booth._maybe_backup()
        clock.advance(svc.BACKUP_EVERY_S)
    files = list((booth.data / "backups").glob("booth-*.sqlite"))
    assert len(files) == svc.BACKUP_KEEP
