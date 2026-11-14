"""Booth service: previews, orders, plate scheduling, printer supervision.

The HTTP layer (server.py) is a thin wrapper around this class, so the whole
flow can be tested without HTTP and with a simulated printer.

Plates: every new tag goes onto a waiting plate of its text colour at once
(up to plate_max_tags and what fits on the bed), so staff see all plates
ahead. Nothing starts by itself: staff press start on a plate (confirming the
bed is empty and the base colour is loaded - after a plate the printer holds
the TEXT colour). The page recommends the plate the old auto policy would
have picked: full (or a newer plate of that colour exists) or its oldest tag
waited plate_max_wait_min; oldest tag first. A failed or done plate can be
restarted; deleting a plate puts its tags back in the queue.
"""
import json
import logging
import re
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from nametag.fonts import load_fonts
from nametag.names import NAME_MAX, clean_name
from nametag.plate import TOWER_KEEP_OUT, build_plate, pack
from nametag.render import layout, render_svg, render_tag
from nametag.setup import list_setups, load_setup
from nametag.shapes import load_shapes
from nametag.slicer import slice_plate

from .config import BoothConfig, ConfigError, config_dict, parse_config, save_config
from .db import DB
from .printer import Printer, PrinterStatus, SimPrinter, make_printer

log = logging.getLogger("booth")

PREVIEW_TTL_S = 600
LISTED = ("waiting", "building", "printing", "color_change", "failed", "done")
BACKUP_EVERY_S = 3600
BACKUP_KEEP = 48
ICON_NAME, ICON_FONT = "EMMA", "baloo"
START_GRACE_S = 90          # printer may report idle this long after upload
# Time model, refined after every sliced plate (est = overhead + area * k).
DEFAULT_PLATE_OVERHEAD_S = 35        # fitted to PrusaSlicer estimates, nozzle040s (2026-11-04)
DEFAULT_S_PER_MM2 = 0.157
DEFAULT_TAG_AREA_MM2 = 900           # wait estimate before the first real tags
# Staff can stop ordering (kiosk shows one of these, or their own text).
CLOSED_MESSAGES = {
    "pause": "Kurze Pause – gleich geht's weiter!",
    "printer": "Der Drucker macht gerade Pause. Bitte schau später nochmal vorbei!",
    "sold_out": "Für heute sind wir ausgebucht. Danke und bis bald!",
}
CLOSING_MESSAGE = "Für heute nehmen wir keine Bestellungen mehr an. Danke und bis bald!"
ORDERING_DEFAULT = {"open": True, "message": "pause", "close_at": None, "show_wait": True}


class BoothError(ValueError):
    """User-facing error with a code for the kiosk/staff UI."""
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


@dataclass
class Preview:
    id: str
    name: str
    font: str
    shape: str
    stl: Path
    outline: str          # SVG path data, mm, y down
    text: str
    w_mm: float
    h_mm: float
    area_mm2: float
    created: float = field(default_factory=time.time)


def path_area(d: str) -> float:
    """Net area of OpenSCAD SVG path data (M/L/z polygons, holes have the
    opposite winding)."""
    total = 0.0
    for sub in re.split(r"(?=M)", d):
        nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", sub)]
        pts = list(zip(nums[0::2], nums[1::2]))
        total += sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1])) / 2
    return abs(total)


def _bbox(d: str) -> tuple[float, float, float, float]:
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d)]
    xs, ys = nums[0::2], nums[1::2]
    return min(xs), min(ys), max(xs), max(ys)


