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
    assert fit == {"stadium": True, "wave": True, "star": True, "tree": True, "bell": True}
    p = booth.preview("emma", "baloo", "star")
    assert p.name == "EMMA" and p.stl.exists() and p.area_mm2 > 500
    assert p.outline.startswith("M") and p.text.startswith("M")
    for bad in [("EMMA!", "baloo", "star"), ("EMMA", "nope", "star"), ("EMMA", "baloo", "bone")]:
        with pytest.raises(BoothError):
            booth.preview(*bad)


def plate_of(booth, tag_id):
    return booth.db.q1("SELECT plate_id FROM tags WHERE id=?", tag_id)["plate_id"]


def start(booth, pid):
    booth.staff_plate_start(pid)
    booth.tick()                                    # builds, slices and sends it
    return booth.db.plate(pid)


def test_order_payment_and_plate_flow(env):
    booth, printer, clock = env
    o = order(booth, ("emma", "baloo", "stadium", "white"), ("oma", "titan", "tree", "white"))
    assert o["number"] == 1 and o["needs_payment"] and o["price_cents"] == 200
    tags = booth.db.order(o["order_id"])["tags"]
    assert [t["status"] for t in tags] == ["queued", "queued"]        # unpaid tags print too
    pid = plate_of(booth, tags[0]["id"])
    assert pid and plate_of(booth, tags[1]["id"]) == pid               # planned onto one waiting plate

    booth.tick()
    assert booth.db.active_plate() is None                             # nothing starts by itself
    ov = booth.staff_overview()
    (pv,) = ov["plates"]
    assert pv["state"] == "waiting" and pv["count"] == 2 and pv["max"] == booth.cfg.plate_max_tags
    assert len(pv["map"]) == 2 and pv["tags"][0]["outline"].startswith("M") and not pv["recommended"]
    clock.advance(booth.cfg.plate_max_wait_min * 60 + 1)
    assert booth.staff_overview()["plates"][0]["recommended"]

    plate = start(booth, pid)
    assert plate["status"] == "printing" and plate["text_color"] == "white"
    assert sorted(t["name"] for t in plate["tags"]) == ["EMMA", "OMA"]
    gcode = Path(plate["gcode"]).read_text()
    assert [ln for ln in gcode.splitlines() if ln.startswith("M600")]
    with pytest.raises(BoothError):                                    # one at a time
        booth.staff_plate_start(pid)

    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "color_change")
    printer.resume()
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "done")
    assert {t["status"] for t in booth.db.order(o["order_id"])["tags"]} == {"printed"}
    ov = booth.staff_overview()
    assert ov["orders"][0]["ready"] and ov["plates"][0]["state"] == "done"

    # restart a done plate (e.g. bad print): same tags, same G-code, printer still FINISHED
    mtime = Path(plate["gcode"]).stat().st_mtime
    p2 = start(booth, pid)
    assert p2["status"] == "printing" and Path(p2["gcode"]).stat().st_mtime == mtime
    booth.tick()
    assert booth.db.plate(pid)["status"] == "printing"
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "color_change")
    printer.resume()
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "done")

    booth.staff_pickup(o["order_id"])
    od = booth.db.order(o["order_id"])
    assert od["paid"] == 1 and od["status"] == "done"
    booth.staff_plate_delete(pid)
    assert booth.staff_overview()["plates"] == [] and booth.db.plate(pid)["status"] == "archived"


def test_prep_and_colour_wait_kept_out_of_real_factor(env):
    """Real time = fixed printer prep + slicer estimate * real_factor + wait at the M600.
    The forecast adds the prep; the learned factor only sees the printing part."""
    booth, printer, clock = env
    printer.prep_s = booth.cfg.plate_prep_min * 60
    o = order(booth, ("emma", "baloo", "stadium", "white"))
    tag = booth.db.order(o["order_id"])["tags"][0]
    eta = booth.forecast()[tag["id"]]
    assert eta >= booth.cfg.plate_prep_min * 60          # prep is part of the ETA
    pid = plate_of(booth, tag["id"])
    start(booth, pid)
    f0 = booth.real_factor
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "color_change", step=2)
    clock.advance(15 * 60)                               # staff takes 15 min for the swap
    booth.tick()
    printer.resume()
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "done", step=2)
    # sim prints exactly est_s after the prep -> f ~ 1.0. Without separating prep and the
    # 15 min wait, f would be > 3 and ignored, so the factor would stay at f0.
    assert booth.real_factor < f0 - 0.03
    assert booth.real_factor == pytest.approx(0.7 * f0 + 0.3 * 1.0, abs=0.02)


