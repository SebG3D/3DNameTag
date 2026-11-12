#!/usr/bin/env python3
"""Simulate a whole booth day in fast-forward with the real backend code
(real OpenSCAD previews, real PrusaSlicer slicing, simulated printer and a
fake clock) and report what kids and staff would experience.

  backend/.venv/bin/python tools/simulate_day.py                 # 150 orders, 10-16 h
  backend/.venv/bin/python tools/simulate_day.py --orders 80 --hours 4 --seed 3
  backend/.venv/bin/python tools/simulate_day.py --no-incidents --plate-max 6

Simulated: kids arrive (busier in the afternoon), 1-3 tags per order,
all tags print at once (money is taken at pickup), staff clear the bed and
start the recommended plate, answer the colour change with realistic delays,
kids pick up (and pay) when ready. Incidents (unless --no-incidents): one
print stopped on the printer (-> plate failed, staff restart it) and one
backend restart in the middle of a plate.

Checks at the end (exit code 1 if one fails): every tag printed exactly once
or cancelled, no tag lost, pickup numbers unique, nothing stuck.
"""
import argparse
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from booth.config import load_config                 # noqa: E402
from booth.printer import SimPrinter                 # noqa: E402
from booth.service import Booth, BoothError          # noqa: E402

SHAPE_WEIGHT = {"stadium": 4, "wave": 3, "star": 3, "tree": 2, "bell": 2}   # how often kids pick a shape

NAMES = ("EMMA MIA SOFIA HANNAH LINA ELLA CLARA LEA MARIE LENA ANNA LUISA FINN NOAH ELIAS PAUL "
         "LEON BEN FELIX LUKAS MAX JONAS THEO HENRY OMA OPA MAMA PAPA JOSEFINE MAXIMILIAN "
         "ZOE JÜRGEN SÖREN GRETA-MARIE ANTON-LUCA KARL").split()


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self):
        return self.t