class Booth:
    def __init__(self, cfg: BoothConfig, printer: Printer | None = None, setup_name: str | None = None,
                 clock=time.time):
        self.cfg, self.clock = cfg, clock
        self.setup_locked = setup_name is not None          # --setup on the command line wins
        self.setup = load_setup(setup_name or cfg.print_setup)
        self.config_rev = 1                                 # kiosk reloads when this changes
        self.kiosk_reset = 0                                # staff 'reset kiosk': kiosk reloads when this changes
        self.fonts, self.shapes = load_fonts(), load_shapes()
        self.data = cfg.data_dir
        for d in ("previews", "tags", "plates"):
            (self.data / d).mkdir(parents=True, exist_ok=True)
        self.db = DB(self.data / "booth.sqlite")
        self.printer = printer or make_printer(cfg.printer)
        self._icons: dict[tuple, dict] = {}                   # shape picker with the real name
        self.previews: dict[str, Preview] = {}
        # plate id -> last seen printer progress (persisted: survives a restart)
        self._progress: dict[int, float] = {int(k): v for k, v in self.db.get_state("plate_progress", {}).items()}
        self._cc_since: dict[int, float] = {}       # plate -> when it started waiting (colour change / pause)
        self._cc_wait: dict[int, float] = {}        # plate -> seconds spent waiting (kept out of real_factor)
        self._just_started: set[int] = set()        # started, printer not seen printing yet
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="render")
        self.lock = threading.RLock()            # scheduler vs. staff actions
        self.last_status = PrinterStatus("offline", message="not polled yet")
        self.plate_overhead_s = self.db.get_state("plate_overhead_s", DEFAULT_PLATE_OVERHEAD_S)
        self.s_per_mm2 = self.db.get_state("s_per_mm2", DEFAULT_S_PER_MM2)
        # real plate duration / slicer estimate (heating, M600 wait), learned
        self.real_factor = self.db.get_state("real_factor", 1.2)
        # real wait / forecast of finished orders (plates fill up with later arrivals), learned
        self.eta_factor = self.db.get_state("eta_factor", 1.1)
        self._stop = threading.Event()
        self._thread = None
        self._recover()

    # ------------------------------------------------------------------ setup
    def _recover(self) -> None:
        """A plate that was being built when the backend stopped is redone."""
        for p in self.db.q("SELECT id FROM plates WHERE status='building'"):
            self.db.plate_status(p["id"], "failed", error="Programm neu gestartet")

    def public_config(self) -> dict:
        c = self.cfg
        return {
            "event_name": c.event_name,
            "base_color": c.base_color,
            "text_colors": c.text_colors,
            "fonts": [{"id": f.id, "label": f.label, "url": f"/fonts/{f.id}.woff2"} for f in self.fonts.values()
                      if f.id not in c.disabled_fonts],
            "shapes": [{"id": s.id, "label": s.label} for s in self.shapes.values()
                       if s.id not in c.disabled_shapes],
            "kiosk": {"idle_s": c.kiosk_idle_s, "sound": c.kiosk_sound},
            "rev": self.config_rev,
            "pricing": {"free_tags": c.free_tags, "price_per_extra_cents": c.price_per_extra_cents},
            "max_tags_per_order": c.max_tags_per_order,
            "name_max": NAME_MAX,
            "queue_limit": c.queue_limit,
        }

    # ---------------------------------------------------------------- kiosk
    def _font_shape(self, font: str, shape: str):
        if font not in self.fonts:
            raise BoothError("bad_font")
        if shape not in self.shapes:
            raise BoothError("bad_shape")
        return self.fonts[font], self.shapes[shape]

    def _name(self, raw: str) -> str:
        try:
            return clean_name(raw)
        except ValueError:
            raise BoothError("bad_name") from None

    def fit(self, raw_name: str, font: str) -> dict:
        """Which shapes can carry this name (kiosk greys out the others)."""
        name = self._name(raw_name)
        f, _ = self._font_shape(font, next(iter(self.shapes)))
        return {s.id: layout(name, f, s, self.setup).fits for s in self.shapes.values()}

    def preview(self, raw_name: str, font: str, shape: str) -> Preview:
        name = self._name(raw_name)
        f, s = self._font_shape(font, shape)
        if not layout(name, f, s, self.setup).fits:
            raise BoothError("too_long")
        self._expire_previews()
        pid = "p_" + uuid.uuid4().hex[:10]
        d = self.data / "previews" / pid
        r = render_tag(name, f, s, self.setup, d, "tag")
        outline, text = render_svg(name, f, s, self.setup, d / "tag.svg")
        x0, y0, x1, y1 = _bbox(outline)
        p = Preview(pid, name, font, shape, r["files"]["tag"], outline, text,
                    round(x1 - x0, 1), round(y1 - y0, 1), round(path_area(outline), 1), self.clock())
        self.previews[pid] = p
        return p

    def shape_icon(self, shape: str, raw_name: str = "", font: str = "") -> dict:
        """Outline + text of a shape for the kiosk shape picker (2D only).
        With name + font: the customer's real text (kept in RAM for a while);
        without: a sample name, cached in the data dir - delete data/icons/
        after changing a shape."""
        if shape not in self.shapes:
            raise BoothError("bad_shape")
        if raw_name.strip() and font:
            name = self._name(raw_name)
            f, s = self._font_shape(font, shape)
            if not layout(name, f, s, self.setup).fits:
                raise BoothError("too_long")
            key = (name, font, shape)
            if key not in self._icons:
                with tempfile.TemporaryDirectory() as d:
                    outline, text = render_svg(name, f, s, self.setup, Path(d) / "icon.svg")
                if len(self._icons) >= 64:
                    self._icons.pop(next(iter(self._icons)))
                self._icons[key] = {"outline": outline, "text": text}
            return self._icons[key]
        cache = self.data / "icons" / f"{shape}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        font = self.fonts.get(ICON_FONT) or next(iter(self.fonts.values()))
        cache.parent.mkdir(exist_ok=True)
        outline, text = render_svg(ICON_NAME, font, self.shapes[shape], self.setup, cache.with_suffix(".svg"))
        icon = {"outline": outline, "text": text}
        cache.write_text(json.dumps(icon))
        return icon

    def tag_estimate_s(self, area_mm2: float) -> float:
        """Slicer-time share of one tag (without heating / colour change)."""
        return area_mm2 * self.s_per_mm2

    def _expire_previews(self) -> None:
        now = self.clock()
        for pid in [k for k, p in self.previews.items() if now - p.created > PREVIEW_TTL_S]:
            p = self.previews.pop(pid)
            shutil.rmtree(p.stl.parent, ignore_errors=True)

    def open_tag_count(self) -> int:
        return self.db.q1("SELECT COUNT(*) AS n FROM tags WHERE status IN ('held','queued','plated')")["n"]

    def queue_full(self) -> bool:
        return self.open_tag_count() >= self.cfg.queue_limit

    def place_order(self, items: list[dict], customer: str = "") -> dict:
        """items: [{preview_id, text_color}]; customer: who orders (the tags may
        carry other names: siblings, grandma ...)"""
        customer = self._name(customer) if customer.strip() else ""
        if not 1 <= len(items) <= self.cfg.max_tags_per_order:
            raise BoothError("bad_count")
        if self.queue_full():
            raise BoothError("queue_full")
        gate = self.ordering_state()
        if not gate["open"]:
            raise BoothError("closed", gate["message"])
        colors = {c["id"] for c in self.cfg.text_colors}
        previews = []
        for it in items:
            p = self.previews.get(it.get("preview_id", ""))
            if not p:
                raise BoothError("preview_expired")
            if it.get("text_color") not in colors:
                raise BoothError("bad_color")
            previews.append((p, it["text_color"]))
        tags = []
        for p, color in previews:
            dst = self.data / "tags" / f"{p.id}.stl"
            shutil.move(str(p.stl), dst)
            tags.append({"name": p.name, "font": p.font, "shape": p.shape, "text_color": color, "stl": dst,
                         "area_mm2": p.area_mm2, "w_mm": p.w_mm, "h_mm": p.h_mm,
                         "outline": p.outline, "text_svg": p.text})
        for p, _ in previews:
            self.previews.pop(p.id, None)
            shutil.rmtree(p.stl.parent, ignore_errors=True)
        price = self.cfg.price_cents(len(tags))
        order = self.db.create_order(tags, price, self.cfg.free_tags, self.clock(), customer=customer)
        with self.lock:
            self.plan()
        # whole order (kids wait for all their tags); the forecast does not know
        # later arrivals, so it is scaled by the learned eta_factor, +2 min,
        # rounded up to 5 min (early is fine, late is not)
        raw = self.eta_s([t["id"] for t in order["tags"]])
        with self.db.tx() as c:
            c.execute("UPDATE orders SET eta_raw=? WHERE id=?", (raw, order["id"]))
        eta = self.clock() + raw * self.eta_factor + 120
        eta = -(-eta // 300) * 300
        return {"order_id": order["id"], "number": order["number"], "customer": customer, "tags": len(tags),
                "price_cents": price, "needs_payment": price > 0,
                "eta": time.strftime("%H:%M", time.localtime(eta)), "eta_s": int(eta - self.clock())}

    def _start_order(self, plates: list[dict], now: float) -> list[dict]:
        """Waiting/failed plates as {id, color, tags, first, ready_at}; ready_at =
        when staff should start it (relative s): full plates (or an older plate
        of a colour that has a newer one) and failed ones at once, the others
        when their oldest tag waited plate_max_wait_min."""
        c = self.cfg
        wait_s = c.plate_max_wait_min * 60
        newest = {}
        for p in plates:
            newest[p["color"]] = max(newest.get(p["color"], 0), p["id"])
        for p in plates:
            full = len(p["tags"]) >= c.plate_max_tags or p["id"] < newest[p["color"]] or p.get("urgent")
            p["ready_at"] = 0.0 if full else max(0.0, p["first"] + wait_s - now)
        return plates

    def _pending_plates(self, probe: dict | None = None) -> list[dict]:
        now = self.clock()
        plates = []
        for pl in self.db.q("SELECT id, text_color, status FROM plates WHERE status IN ('waiting','failed') "
                            "ORDER BY id"):
            tags = self.db.q("SELECT id, area_mm2, reprint, COALESCE(queued_at, created) AS queued_at FROM tags "
                             "WHERE plate_id=? AND status='queued' ORDER BY queued_at, id", pl["id"])
            if tags:
                plates.append({"id": pl["id"], "color": pl["text_color"], "tags": tags,
                               "first": min(t["queued_at"] for t in tags),
                               "urgent": pl["status"] == "failed" or any(t["reprint"] for t in tags)})
        loose: dict[str, list[dict]] = {}              # not planned yet (only between plan() calls)
        for t in self.db.q("SELECT id, text_color, area_mm2, COALESCE(queued_at, created) AS queued_at FROM tags "
                           "WHERE status='queued' AND plate_id IS NULL ORDER BY queued_at, id"):
            loose.setdefault(t["text_color"], []).append(t)
        for color, tags in loose.items():
            for i in range(0, len(tags), self.cfg.plate_max_tags):
                chunk = tags[i:i + self.cfg.plate_max_tags]
                plates.append({"id": 10**9 + len(plates), "color": color, "tags": chunk,
                               "first": chunk[0]["queued_at"]})
        if probe:                                      # what-if tag for the wait estimate: own new plate
            plates.append({"id": 2 * 10**9, "color": "", "tags": [probe], "first": now})
        return self._start_order(plates, now)

    def recommended_plate(self) -> int | None:
        """The waiting plate staff should start next (None: let plates fill up)."""
        ready = [(p["first"], p["id"]) for p in self._pending_plates() if p["ready_at"] <= 0 and p["id"] < 10**9]
        return min(ready)[1] if ready else None

    def forecast(self, probe: dict | None = None) -> dict[int, float]:
        """Seconds from now until each queued tag is printed, assuming staff
        start plates as recommended (see _start_order) with the learned time
        model."""
        c = self.cfg
        t = 0.0
        plate = self.db.active_plate()
        if plate:
            st = self.last_status
            remain = st.remaining_s if st.remaining_s is not None and plate["status"] in ("printing", "color_change") \
                else (plate["est_s"] or 0)
            prep = c.plate_prep_min * 60 if plate["status"] != "color_change" and self._progress.get(plate["id"], 0) < 1 \
                else 0
            t += remain * self.real_factor + prep + c.plate_change_min * 60
            tags = self.db.q("SELECT id FROM tags WHERE plate_id=? AND status='plated'", plate["id"])
            done = {x["id"]: t - c.plate_change_min * 60 for x in tags}
        else:
            done = {}
            t += self.foreign_job_s()
        plates = self._pending_plates(probe)
        while plates:
            start = max(t, min(p["ready_at"] for p in plates))
            nxt = min((p for p in plates if p["ready_at"] <= start), key=lambda p: (p["first"], p["id"]))
            plates.remove(nxt)
            dur = (self.plate_overhead_s + sum(self.tag_estimate_s(x["area_mm2"]) for x in nxt["tags"])) \
                * self.real_factor + c.plate_prep_min * 60
            t = start + dur
            for x in nxt["tags"]:
                done[x["id"]] = t
            t += c.plate_change_min * 60
        return done

    def foreign_job_s(self) -> float:
        """Time until a job the booth did not start (e.g. a print sent from
        PrusaSlicer before the booth opened) is off the bed: the printer's own
        remaining time + the plate change. 0 when the printer is free."""
        st = self.last_status
        if self.db.active_plate() or st.state not in ("printing", "paused", "attention", "busy"):
            return 0.0
        if st.state == "busy" and not st.remaining_s:
            return 0.0                      # busy without a job (e.g. homing from the menu)
        return (st.remaining_s or 0) + self.cfg.plate_change_min * 60

    def eta_s(self, tag_ids: list[int] | None = None) -> float:
        """Time until the given tags (default: all queued) are printed."""
        f = self.forecast()
        vals = [f[i] for i in tag_ids if i in f] if tag_ids is not None else list(f.values())
        return max(vals, default=0.0)

    def public_status(self) -> dict:
        plate = self.db.active_plate()
        current = None
        if plate:
            names = [t["name"] for t in self.db.q("SELECT name FROM tags WHERE plate_id=? ORDER BY id", plate["id"])]
            current = {"id": plate["id"], "names": names, "status": plate["status"],
                       "remaining_min": round((self.last_status.remaining_s or 0) / 60)}
        st = self.last_status.state
        gate = self.ordering_state()
        return {"printer": st, "current_plate": current,
                "queue_length": self.open_tag_count(), "queue_full": self.queue_full(),
                "ordering": {"open": gate["open"], "reason": gate["reason"], "message": gate["message"]},
                "wait_min": gate["wait_min"] if gate["show_wait"] else None,
                "config_rev": self.config_rev, "kiosk_reset": self.kiosk_reset}

    # ------------------------------------------------------------ ordering gate
    def wait_estimate_s(self) -> float:
        """How long a child ordering now waits for one tag: a what-if tag on a
        new plate (worst case: no room on a plate of its colour), with the same
        safety margin as the pickup time (eta_factor, +2 min)."""
        avg = self.db.q1("SELECT AVG(area_mm2) AS a FROM (SELECT area_mm2 FROM tags ORDER BY id DESC LIMIT 50)")["a"]
        probe = {"id": -1, "area_mm2": avg or DEFAULT_TAG_AREA_MM2, "queued_at": self.clock()}
        return self.forecast(probe).get(-1, 0.0) * self.eta_factor + 120

    def _close_ts(self, hhmm: str) -> float:
        """Today's timestamp of HH:MM (local time of the booth computer)."""
        lt = time.localtime(self.clock())
        h, m = map(int, hhmm.split(":"))
        return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))

    def ordering_state(self) -> dict:
        """Staff controls + what follows from them: open? why not? wait time."""
        ctl = {**ORDERING_DEFAULT, **self.db.get_state("ordering", {})}
        wait_s = self.wait_estimate_s()
        wait_min = int(-(-wait_s // 300) * 5)                     # rounded up to 5 min
        reason, message, last_order = None, "", None
        if ctl["close_at"]:
            close = self._close_ts(ctl["close_at"])
            last_order = close - wait_s
            if self.clock() + wait_s > close:
                reason, message = "closing", CLOSING_MESSAGE
        if not ctl["open"]:
            reason = "manual"
            message = CLOSED_MESSAGES.get(ctl["message"], ctl["message"]) or CLOSED_MESSAGES["pause"]
        return {**ctl, "open": reason is None, "manual_open": ctl["open"], "reason": reason, "message": message,
                "wait_s": int(wait_s), "wait_min": wait_min,
                "last_order": time.strftime("%H:%M", time.localtime(last_order)) if last_order else None}

    def staff_set_ordering(self, d: dict) -> dict:
        """Partial update: open (bool), message (preset id or own text),
        close_at ('HH:MM' or null), show_wait (bool)."""
        ctl = {**ORDERING_DEFAULT, **self.db.get_state("ordering", {})}
        for k, v in d.items():
            if k in ("open", "show_wait"):
                if not isinstance(v, bool):
                    raise BoothError("bad_value", f"{k}: ja/nein erwartet")
            elif k == "message":
                if not isinstance(v, str) or len(v.strip()) > 120:
                    raise BoothError("bad_value", "Text: max. 120 Zeichen")
                v = v.strip()
            elif k == "close_at":
                if v in ("", None):
                    v = None
                elif not isinstance(v, str) or not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
                    raise BoothError("bad_value", "Uhrzeit als HH:MM")
            else:
                raise BoothError("bad_value", f"unbekannt: {k}")
            ctl[k] = v
        self.db.set_state("ordering", ctl)
        log.info("ordering: %s", ctl)
        return self.ordering_state()

    def staff_kiosk_reset(self) -> None:
        """Kiosk drops a half-finished order and shows the start screen."""
        self.kiosk_reset += 1

    # ------------------------------------------------------------ scheduler
    def _keep_out(self):
        return TOWER_KEEP_OUT if self.setup.color_change == "tower" else None

    def _fits(self, tags: list[dict]) -> bool:
        return not pack([(str(t["id"]), t["w_mm"], t["h_mm"]) for t in tags], keep_out=self._keep_out())[1]

    def plan(self) -> None:
        """Put unassigned queued tags on a waiting plate of their colour (oldest
        plate with room first, else a new one); drop empty waiting plates."""
        max_tags = self.cfg.plate_max_tags
        for t in self.db.queued_tags(unassigned=True):
            for pl in self.db.q("SELECT id FROM plates WHERE status='waiting' AND text_color=? ORDER BY id",
                                t["text_color"]):
                on = self.db.q("SELECT id, w_mm, h_mm FROM tags WHERE plate_id=? AND status='queued'", pl["id"])
                if len(on) < max_tags and self._fits(on + [t]):
                    self.db.assign(t["id"], pl["id"])
                    break
            else:
                self.db.assign(t["id"], self.db.new_plate(t["text_color"], self.clock()))
        with self.db.tx() as c:
            c.execute("UPDATE plates SET status='deleted' WHERE status='waiting' AND NOT EXISTS ("
                      "SELECT 1 FROM tags t WHERE t.plate_id=plates.id AND t.status='queued')")

    def tick(self) -> None:
        """One scheduler step; called every ~2 s by the loop thread."""
        with self.lock:
            st = self.printer.status()
            self.last_status = st
            self.plan()
            plate = self.db.active_plate()
            if not plate:
                return
            if plate["status"] == "building":
                self._start_plate(plate["id"])
            else:
                self._supervise(plate, st)

    def _supervise(self, plate: dict, st: PrinterStatus) -> None:
        pid, status = plate["id"], plate["status"]
        if pid in self._just_started:
            if st.state in ("printing", "attention", "paused", "busy") or \
                    self.clock() - (plate["started"] or 0) > START_GRACE_S:
                self._just_started.discard(pid)
            elif st.state == "finished":
                return              # still the FINISHED of the previous job (restart from FINISHED)
        if st.state in ("printing", "attention", "paused", "finished"):
            prog = 100.0 if st.state == "finished" else st.progress
            if int(prog) != int(self._progress.get(pid, -1)):
                self._progress = {pid: prog}                 # only the active plate matters
                self.db.set_state("plate_progress", self._progress)
        if st.state in ("attention", "paused"):
            if status != "color_change":
                self.db.plate_status(pid, "color_change")
            self._cc_since.setdefault(pid, self.clock())
        elif st.state == "printing" or st.state == "busy":
            if pid in self._cc_since:
                self._cc_wait[pid] = self._cc_wait.get(pid, 0.0) + self.clock() - self._cc_since.pop(pid)
            if status != "printing":
                self.db.plate_status(pid, "printing")
        elif st.state == "finished":
            now = self.clock()
            self.db.plate_status(pid, "done", finished=now)
            self._learn_eta(pid, now)
            if plate["started"] and plate["est_s"]:
                # printing time only: without the fixed prep and the wait at the colour change
                printed = now - plate["started"] - self.cfg.plate_prep_min * 60 - self._cc_wait.pop(pid, 0.0)
                f = printed / plate["est_s"]
                if 0.8 < f < 3:
                    self.real_factor = round(0.7 * self.real_factor + 0.3 * f, 3)
                    self.db.set_state("real_factor", self.real_factor)
        elif st.state == "idle" and self.clock() - (plate["started"] or 0) > START_GRACE_S:
            if self._progress.get(pid, 0) >= 99:
                # FINISHED was missed (backend down, or the end was confirmed on the
                # printer before we polled) - the plate is done, do not reprint it
                self.db.plate_status(pid, "done", finished=self.clock())
                log.info("plate %d: printer idle after %.0f %% - counted as done", pid, self._progress[pid])
            else:
                self.db.plate_status(pid, "failed", error="Druck am Drucker abgebrochen")
        elif st.state == "error":
            self.db.plate_status(pid, "failed", error=f"Druckerfehler: {st.message}")

    def _start_plate(self, pid: int) -> None:
        """Plate is 'building' (staff pressed start): pack + slice (or reuse the
        G-code of a restart) and send it to the printer."""
        plate = self.db.plate(pid)
        tags = [t for t in plate["tags"] if t["status"] == "plated"]
        d = self.data / "plates"
        try:
            gcode = Path(plate["gcode"]) if plate["gcode"] else None
            if gcode and gcode.exists() and plate["est_s"] and \
                    {m["tag_id"] for m in plate["map"]} == {t["id"] for t in tags}:
                est = plate["est_s"]                              # restart: same tags, same G-code
            else:
                stls = {str(t["id"]): Path(t["stl"]) for t in tags}
                placed, rest = build_plate(stls, d / f"plate_{pid:03d}.3mf", self.setup)
                res = slice_plate([d / f"plate_{pid:03d}.3mf"], d / f"plate_{pid:03d}.gcode", self.setup)
                pmap = [{"tag_id": int(p.key), "x": round(p.x, 1), "y": round(p.y, 1),
                         "w": round(float(p.w), 1), "h": round(float(p.h), 1)} for p in placed]
                self.db.plate_built(pid, pmap, [int(k) for k in rest], res.gcode, res.estimated_s)
                self._learn_time(res.estimated_s, [t for t in tags if str(t["id"]) not in rest])
                gcode, est = res.gcode, res.estimated_s
            self._progress.pop(pid, None)
            self._cc_since.pop(pid, None)
            self._cc_wait.pop(pid, None)
            self.printer.start(gcode, est)
            self._just_started.add(pid)
            self.db.plate_status(pid, "printing", started=self.clock(), finished=None, error=None)
            log.info("plate %d started: %s, %d tags, est %d min", pid, plate["text_color"], len(tags), est // 60)
        except Exception as e:                      # noqa: BLE001 - shown on the staff page
            log.exception("plate %d failed", pid)
            self.db.plate_status(pid, "failed", error=str(e)[:300])

    def _learn_eta(self, pid: int, now: float) -> None:
        """Orders completed by this plate: compare real wait with the forecast."""
        for o in self.db.q(
                "SELECT DISTINCT o.id, o.created, o.eta_raw FROM orders o JOIN tags t ON t.order_id=o.id "
                "WHERE t.plate_id=? AND o.eta_raw > 300 AND NOT EXISTS (SELECT 1 FROM tags x WHERE "
                "x.order_id=o.id AND x.status IN ('held','queued','plated'))", pid):
            f = (now - o["created"]) / o["eta_raw"]
            if 0.5 < f < 4:
                self.eta_factor = round(min(2.5, max(1.0, 0.85 * self.eta_factor + 0.15 * f)), 3)
        self.db.set_state("eta_factor", self.eta_factor)

    def _learn_time(self, est_s: int, tags: list[dict]) -> None:
        area = sum(t["area_mm2"] for t in tags)
        if area > 0 and est_s > self.plate_overhead_s:
            k = (est_s - self.plate_overhead_s) / area
            self.s_per_mm2 = round(0.7 * self.s_per_mm2 + 0.3 * k, 5)
            self.db.set_state("s_per_mm2", self.s_per_mm2)

    def run_forever(self, interval: float = 2.0) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
                self._maybe_backup()
            except Exception:                       # noqa: BLE001 - keep the loop alive
                log.exception("tick failed")
            self._stop.wait(interval)

    def start_loop(self) -> None:
        self._thread = threading.Thread(target=self.run_forever, name="scheduler", daemon=True)
        self._thread.start()

    def stop_loop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    # --------------------------------------------------------------- staff
    def _plate_view(self, pid: int, recommended: int | None) -> dict:
        p = self.db.plate(pid)
        live = [t for t in p["tags"] if t["status"] != "cancelled"]
        pmap = p["map"]
        if p["status"] == "waiting" or not pmap:                # not packed yet: same packing as the printer
            placed, _ = pack([(str(t["id"]), t["w_mm"], t["h_mm"]) for t in live], keep_out=self._keep_out())
            pmap = [{"tag_id": int(x.key), "x": round(x.x, 1), "y": round(x.y, 1), "w": x.w, "h": x.h}
                    for x in placed]
        state = {"waiting": "waiting", "failed": "error", "done": "done"}.get(p["status"], "printing")
        return {"id": pid, "state": state, "status": p["status"], "text_color": p["text_color"],
                "count": len(live), "max": self.cfg.plate_max_tags,
                "est_s": p["est_s"], "error": p["error"],
                "started": p["started"], "finished": p["finished"], "recommended": pid == recommended,
                "map": pmap,
                "tags": [{"id": t["id"], "name": t["name"], "order_number": t["order_number"],
                          "outline": t["outline"], "text": t["text_svg"], "reprint": bool(t["reprint"])}
                         for t in live]}

    def staff_overview(self) -> dict:
        orders = self.db.q("SELECT * FROM orders WHERE status='open' ORDER BY id")
        for o in orders:
            o["tags"] = self.db.q("SELECT t.id, t.idx, t.name, t.font, t.shape, t.text_color, t.free, t.status, "
                                  "t.plate_id FROM tags t WHERE order_id=? ORDER BY idx", o["id"])
            live = [t for t in o["tags"] if t["status"] != "cancelled"]
            o["ready"] = bool(live) and all(t["status"] == "printed" for t in live)
        rec = self.recommended_plate()
        rank = {"printing": 0, "error": 1, "waiting": 2, "done": 3}
        plates = [self._plate_view(p["id"], rec) for p in self.db.q(
            "SELECT id FROM plates WHERE status IN ('waiting','building','printing','color_change','failed','done') "
            "ORDER BY id")]
        plates.sort(key=lambda p: (rank[p["state"]], -p["id"] if p["state"] == "done" else p["id"]))
        st = self.last_status
        return {"printer": {"kind": self.printer.kind, "state": st.state, "progress": round(st.progress, 1),
                            "remaining_s": st.remaining_s, "message": st.message,
                            "foreign_job": self.foreign_job_s() > 0},
                "orders": orders, "plates": plates,
                "base_color": self.cfg.base_color, "text_colors": self.cfg.text_colors,
                "setup": self.setup.name, "eta_all_s": int(self.eta_s()), "today": self._day(),
                "ordering": self.ordering_state(), "closed_messages": CLOSED_MESSAGES,
                "server_time": time.time()}

    def staff_paid(self, oid: int) -> None:
        self.db.mark_paid(oid)

    def staff_pickup(self, oid: int) -> None:
        """Handed out at the stand; the money (if any) was taken then."""
        self.db.mark_paid(oid)
        self.db.order_done(oid, self.clock())

    def staff_cancel_tag(self, tid: int) -> None:
        t = self.db.q1("SELECT * FROM tags WHERE id=?", tid)
        if not t:
            raise BoothError("not_found")
        if t["status"] not in ("held", "queued"):
            raise BoothError("tag_on_plate", "tag is already printing or printed")
        with self.lock:
            self.db.cancel_tag(tid)
            n = self.db.q1("SELECT COUNT(*) AS n FROM tags WHERE order_id=? AND status!='cancelled'",
                           t["order_id"])["n"]
            self.db.set_order_price(t["order_id"], self.cfg.price_cents(n))
            if n == 0:
                self.db.cancel_order(t["order_id"])
            self.plan()

    def staff_reprint_tag(self, tid: int) -> None:
        """A printed tag came out badly: print it once more. It keeps its old
        queue time, so its plate is recommended right away."""
        with self.lock:
            t = self.db.q1("SELECT * FROM tags WHERE id=?", tid)
            if not t:
                raise BoothError("not_found")
            if t["status"] != "printed":
                raise BoothError("bad_state", "Nur fertige Anhänger können nochmal gedruckt werden")
            if not Path(t["stl"]).exists():
                raise BoothError("bad_state", "Druckdatei ist schon gelöscht (Tag abgeschlossen)")
            with self.db.tx() as c:
                c.execute("UPDATE tags SET status='queued', plate_id=NULL, reprint=1 WHERE id=?", (tid,))
                c.execute("UPDATE orders SET status='open', done_at=NULL WHERE id=? AND status='done'",
                          (t["order_id"],))
            self.plan()

    def staff_cancel_order(self, oid: int) -> None:
        with self.lock:
            self.db.cancel_order(oid)
            self.plan()

    def staff_handed_out(self, oid: int) -> None:
        self.db.order_done(oid, self.clock())

    def staff_plate_start(self, pid: int) -> None:
        """Start a waiting plate, or restart a failed/done one. Staff confirmed
        the bed is empty and the base colour is loaded."""
        with self.lock:
            p = self.db.q1("SELECT * FROM plates WHERE id=?", pid)
            if not p or p["status"] not in ("waiting", "failed", "done"):
                raise BoothError("bad_state", "Platte kann nicht gestartet werden")
            if not self.db.q1("SELECT 1 AS x FROM tags WHERE plate_id=? AND status IN ('queued','printed')", pid):
                raise BoothError("bad_state", "Keine Anhänger auf der Platte")
            if self.db.active_plate():
                raise BoothError("bad_state", "Es druckt schon eine Platte")
            st = self.printer.status()
            self.last_status = st
            if st.state not in ("idle", "finished"):
                raise BoothError("printer_busy", "Drucker ist nicht bereit")
            self.printer.acknowledge()
            self.db.plate_status(pid, "building", error=None)

    def staff_plate_delete(self, pid: int) -> None:
        """Remove a plate from the list. Unprinted tags go back to the queue
        (and onto a new plate); a running print is stopped."""
        with self.lock:
            p = self.db.q1("SELECT * FROM plates WHERE id=?", pid)
            if not p or p["status"] not in LISTED:
                raise BoothError("bad_state")
            if p["status"] == "done":
                self.db.plate_status(pid, "archived")
                return
            if p["status"] in ("building", "printing", "color_change"):
                self.printer.abort()
            self.db.plate_status(pid, "deleted", finished=self.clock())
            self.plan()

    def staff_sim_resume(self) -> None:
        if not isinstance(self.printer, SimPrinter):
            raise BoothError("not_sim")
        self.printer.resume()

    # ------------------------------------------------------------ settings
    SECRETS = ("api_key", "password")

    def staff_settings(self) -> dict:
        d = config_dict(self.cfg)
        d.pop("_comment")
        d["staff_pin"] = ""                                   # never sent out; empty = unchanged
        p = d["printer"] = dict(d["printer"])
        for k in self.SECRETS:
            p[f"has_{k}"] = bool(p.pop(k, ""))                # empty = unchanged
        active, setups = list_setups()
        in_use = {t["text_color"] for t in self.db.q(
            "SELECT DISTINCT text_color FROM tags WHERE status IN ('held','queued','plated')")}
        return {"settings": d,
                "fonts": [{"id": f.id, "label": f.label} for f in self.fonts.values()],
                "shapes": [{"id": s.id, "label": s.label["de"]} for s in self.shapes.values()],
                "setups": [{"name": n, "scale": e["scale"], "min_text_size": e["min_text_size"],
                            "profile": e["profile"], "default": n == active} for n, e in setups.items()],
                "current_setup": self.setup.name, "setup_locked": self.setup_locked,
                "pin_from_env": self.cfg.file_pin is not None,
                "open_tags": self.open_tag_count(), "plate_active": self.db.active_plate() is not None,
                "colors_in_use": sorted(in_use)}

    def _merge_settings(self, d: dict) -> dict:
        """Staff page dict -> full booth.json dict (secrets and PIN: empty = keep)."""
        d = {k: v for k, v in d.items() if k != "_comment"}
        p = dict(d.get("printer") or {})
        for k in self.SECRETS:
            p.pop(f"has_{k}", None)
            if not p.get(k):
                p[k] = self.cfg.printer.get(k, "")
        d["printer"] = p
        if not str(d.get("staff_pin") or "").strip():
            d["staff_pin"] = self.cfg.file_pin or self.cfg.staff_pin
        return d

    def staff_update_settings(self, d: dict) -> dict:
        try:
            new = parse_config(self._merge_settings(d))
        except ConfigError as e:
            raise BoothError("bad_config", str(e)) from None
        old = self.cfg
        if old.file_pin is not None:
            if new.staff_pin != old.file_pin:
                raise BoothError("bad_config", "PIN kommt aus BOOTH_PIN und kann hier nicht geändert werden")
            new.file_pin, new.staff_pin = old.file_pin, old.staff_pin
        if unknown := set(new.disabled_fonts) - set(self.fonts):
            raise BoothError("bad_config", f"unbekannte Schrift {sorted(unknown)}")
        if unknown := set(new.disabled_shapes) - set(self.shapes):
            raise BoothError("bad_config", f"unbekannte Form {sorted(unknown)}")
        if not set(self.fonts) - set(new.disabled_fonts) or not set(self.shapes) - set(new.disabled_shapes):
            raise BoothError("bad_config", "mindestens eine Schrift und eine Form muss an sein")
        with self.lock:
            removed = {c["id"] for c in old.text_colors} - {c["id"] for c in new.text_colors}
            in_use = removed & {t["text_color"] for t in self.db.q(
                "SELECT DISTINCT text_color FROM tags WHERE status IN ('held','queued','plated')")}
            if in_use:
                names = ", ".join(old.color(i)["name"] for i in sorted(in_use))
                raise BoothError("bad_config", f"Farbe {names} hat noch offene Anhänger – erst drucken oder stornieren")
            plate_active = self.db.active_plate() is not None
            setup = self.setup
            want = new.print_setup or list_setups()[0]
            if want != self.setup.name:
                if self.setup_locked:
                    raise BoothError("bad_config", "Druck-Setup ist per --setup festgelegt")
                if self.open_tag_count() or plate_active:
                    raise BoothError("bad_config", "Druck-Setup nur ändern, wenn keine Anhänger offen sind")
                try:
                    setup = load_setup(want)
                except (KeyError, ValueError) as e:
                    raise BoothError("bad_config", f"Druck-Setup {want}: {e}") from None
            printer = self.printer
            if new.printer != old.printer:
                if plate_active:
                    raise BoothError("bad_config", "Drucker erst ändern, wenn keine Platte läuft")
                printer = make_printer(new.printer)
            new.data_dir, new.path = old.data_dir, old.path
            save_config(new)
            if setup is not self.setup:
                self.setup = setup
                for pid in list(self.previews):
                    shutil.rmtree(self.previews.pop(pid).stl.parent, ignore_errors=True)
            self.cfg, self.printer = new, printer
            self.config_rev += 1
        log.info("settings saved (rev %d)", self.config_rev)
        return self.staff_settings()

    def staff_test_printer(self, p: dict) -> dict:
        """Status of a printer config without applying it."""
        p = self._merge_settings({"printer": p})["printer"]
        if p.get("type") == "prusalink" and not str(p.get("host", "")).strip():
            raise BoothError("bad_config", "Host/IP fehlt")
        pr = self.printer if p == self.cfg.printer else make_printer(p)
        st = pr.check() if hasattr(pr, "check") else pr.status()
        return {"state": st.state, "message": st.message}

    # ------------------------------------------------------------ day / stats
    def _day(self, t: float | None = None) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(self.clock() if t is None else t))

    def stats(self, day: str | None = None) -> dict:
        """Numbers for one day (default today): orders, tags, money, colours, waiting time."""
        day = day or self._day()
        q, q1 = self.db.q, self.db.q1
        orders = q1("SELECT COUNT(*) AS n, COALESCE(SUM(CASE WHEN paid=1 AND status!='cancelled' "
                    "THEN price_cents END), 0) AS paid_cents, "
                    "COALESCE(SUM(CASE WHEN paid=0 AND status='open' THEN price_cents END), 0) AS due_cents "
                    "FROM orders WHERE day=? AND status!='cancelled'", day)
        tags = {r["status"]: r["n"] for r in q(
            "SELECT t.status, COUNT(*) AS n FROM tags t JOIN orders o ON o.id=t.order_id WHERE o.day=? "
            "GROUP BY t.status", day)}
        by_color = {r["text_color"]: r["n"] for r in q(
            "SELECT t.text_color, COUNT(*) AS n FROM tags t JOIN orders o ON o.id=t.order_id "
            "WHERE o.day=? AND t.status='printed' GROUP BY t.text_color", day)}
        by_shape = {r["shape"]: r["n"] for r in q(
            "SELECT t.shape, COUNT(*) AS n FROM tags t JOIN orders o ON o.id=t.order_id "
            "WHERE o.day=? AND t.status!='cancelled' GROUP BY t.shape", day)}
        by_font = {r["font"]: r["n"] for r in q(
            "SELECT t.font, COUNT(*) AS n FROM tags t JOIN orders o ON o.id=t.order_id "
            "WHERE o.day=? AND t.status!='cancelled' GROUP BY t.font", day)}
        wait = q1("SELECT AVG(p.finished - t.queued_at) AS avg_s, MAX(p.finished - t.queued_at) AS max_s "
                  "FROM tags t JOIN orders o ON o.id=t.order_id JOIN plates p ON p.id=t.plate_id "
                  "WHERE o.day=? AND t.status='printed' AND p.finished IS NOT NULL", day)
        lo, hi = time.mktime(time.strptime(day, "%Y-%m-%d")), time.mktime(time.strptime(day, "%Y-%m-%d")) + 86400
        plates = {r["status"]: r["n"] for r in q(
            "SELECT status, COUNT(*) AS n FROM plates WHERE created>=? AND created<? GROUP BY status", lo, hi)}
        print_s = q1("SELECT COALESCE(SUM(finished - started), 0) AS s FROM plates "
                     "WHERE status IN ('printed','done','archived') AND created>=? AND created<?", lo, hi)["s"]
        return {"day": day, "orders": orders["n"], "paid_cents": orders["paid_cents"],
                "due_cents": orders["due_cents"],
                "tags_printed": tags.get("printed", 0),
                "tags_open": sum(tags.get(k, 0) for k in ("held", "queued", "plated")),
                "tags_cancelled": tags.get("cancelled", 0),
                "free_tags": q1("SELECT COUNT(*) AS n FROM tags t JOIN orders o ON o.id=t.order_id "
                                "WHERE o.day=? AND t.free=1 AND t.status!='cancelled'", day)["n"],
                "plates_done": plates.get("done", 0) + plates.get("printed", 0) + plates.get("archived", 0),
                "plates_failed": plates.get("failed", 0) + plates.get("cancelled", 0),
                "print_h": round(print_s / 3600, 1),
                "by_color": by_color, "by_shape": by_shape, "by_font": by_font,
                "wait_avg_min": round((wait["avg_s"] or 0) / 60), "wait_max_min": round((wait["max_s"] or 0) / 60)}

    def staff_stats(self) -> dict:
        days = [r["day"] for r in self.db.q("SELECT DISTINCT day FROM orders ORDER BY day DESC LIMIT 7")]
        today = self._day()
        return {"today": self.stats(today),
                "days": [self.stats(d) for d in days if d != today],
                "close_preview": self.close_day_preview(),
                "last_backup": self.db.get_state("last_backup"),
                "colors": self.cfg.text_colors}

    def close_day_preview(self) -> dict:
        """What 'Tag abschließen' would do."""
        q1 = self.db.q1
        return {
            "plate_active": self.db.active_plate() is not None,
            "orders_open": q1("SELECT COUNT(*) AS n FROM orders WHERE status='open'")["n"],
            "tags_unprinted": q1("SELECT COUNT(*) AS n FROM tags WHERE status IN ('held','queued')")["n"],
            "orders_unpaid": q1("SELECT COUNT(*) AS n FROM orders WHERE status='open' AND paid=0")["n"],
            "orders_waiting_pickup": q1(
                "SELECT COUNT(*) AS n FROM orders o WHERE status='open' AND NOT EXISTS (SELECT 1 FROM tags t "
                "WHERE t.order_id=o.id AND t.status IN ('held','queued','plated'))")["n"],
        }

    def staff_close_day(self) -> dict:
        """End of the booth day: unprinted tags are cancelled, all open orders
        closed (printed but not picked up -> done; they stay in the leftover box),
        files of finished work removed, a backup made. Pickup numbers restart
        with the next calendar day anyway."""
        with self.lock:
            if self.db.active_plate():
                raise BoothError("bad_state", "Erst die laufende Platte fertig drucken und abnehmen")
            now = self.clock()
            with self.db.tx() as c:
                c.execute("UPDATE tags SET status='cancelled' WHERE status IN ('held','queued')")
                c.execute("UPDATE plates SET status='deleted' WHERE status IN ('waiting','failed')")
                c.execute("UPDATE plates SET status='archived' WHERE status='done'")
                c.execute("UPDATE orders SET status='cancelled' WHERE status='open' AND NOT EXISTS ("
                          "SELECT 1 FROM tags t WHERE t.order_id=orders.id AND t.status!='cancelled')")
                c.execute("UPDATE orders SET status='done', done_at=? WHERE status='open'", (now,))
            removed = self.cleanup_files()
            path = self.backup(tag="close")
            self.db.set_state("day_closed", self._day())
        log.info("day closed: %d files removed, backup %s", removed, path)
        return {"removed_files": removed, "backup": str(path)}

    def cleanup_files(self) -> int:
        """Delete STL/3MF/G-code of finished or cancelled work."""
        n = 0
        for t in self.db.q("SELECT stl FROM tags WHERE status IN ('printed','cancelled')"):
            p = Path(t["stl"])
            if p.exists():
                p.unlink()
                n += 1
        for pl in self.db.q("SELECT id, gcode FROM plates WHERE status IN ('archived','deleted','cancelled')"):
            for f in (self.data / "plates").glob(f"plate_{pl['id']:03d}.*"):
                f.unlink()
                n += 1
        self._expire_previews()
        return n

    def backup(self, tag: str = "auto") -> Path:
        """Consistent SQLite copy to data/backups (+ $BOOTH_BACKUP_DIR, e.g. a USB stick)."""
        import os
        import sqlite3
        name = f"booth-{time.strftime('%Y%m%d-%H%M%S', time.localtime(self.clock()))}-{tag}.sqlite"
        dirs = [self.data / "backups"]
        if os.environ.get("BOOTH_BACKUP_DIR"):
            dirs.append(Path(os.environ["BOOTH_BACKUP_DIR"]))
        first = None
        for d in dirs:
            try:
                d.mkdir(parents=True, exist_ok=True)
                dst = sqlite3.connect(d / name)
                with self.db.lock:
                    self.db.con.backup(dst)
                dst.close()
                for old in sorted(d.glob("booth-*.sqlite"))[:-BACKUP_KEEP]:
                    old.unlink()
                first = first or d / name
            except OSError as e:
                log.warning("backup to %s failed: %s", d, e)
        self.db.set_state("last_backup", {"t": self.clock(), "file": name})
        return first

    def _maybe_backup(self) -> None:
        last = (self.db.get_state("last_backup") or {}).get("t", 0)
        if self.clock() - last >= BACKUP_EVERY_S:
            self.backup()

    def export_csv(self, day: str | None = None) -> str:
        import csv
        import io
        rows = self.db.q(
            "SELECT o.day, o.number, o.customer, o.status AS order_status, o.paid, o.price_cents, t.idx, t.name, t.font, "
            "t.shape, t.text_color, t.free, t.status AS tag_status, t.plate_id, "
            "datetime(o.created, 'unixepoch', 'localtime') AS created "
            "FROM tags t JOIN orders o ON o.id=t.order_id " + ("WHERE o.day=? " if day else "") +
            "ORDER BY o.id, t.idx", *([day] if day else []))
        out = io.StringIO()
        w = csv.writer(out, delimiter=";")
        w.writerow(["Tag", "Nummer", "Kunde", "Bestellung", "bezahlt", "Preis (EUR)", "Pos", "Name", "Schrift", "Form",
                    "Farbe", "gratis", "Status", "Platte", "Zeit"])
        for r in rows:
            w.writerow([r["day"], r["number"], r["customer"], r["order_status"], r["paid"],
                        f"{r['price_cents'] / 100:.2f}".replace(".", ","), r["idx"], r["name"], r["font"],
                        r["shape"], r["text_color"], r["free"], r["tag_status"], r["plate_id"] or "", r["created"]])
        return out.getvalue()

    def plate_gcode(self, pid: int) -> Path:
        p = self.db.plate(pid)
        if not p or not p["gcode"] or not Path(p["gcode"]).exists():
            raise BoothError("not_found")
        return Path(p["gcode"])