def test_colors_grouped_full_plate_recommended(env):
    booth, _, _ = env
    booth.cfg.plate_max_tags = 3
    for name in ["A", "B"]:
        order(booth, (name, "baloo", "stadium", "red"))
    order(booth, ("C", "baloo", "stadium", "white"))
    plates = booth.staff_overview()["plates"]
    assert [(p["text_color"], p["count"]) for p in plates] == [("red", 2), ("white", 1)]
    assert booth.recommended_plate() is None                # red has 2 < 3
    order(booth, ("D", "baloo", "stadium", "red"), ("E", "baloo", "stadium", "red"))
    plates = booth.staff_overview()["plates"]
    assert [(p["text_color"], p["count"]) for p in plates] == [("red", 3), ("white", 1), ("red", 1)]
    assert booth.recommended_plate() == plates[0]["id"]
    assert sorted(t["name"] for t in plates[0]["tags"]) == ["A", "B", "D"]
    f = booth.forecast()
    assert len(f) == 5 and max(f.values()) == booth.eta_s()


def test_cancel_and_limits(env):
    booth, _, _ = env
    o = order(booth, ("A", "baloo", "stadium", "red"), ("B", "baloo", "stadium", "red"))
    second = booth.db.order(o["order_id"])["tags"][1]
    booth.staff_cancel_tag(second["id"])
    o2 = booth.db.order(o["order_id"])
    assert o2["price_cents"] == 0 and o2["paid"] == 1
    assert booth.staff_overview()["plates"][0]["count"] == 1
    booth.staff_cancel_order(o["order_id"])
    assert booth.staff_overview()["plates"] == []           # empty waiting plate is gone
    with pytest.raises(BoothError):
        booth.place_order([])
    booth.cfg.queue_limit = 1
    order(booth, ("C", "baloo", "stadium", "red"))
    with pytest.raises(BoothError) as e:
        order(booth, ("D", "baloo", "stadium", "red"))
    assert e.value.code == "queue_full"


def test_failed_plate_restart_and_delete(env):
    booth, printer, clock = env
    o = order(booth, ("A", "baloo", "stadium", "red"))
    tid = booth.db.order(o["order_id"])["tags"][0]["id"]
    pid = plate_of(booth, tid)
    start(booth, pid)
    printer.abort()                                 # someone stopped it on the printer
    clock.advance(200)
    booth.tick()
    p = booth.db.plate(pid)
    assert p["status"] == "failed" and p["error"]
    assert booth.db.q1("SELECT status FROM tags WHERE id=?", tid)["status"] == "queued"
    assert plate_of(booth, tid) == pid                 # stays on its plate for a restart
    assert booth.staff_overview()["plates"][0]["state"] == "error"
    assert start(booth, pid)["status"] == "printing" and booth.db.plate(pid)["error"] is None
    booth.staff_plate_delete(pid)                       # while printing: stops it, name back in the queue
    assert printer.status().state == "idle"
    assert booth.db.plate(pid)["status"] == "deleted"
    new = plate_of(booth, tid)
    assert new and new != pid and booth.db.q1("SELECT status FROM tags WHERE id=?", tid)["status"] == "queued"


def test_start_needs_ready_printer(env):
    booth, printer, clock = env
    order(booth, ("A", "baloo", "stadium", "red"))
    order(booth, ("B", "baloo", "stadium", "white"))
    a, b = [p["id"] for p in booth.staff_overview()["plates"]]
    start(booth, a)
    printer.abort()
    printer.job = {"est": 100, "done_s": 0, "last": clock(), "cc_frac": None, "waiting_since": None,
                   "state": "printing", "name": "x"}     # printer busy with something else
    booth.db.plate_status(a, "failed", error="x")
    with pytest.raises(BoothError) as e:
        booth.staff_plate_start(b)
    assert e.value.code == "printer_busy"