def weighted(rng, d: dict):
    return rng.choices(list(d), weights=list(d.values()))[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--orders", type=int, default=150)
    ap.add_argument("--hours", type=float, default=6)
    ap.add_argument("--start", default="10:00")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--plate-max", type=int, help="override plate.max_tags")
    ap.add_argument("--plate-wait", type=float, help="override plate.max_wait_min")
    ap.add_argument("--queue-limit", type=int, help="override queue_limit")
    ap.add_argument("--no-incidents", action="store_true")
    ap.add_argument("--step", type=float, default=10, help="simulated seconds per tick")
    ap.add_argument("--setup", default=None)
    ap.add_argument("--debug", action="store_true", help="print every order")
    ap.add_argument("--data", type=Path, help="data dir (default: new temp dir)")
    a = ap.parse_args()
    rng = random.Random(a.seed)

    data = a.data or Path(tempfile.mkdtemp(prefix="booth-sim-"))
    cfg = load_config(data_dir=data)
    cfg.path = None                                          # never write the real config
    if a.plate_max:
        cfg.plate_max_tags = a.plate_max
    if a.plate_wait is not None:
        cfg.plate_max_wait_min = a.plate_wait
    if a.queue_limit:
        cfg.queue_limit = a.queue_limit
    h, m = map(int, a.start.split(":"))
    day0 = time.mktime(time.strptime(time.strftime("%Y-%m-%d") + f" {h:02d}:{m:02d}", "%Y-%m-%d %H:%M"))
    clock = Clock(day0)
    printer = SimPrinter(speed=1.0, clock=clock, prep_s=cfg.plate_prep_min * 60)   # as measured on the Core One
    booth = Booth(cfg, printer=printer, setup_name=a.setup, clock=clock)
    fonts, shapes = list(booth.fonts), list(booth.shapes)
    colors = [c["id"] for c in cfg.text_colors]
    end = day0 + a.hours * 3600

    # arrivals: busier in the second half (weights 1 .. 2)
    arrivals = sorted(day0 + a.hours * 3600 * (rng.random() ** 0.8) for _ in range(a.orders))
    incidents = [] if a.no_incidents else [("abort", day0 + a.hours * 3600 * 0.35),
                                           ("restart", day0 + a.hours * 3600 * 0.6)]

    orders = {}            # order_id -> dict(number, t, eta_s, n, pays_at, cancel_at, ready_t, picked)
    rejected = []          # (t, reason)
    staff = {"cc_at": None, "clear_at": None, "resume_at": None}
    stats = {"previews": 0, "preview_s": 0.0, "plates": 0, "slice_s": 0.0, "max_queue": 0, "fit_fail": 0,
             "paused_min": 0.0}
    plates_seen = set()
    log = []

    def note(msg):
        log.append(f"{time.strftime('%H:%M', time.localtime(clock.t))} {msg}")

    def place():
        n = weighted(rng, {1: 60, 2: 25, 3: 15})
        items = []
        for _ in range(n):
            name, font = rng.choice(NAMES), weighted(rng, dict(zip(fonts, (5, 2, 4, 2, 3, 2))))
            shape = weighted(rng, {s: SHAPE_WEIGHT.get(s, 2) for s in shapes})
            fit = booth.fit(name, font)
            if not any(fit.values()):                           # fits no shape: kid picks a plainer font
                stats["fit_fail"] += 1
                font = "baloo"
                fit = booth.fit(name, font)
            if not fit[shape]:
                stats["fit_fail"] += 1
                shape = next(s for s in shapes if fit[s])          # kid picks another shape
            t0 = time.perf_counter()
            p = booth.preview(name, font, shape)
            stats["previews"] += 1
            stats["preview_s"] += time.perf_counter() - t0
            items.append({"preview_id": p.id, "text_color": weighted(rng, dict(zip(colors, (3, 2, 4, 2, 1))))})
        try:
            r = booth.place_order(items)
        except BoothError as e:
            rejected.append((clock.t, e.code))
            note(f"order rejected: {e.code}")
            return
        # unpaid tags print right away, the money is taken at pickup
        orders[r["order_id"]] = {"number": r["number"], "t": clock.t, "eta_s": r["eta_s"], "n": n,
                                 "pays_at": None, "cancel_at": None, "ready_t": None, "picked": False}

    t_wall = time.perf_counter()
    ai = 0
    while True:
        now = clock.t
        while ai < len(arrivals) and arrivals[ai] <= now:
            place()
            ai += 1
        # incidents
        for inc in list(incidents):
            kind, at = inc
            if now < at:
                continue
            act = booth.db.active_plate()
            if kind == "abort" and act and act["status"] == "printing":
                printer.abort()
                note(f"INCIDENT: plate {act['id']} stopped on the printer")
                incidents.remove(inc)
            elif kind == "restart" and act and act["status"] in ("printing", "color_change"):
                booth = Booth(cfg, printer=printer, setup_name=a.setup, clock=clock)
                note(f"INCIDENT: backend restart during plate {act['id']}")
                incidents.remove(inc)
        # staff
        for oid, o in orders.items():
            if o["pays_at"] and now >= o["pays_at"]:
                booth.staff_paid(oid)
                o["pays_at"] = None
            if o["cancel_at"] and now >= o["cancel_at"]:
                for t in booth.db.q("SELECT id FROM tags WHERE order_id=? AND status='held'", oid):
                    booth.staff_cancel_tag(t["id"])
                o["cancel_at"] = None
        act = booth.db.active_plate()
        if act:
            if act["id"] not in plates_seen and act["status"] != "building":
                plates_seen.add(act["id"])
                stats["plates"] += 1
            if act["status"] == "color_change":
                staff["cc_at"] = staff["cc_at"] or now + rng.uniform(30, 180)
                if now >= staff["cc_at"]:
                    printer.resume()
                    staff["cc_at"] = None
        else:
            # staff: bed empty + base colour, then start the recommended plate (a failed one is
            # restarted after looking at the printer); nothing recommended -> let plates fill up
            failed = booth.db.q1("SELECT id FROM plates WHERE status='failed' ORDER BY id")
            nxt = failed["id"] if failed else booth.recommended_plate()
            if nxt is None:
                staff["clear_at"] = None
            else:
                if staff["clear_at"] is None:
                    staff["clear_at"] = now + rng.uniform(120, 300) if failed else now + rng.uniform(60, 300)
                    if failed:
                        note(f"plate {nxt} failed - staff restart it")
                if now >= staff["clear_at"]:
                    staff["clear_at"] = None
                    try:
                        booth.staff_plate_start(nxt)
                    except BoothError as e:
                        note(f"start refused: {e}")
        # pickup
        for oid, o in orders.items():
            if o["ready_t"] is None:
                tags = booth.db.q("SELECT status FROM tags WHERE order_id=? AND status!='cancelled'", oid)
                if tags and all(t["status"] == "printed" for t in tags):
                    o["ready_t"] = now
            elif not o["picked"] and now >= o["ready_t"] + 120:
                booth.staff_pickup(oid)
                o["picked"] = True
        stats["max_queue"] = max(stats["max_queue"], booth.open_tag_count())

        t0 = time.perf_counter()
        booth.tick()
        dt = time.perf_counter() - t0
        if dt > 1:
            stats["slice_s"] += dt
        clock.t += a.step
        open_tags = booth.open_tag_count()
        if clock.t > end and ai >= len(arrivals) and open_tags == 0 and not booth.db.active_plate() \
                and all(o["picked"] for o in orders.values()):
            break
        if clock.t > end + 6 * 3600:
            note("STUCK: queue not empty 6 h after closing")
            break

    # ---------------- report
    db = booth.db
    problems = []
    tags = db.q("SELECT * FROM tags")
    for t in tags:
        if t["status"] not in ("printed", "cancelled"):
            problems.append(f"tag {t['id']} {t['name']} ends as {t['status']}")
        if t["status"] == "printed" and not t["plate_id"]:
            problems.append(f"tag {t['id']} printed without plate")
    nums = [o["number"] for o in db.q("SELECT number FROM orders")]
    if len(nums) != len(set(nums)):
        problems.append("duplicate pickup numbers")
    printed_plates = db.q("SELECT * FROM plates WHERE status IN ('printed','done','archived')")
    per_plate = [db.q1("SELECT COUNT(*) AS n FROM tags WHERE plate_id=?", p["id"])["n"] for p in printed_plates]
    failed = db.q("SELECT id, error FROM plates WHERE status IN ('failed','cancelled','deleted') "
                  "AND started IS NOT NULL")
    for oid, o in orders.items():
        live = db.q1("SELECT COUNT(*) AS n FROM tags WHERE order_id=? AND status!='cancelled'", oid)["n"]
        if live and o["ready_t"] is None:
            problems.append(f"order #{o['number']} never ready")

    eta_err, waits = [], []
    for o in orders.values():
        if o["ready_t"]:
            waits.append((o["ready_t"] - o["t"]) / 60)
            eta_err.append((o["ready_t"] - o["t"] - o["eta_s"]) / 60)
            if a.debug:
                print(f"#{o['number']:3d} {time.strftime('%H:%M', time.localtime(o['t']))} n={o['n']} "
                      f"eta {o['eta_s'] / 60:5.0f} real {(o['ready_t'] - o['t']) / 60:5.0f} "
                      f"colors {[t['text_color'] for t in db.q('SELECT text_color FROM tags WHERE order_id=(SELECT id FROM orders WHERE number=?)', o['number'])]}")
    busy = sum((p["finished"] or 0) - (p["started"] or 0) for p in printed_plates)
    span = clock.t - day0
    st = booth.stats(time.strftime("%Y-%m-%d", time.localtime(day0)))

    def q(vals, p):
        return statistics.quantiles(vals, n=20)[p] if len(vals) >= 20 else max(vals or [0])

    print(f"\n=== Booth day simulation (seed {a.seed}, {a.orders} kids, {a.hours:g} h from {a.start}, "
          f"plate max {cfg.plate_max_tags}, wait {cfg.plate_max_wait_min:g} min, queue limit {cfg.queue_limit}) ===")
    print(f"orders placed    {len(orders)}   rejected {len(rejected)} "
          f"({', '.join(sorted({r for _, r in rejected})) or '-'})")
    print(f"tags printed     {st['tags_printed']}   cancelled {st['tags_cancelled']}   "
          f"names that did not fit the first shape: {stats['fit_fail']}")
    print(f"money            {st['paid_cents'] / 100:.2f} EUR paid")
    print(f"plates           {len(printed_plates)} printed, {len(failed)} failed/cancelled, "
          f"tags/plate avg {statistics.mean(per_plate or [0]):.1f} (min {min(per_plate or [0])}, max {max(per_plate or [0])})")
    print(f"printer busy     {busy / 3600:.1f} h of {span / 3600:.1f} h ({100 * busy / span:.0f} %)")
    print(f"max open tags    {stats['max_queue']}")
    if waits:
        print(f"wait until ready median {statistics.median(waits):.0f} min, 90 % {q(waits, 17):.0f} min, "
              f"max {max(waits):.0f} min")
        late = [e for e in eta_err if e > 10]
        print(f"ETA shown vs real: median {statistics.median(eta_err):+.0f} min (+ = later than promised), "
              f"90 % {q(eta_err, 17):+.0f} min, {len(late)} orders > 10 min late, "
              f"{sum(e < -20 for e in eta_err)} orders > 20 min early")
    last = max((o["ready_t"] for o in orders.values() if o["ready_t"]), default=clock.t)
    print(f"last tag ready   {time.strftime('%H:%M', time.localtime(last))}")
    print(f"compute          {stats['previews']} previews, avg {stats['preview_s'] / max(1, stats['previews']):.2f} s; "
          f"wall time {time.perf_counter() - t_wall:.0f} s")
    print("events:")
    for line in log[:30]:
        print("  " + line)
    for f in failed:
        print(f"  plate {f['id']} failed: {f['error']}")
    print("CHECKS: " + ("OK" if not problems else "FAILED"))
    for p in problems[:20]:
        print("  - " + p)
    print(f"data kept in {data}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
