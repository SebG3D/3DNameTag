"""Booth service: previews, orders, plate scheduling, printer supervision.

The HTTP layer (server.py) is a thin wrapper around this class, so the whole
flow can be tested without HTTP and with a simulated printer.

Plate policy: tags are grouped by text colour. A colour gets a plate when it
has plate_max_tags tags waiting, when its oldest tag waited plate_max_wait_min,
or when staff press "start now". The colour with the oldest waiting tag wins.
After a plate the printer holds the TEXT colour, so staff confirm "bed cleared
and base colour loaded" before the next plate starts.
"""
import json
import logging
import re
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from nametag.fonts import load_fonts
from nametag.names import NAME_MAX, clean_name
from nametag.plate import build_plate
from nametag.render import layout, render_svg, render_tag
from nametag.setup import list_setups, load_setup
from nametag.shapes import load_shapes
from nametag.slicer import slice_plate

from .config import BoothConfig, ConfigError, config_dict, parse_config, save_config
from .db import DB
from .printer import Printer, PrinterStatus, SimPrinter, make_printer

log = logging.getLogger("booth")

PREVIEW_TTL_S = 600
ICON_NAME, ICON_FONT = "EMMA", "baloo"
START_GRACE_S = 90          # printer may report idle this long after upload
# Time model, refined after every sliced plate (est = overhead + area * k).
DEFAULT_PLATE_OVERHEAD_S = 35        # fitted to PrusaSlicer estimates, nozzle040s (2026-11-04)
DEFAULT_S_PER_MM2 = 0.157


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
        self.fonts, self.shapes = load_fonts(), load_shapes()
        self.data = cfg.data_dir
        for d in ("previews", "tags", "plates"):
            (self.data / d).mkdir(parents=True, exist_ok=True)
        self.db = DB(self.data / "booth.sqlite")
        self.printer = printer or make_printer(cfg.printer)
        self.previews: dict[str, Preview] = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="render")
        self.lock = threading.RLock()            # scheduler vs. staff actions
        self.last_status = PrinterStatus("offline", message="not polled yet")
        self.plate_overhead_s = self.db.get_state("plate_overhead_s", DEFAULT_PLATE_OVERHEAD_S)
        self.s_per_mm2 = self.db.get_state("s_per_mm2", DEFAULT_S_PER_MM2)
        # real plate duration / slicer estimate (heating, M600 wait), learned
        self.real_factor = self.db.get_state("real_factor", 1.2)
        self._stop = threading.Event()
        self._thread = None
        self._recover()

    # ------------------------------------------------------------------ setup
    def _recover(self) -> None:
        """A plate that was being built when the backend stopped is redone."""
        for p in self.db.q("SELECT id FROM plates WHERE status='building'"):
            self.db.plate_status(p["id"], "failed", error="backend restart while building")

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

    def shape_icon(self, shape: str) -> dict:
        """Outline + sample text of a shape for the kiosk shape picker.
        Rendered once (2D only) and cached in the data dir; delete
        data/icons/ after changing a shape."""
        if shape not in self.shapes:
            raise BoothError("bad_shape")
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

    def place_order(self, items: list[dict]) -> dict:
        """items: [{preview_id, text_color}]"""
        if not 1 <= len(items) <= self.cfg.max_tags_per_order:
            raise BoothError("bad_count")
        if self.queue_full():
            raise BoothError("queue_full")
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
                         "area_mm2": p.area_mm2, "w_mm": p.w_mm, "h_mm": p.h_mm})
        for p, _ in previews:
            self.previews.pop(p.id, None)
            shutil.rmtree(p.stl.parent, ignore_errors=True)
        price = self.cfg.price_cents(len(tags))
        order = self.db.create_order(tags, price, self.cfg.free_tags, self.clock())
        eta = self.clock() + self.eta_s()
        return {"order_id": order["id"], "number": order["number"], "tags": len(tags),
                "price_cents": price, "needs_payment": price > 0,
                "eta": time.strftime("%H:%M", time.localtime(eta)), "eta_s": int(eta - self.clock())}

    def eta_s(self) -> float:
        """Rough time until everything open now is printed (incl. staff changes)."""
        c = self.cfg
        t = 0.0
        plate = self.db.active_plate()
        if plate:
            st = self.last_status
            remain = st.remaining_s if st.remaining_s is not None and plate["status"] != "building" \
                else (plate["est_s"] or 0)
            t += remain + c.plate_change_min * 60
        waiting = self.db.q("SELECT area_mm2 FROM tags WHERE status IN ('queued','held')")
        if waiting:
            plates = -(-len(waiting) // c.plate_max_tags)
            slicer = sum(self.tag_estimate_s(w["area_mm2"]) for w in waiting) + plates * self.plate_overhead_s
            t += slicer * self.real_factor + plates * c.plate_change_min * 60
        return t

    def public_status(self) -> dict:
        plate = self.db.active_plate()
        current = None
        if plate:
            names = [t["name"] for t in self.db.q("SELECT name FROM tags WHERE plate_id=? ORDER BY id", plate["id"])]
            current = {"id": plate["id"], "names": names, "status": plate["status"],
                       "remaining_min": round((self.last_status.remaining_s or 0) / 60)}
        st = self.last_status.state
        return {"printer": st, "current_plate": current,
                "queue_length": self.open_tag_count(), "queue_full": self.queue_full(),
                "paused": bool(self.db.get_state("paused", False)), "config_rev": self.config_rev}

    # ------------------------------------------------------------ scheduler
    def pick_next(self, force_color: str | None = None) -> tuple[str, list[dict]] | None:
        now, c = self.clock(), self.cfg
        groups: dict[str, list[dict]] = {}
        for t in self.db.queued_tags():
            groups.setdefault(t["text_color"], []).append(t)
        if force_color:
            return (force_color, groups[force_color][:c.plate_max_tags]) if force_color in groups else None
        ready = [(tags[0]["queued_at"], color) for color, tags in groups.items()
                 if len(tags) >= c.plate_max_tags or now - tags[0]["queued_at"] >= c.plate_max_wait_min * 60]
        if not ready:
            return None
        color = min(ready)[1]
        return color, groups[color][:c.plate_max_tags]

    def tick(self) -> None:
        """One scheduler step; called every ~2 s by the loop thread."""
        with self.lock:
            st = self.printer.status()
            self.last_status = st
            plate = self.db.active_plate()
            if plate:
                self._supervise(plate, st)
                return
            if self.db.get_state("paused", False) or st.state not in ("idle", "finished"):
                return
            force = self.db.get_state("force_color")
            nxt = self.pick_next(force)
            if force:
                self.db.set_state("force_color", None)
            if nxt:
                self._start_plate(*nxt)

    def _supervise(self, plate: dict, st: PrinterStatus) -> None:
        pid, status = plate["id"], plate["status"]
        if status not in ("printing", "color_change"):
            return                                   # printed: waits for staff
        if st.state in ("attention", "paused"):
            if status != "color_change":
                self.db.plate_status(pid, "color_change")
        elif st.state == "printing" or st.state == "busy":
            if status != "printing":
                self.db.plate_status(pid, "printing")
        elif st.state == "finished":
            now = self.clock()
            self.db.plate_status(pid, "printed", finished=now)
            if plate["started"] and plate["est_s"]:
                f = (now - plate["started"]) / plate["est_s"]
                if 0.8 < f < 3:
                    self.real_factor = round(0.7 * self.real_factor + 0.3 * f, 3)
                    self.db.set_state("real_factor", self.real_factor)
        elif st.state == "idle" and self.clock() - (plate["started"] or 0) > START_GRACE_S:
            self.db.plate_status(pid, "failed", error="printer idle - print aborted on the printer?")
            self._pause("plate failed")
        elif st.state == "error":
            self.db.plate_status(pid, "failed", error=f"printer error: {st.message}")
            self._pause("printer error")

    def _pause(self, reason: str) -> None:
        self.db.set_state("paused", True)
        self.db.set_state("pause_reason", reason)
        log.warning("queue paused: %s", reason)

    def _start_plate(self, color: str, tags: list[dict]) -> None:
        pid = self.db.create_plate(color, [t["id"] for t in tags], self.clock())
        d = self.data / "plates"
        try:
            stls = {str(t["id"]): Path(t["stl"]) for t in tags}
            placed, rest = build_plate(stls, d / f"plate_{pid:03d}.3mf", self.setup)
            res = slice_plate([d / f"plate_{pid:03d}.3mf"], d / f"plate_{pid:03d}.gcode", self.setup)
            pmap = [{"tag_id": int(p.key), "x": round(p.x, 1), "y": round(p.y, 1),
                     "w": round(float(p.w), 1), "h": round(float(p.h), 1)} for p in placed]
            self.db.plate_built(pid, pmap, [int(k) for k in rest], res.gcode, res.estimated_s)
            self._learn_time(res.estimated_s, [t for t in tags if str(t["id"]) not in rest])
            self.printer.start(res.gcode, res.estimated_s)
            self.db.plate_status(pid, "printing", started=self.clock())
            log.info("plate %d started: %s, %d tags, est %d min", pid, color, len(placed), res.estimated_s // 60)
        except Exception as e:                      # noqa: BLE001 - shown on the staff page
            log.exception("plate %d failed", pid)
            self.db.plate_status(pid, "failed", error=str(e)[:500])
            self._pause("plate failed")

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
    def staff_overview(self) -> dict:
        orders = self.db.q("SELECT * FROM orders WHERE status='open' ORDER BY id")
        for o in orders:
            o["tags"] = self.db.q("SELECT id, idx, name, font, shape, text_color, free, status, plate_id "
                                  "FROM tags WHERE order_id=? ORDER BY idx", o["id"])
            live = [t for t in o["tags"] if t["status"] != "cancelled"]
            o["ready"] = bool(live) and all(t["status"] == "printed" for t in live)
        plates = [self.db.plate(p["id"]) for p in
                  self.db.q("SELECT id FROM plates ORDER BY id DESC LIMIT 8")]
        waiting = {}
        for t in self.db.queued_tags():
            waiting.setdefault(t["text_color"], 0)
            waiting[t["text_color"]] += 1
        st = self.last_status
        return {"printer": {"kind": self.printer.kind, "state": st.state, "progress": round(st.progress, 1),
                            "remaining_s": st.remaining_s, "message": st.message},
                "paused": bool(self.db.get_state("paused", False)),
                "pause_reason": self.db.get_state("pause_reason", ""),
                "orders": orders, "plates": plates, "waiting_by_color": waiting,
                "held": self.db.q1("SELECT COUNT(*) AS n FROM tags WHERE status='held'")["n"],
                "base_color": self.cfg.base_color, "text_colors": self.cfg.text_colors,
                "setup": self.setup.name, "eta_all_s": int(self.eta_s())}

    def staff_paid(self, oid: int) -> None:
        self.db.mark_paid(oid, self.clock())

    def staff_cancel_tag(self, tid: int) -> None:
        t = self.db.q1("SELECT * FROM tags WHERE id=?", tid)
        if not t:
            raise BoothError("not_found")
        if t["status"] not in ("held", "queued"):
            raise BoothError("tag_on_plate", "tag is already on a plate")
        self.db.cancel_tag(tid)
        n = self.db.q1("SELECT COUNT(*) AS n FROM tags WHERE order_id=? AND status!='cancelled'",
                       t["order_id"])["n"]
        self.db.set_order_price(t["order_id"], self.cfg.price_cents(n))
        if n == 0:
            self.db.cancel_order(t["order_id"])

    def staff_cancel_order(self, oid: int) -> None:
        self.db.cancel_order(oid)

    def staff_handed_out(self, oid: int) -> None:
        self.db.order_done(oid, self.clock())

    def staff_plate_cleared(self, pid: int) -> None:
        with self.lock:
            p = self.db.plate(pid)
            if not p or p["status"] != "printed":
                raise BoothError("bad_state", "plate is not printed")
            self.db.plate_status(pid, "done")
            self.printer.acknowledge()

    def staff_plate_cancel(self, pid: int) -> None:
        """Plate failed/aborted: its tags go back to the queue. Stop the print
        on the printer itself."""
        with self.lock:
            p = self.db.plate(pid)
            if not p or p["status"] not in ("building", "printing", "color_change", "printed"):
                raise BoothError("bad_state")
            self.db.plate_status(pid, "cancelled", finished=self.clock())
            self.printer.abort()

    def staff_start_now(self, color: str) -> None:
        if color not in {c["id"] for c in self.cfg.text_colors}:
            raise BoothError("bad_color")
        self.db.set_state("force_color", color)

    def staff_pause(self, paused: bool) -> None:
        self.db.set_state("paused", paused)
        if not paused:
            self.db.set_state("pause_reason", "")

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
        if p == self.cfg.printer:
            st = self.printer.status()
        else:
            st = make_printer(p).status()
        return {"state": st.state, "message": st.message}

    def plate_gcode(self, pid: int) -> Path:
        p = self.db.plate(pid)
        if not p or not p["gcode"] or not Path(p["gcode"]).exists():
            raise BoothError("not_found")
        return Path(p["gcode"])