def test_api(tmp_path):
    from fastapi.testclient import TestClient
    from booth.server import create_app
    booth = Booth(load_config(data_dir=tmp_path), printer=SimPrinter(), setup_name="nozzle040s")
    with TestClient(create_app(booth, run_loop=False)) as c:
        cfg = c.get("/api/config").json()
        assert [s["id"] for s in cfg["shapes"]] == ["stadium", "wave", "star", "tree", "bell"]
        assert c.get(cfg["fonts"][0]["url"]).status_code == 200
        icon = c.get("/api/shapes/tree/icon").json()
        assert icon["outline"].startswith("M") and icon["text"].startswith("M")
        assert (tmp_path / "icons" / "tree.json").exists()
        assert c.get("/api/shapes/bone/icon").json()["error"] == "bad_shape"
        real = c.get("/api/shapes/tree/icon", params={"name": "jonas", "font": "titan"}).json()
        assert real["outline"].startswith("M") and real["text"] != icon["text"]
        assert c.get("/api/shapes/tree/icon", params={"name": "jonas", "font": "titan"}).json() == real
        assert c.get("/api/shapes/stadium/icon", params={"name": "jo$", "font": "titan"}).json()["error"] == "bad_name"
        assert c.post("/api/fit", json={"name": "emma", "font": "baloo"}).json()["star"] is True
        p = c.post("/api/preview", json={"name": "emma", "font": "baloo", "shape": "bell"}).json()
        assert p["name"] == "EMMA" and p["estimated_min"] > 0
        r = c.post("/api/orders", json={"tags": [{"preview_id": p["preview_id"], "text_color": "red"}],
                                        "customer": " lena  m "}).json()
        assert r["number"] == 1 and not r["needs_payment"] and r["customer"] == "LENA M"
        assert c.post("/api/orders", json={"tags": [{"preview_id": "p_x", "text_color": "red"}]}).json()["error"] \
            == "preview_expired"
        assert c.get("/api/status").json()["queue_length"] == 1
        assert c.get("/api/staff/overview").status_code == 401
        assert c.post("/api/staff/login", json={"pin": "0000"}).status_code == 403
        tok = c.post("/api/staff/login", json={"pin": booth.cfg.staff_pin}).json()["token"]
        h = {"X-Staff-Token": tok}
        ov = c.get("/api/staff/overview", headers=h).json()
        assert ov["orders"][0]["tags"][0]["name"] == "EMMA" and ov["orders"][0]["customer"] == "LENA M"
        assert ";LENA M;" in c.get("/api/staff/export.csv", headers=h).text
        pid = ov["plates"][0]["id"]
        assert c.post(f"/api/staff/plates/{pid}/start", headers=h).json()["ok"]
        assert c.post(f"/api/staff/plates/{pid}/start", headers=h).status_code == 409
        assert c.get("/api/staff/stats", headers=h).json()["today"]["orders"] == 1
        r = c.get(f"/api/staff/export.csv?token={tok}")
        assert r.status_code == 200 and "EMMA" in r.text and "attachment" in r.headers["content-disposition"]
        assert c.get("/api/staff/export.csv?day=x", headers=h).status_code == 400
        assert c.post("/api/staff/backup", headers=h).json()["file"].endswith(".sqlite")
        assert c.get("/api/staff/system", headers=h).json()["allowed"] is False      # only with BOOTH_ALLOW_SYSTEM=1
        assert c.post("/api/staff/system/time", headers=h, json={"time": 1.8e9}).status_code == 403
        assert c.post("/api/staff/system/poweroff", headers=h).status_code == 403
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
    order(booth, ("LEO", "baloo", "bell", "gold"), ("MIA", "baloo", "bell", "gold"))      # unpaid, not printed
    booth.staff_paid(o2["order_id"])
    pid = plate_of(booth, booth.db.order(o2["order_id"])["tags"][0]["id"])
    start(booth, pid)
    run_until(booth, clock, lambda: booth.db.active_plate() and booth.db.active_plate()["status"] == "color_change")
    printer.resume()
    with pytest.raises(BoothError):                                  # plate still printing
        booth.staff_close_day()
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "done")
    st = booth.stats()
    assert st["orders"] == 3 and st["tags_printed"] == 3 and st["paid_cents"] == 200 and st["due_cents"] == 200
    assert st["by_color"] == {"red": 3} and st["tags_open"] == 2 and st["free_tags"] == 3
    pv = booth.close_day_preview()
    assert pv["tags_unprinted"] == 2 and pv["orders_unpaid"] == 1
    assert booth.close_day_preview()["orders_waiting_pickup"] == 2
    res = booth.staff_close_day()
    assert Path(res["backup"]).exists() and res["removed_files"] >= 3
    assert booth.db.q1("SELECT COUNT(*) AS n FROM orders WHERE status='open'")["n"] == 0
    assert booth.open_tag_count() == 0 and booth.staff_overview()["plates"] == []
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


def test_reprint_single_tag(env):
    booth, printer, clock = env
    o = order(booth, ("A", "baloo", "stadium", "red"), ("B", "baloo", "stadium", "red"))
    a, b = booth.db.order(o["order_id"])["tags"]
    pid = plate_of(booth, a["id"])
    with pytest.raises(BoothError):                         # not printed yet
        booth.staff_reprint_tag(a["id"])
    start(booth, pid)
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "color_change")
    printer.resume()
    run_until(booth, clock, lambda: booth.db.plate(pid)["status"] == "done")
    booth.staff_pickup(o["order_id"])
    booth.staff_reprint_tag(b["id"])                       # B came out badly
    new = plate_of(booth, b["id"])
    assert new and new != pid
    assert booth.db.order(o["order_id"])["status"] == "open"   # back on the pickup list
    assert booth.recommended_plate() == new                    # old queue time: goes next
    ov = booth.staff_overview()
    assert not ov["orders"][0]["ready"]
    start(booth, new)
    assert [t["name"] for t in booth.db.plate(new)["tags"]] == ["B"]
