"""SQLite storage: orders, tags, plates.

Tag status:   queued -> plated (its plate prints) -> printed;  any -> cancelled
              A queued tag is assigned to a waiting plate at once (plate_id set);
              unpaid tags are printed too, the customer pays at pickup.
              (held = old "wait for payment" state, migrated to queued)
Plate status: waiting (filling up, staff press start) -> building -> printing
              <-> color_change -> done; building/printing/color_change -> failed
              failed/done -> building again (restart)
              waiting/failed/printing -> deleted (tags back to the queue)
              done -> archived (deleted from the list or closed day; tags stay printed)
              (old: printed = done, cancelled = deleted)
Order status: open -> done (handed out) | cancelled
"""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    number INTEGER NOT NULL,          -- pickup number, counts per day
    day TEXT NOT NULL,
    created REAL NOT NULL,
    price_cents INTEGER NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open',
    done_at REAL,
    customer TEXT NOT NULL DEFAULT ''   -- who ordered (kiosk asks first)
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    idx INTEGER NOT NULL,             -- 1..n inside the order
    name TEXT NOT NULL,
    font TEXT NOT NULL,
    shape TEXT NOT NULL,
    text_color TEXT NOT NULL,
    free INTEGER NOT NULL,
    status TEXT NOT NULL,
    plate_id INTEGER REFERENCES plates(id),
    stl TEXT NOT NULL,
    area_mm2 REAL NOT NULL,
    w_mm REAL NOT NULL,
    h_mm REAL NOT NULL,
    created REAL NOT NULL,
    queued_at REAL
);
CREATE TABLE IF NOT EXISTS plates (
    id INTEGER PRIMARY KEY,
    text_color TEXT NOT NULL,
    status TEXT NOT NULL,
    created REAL NOT NULL,
    est_s INTEGER,
    gcode TEXT,
    map TEXT,                         -- JSON list of {tag_id, x, y, w, h}
    started REAL,
    finished REAL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS tags_status ON tags(status);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

ACTIVE_PLATE = ("building", "printing", "color_change")
LISTED_PLATE = ("waiting", "building", "printing", "color_change", "failed", "done")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript(SCHEMA)
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(orders)")}
        if "eta_raw" not in cols:                      # forecast at order time (s), for learning
            self.con.execute("ALTER TABLE orders ADD COLUMN eta_raw REAL")
        if "customer" not in cols:
            self.con.execute("ALTER TABLE orders ADD COLUMN customer TEXT NOT NULL DEFAULT ''")
        tcols = {r[1] for r in self.con.execute("PRAGMA table_info(tags)")}
        if "outline" not in tcols:                     # 2D shape (SVG path, mm) for the plate preview
            self.con.execute("ALTER TABLE tags ADD COLUMN outline TEXT NOT NULL DEFAULT ''")
            self.con.execute("ALTER TABLE tags ADD COLUMN text_svg TEXT NOT NULL DEFAULT ''")
        if "reprint" not in tcols:                     # printed once more (bad print): plate is urgent
            self.con.execute("ALTER TABLE tags ADD COLUMN reprint INTEGER NOT NULL DEFAULT 0")
        # pay at pickup (2026-11-12): unpaid tags are printed right away
        self.con.execute("UPDATE tags SET status='queued', queued_at=COALESCE(queued_at, created) "
                         "WHERE status='held'")
        self.con.execute("UPDATE plates SET status='done' WHERE status='printed'")
        # old failed plates gave their tags back to the queue: nothing left to restart
        self.con.execute("UPDATE plates SET status='deleted' WHERE status='failed' AND NOT EXISTS ("
                         "SELECT 1 FROM tags t WHERE t.plate_id=plates.id AND t.status IN ('queued','plated'))")
        self.lock = threading.RLock()

    @contextmanager
    def tx(self):
        with self.lock:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                yield self.con
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise

    def q(self, sql: str, *args) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]

    def q1(self, sql: str, *args) -> dict | None:
        rows = self.q(sql, *args)
        return rows[0] if rows else None

    # --- state (pause flag etc.) ---
    def get_state(self, key: str, default=None):
        r = self.q1("SELECT value FROM state WHERE key=?", key)
        return json.loads(r["value"]) if r else default

    def set_state(self, key: str, value) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO state(key, value) VALUES(?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value)))

    # --- orders ---
    def create_order(self, tags: list[dict], price_cents: int, free_tags: int, now: float | None = None,
                     customer: str = "") -> dict:
        """tags: dicts with name, font, shape, text_color, stl, area_mm2, w_mm, h_mm
        (+ outline, text_svg). All are queued at once; the first `free_tags` are free,
        the rest is paid at pickup."""
        now = now or time.time()
        day = time.strftime("%Y-%m-%d", time.localtime(now))
        paid = 1 if price_cents == 0 else 0
        with self.tx() as c:
            n = c.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM orders WHERE day=?", (day,)).fetchone()[0]
            oid = c.execute("INSERT INTO orders(number, day, created, price_cents, paid, customer)"
                            " VALUES(?,?,?,?,?,?)", (n, day, now, price_cents, paid, customer)).lastrowid
            for i, t in enumerate(tags, 1):
                free = i <= free_tags
                c.execute("INSERT INTO tags(order_id, idx, name, font, shape, text_color, free, status, stl,"
                          " area_mm2, w_mm, h_mm, created, queued_at, outline, text_svg)"
                          " VALUES(?,?,?,?,?,?,?,'queued',?,?,?,?,?,?,?,?)",
                          (oid, i, t["name"], t["font"], t["shape"], t["text_color"], int(free),
                           str(t["stl"]), t["area_mm2"], t["w_mm"], t["h_mm"], now, now,
                           t.get("outline", ""), t.get("text_svg", "")))
        return self.order(oid)

    def order(self, oid: int) -> dict | None:
        o = self.q1("SELECT * FROM orders WHERE id=?", oid)
        if o:
            o["tags"] = self.q("SELECT * FROM tags WHERE order_id=? ORDER BY idx", oid)
        return o

    def mark_paid(self, oid: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE orders SET paid=1 WHERE id=?", (oid,))

    def cancel_tag(self, tid: int) -> None:
        """Only tags not printing yet (leaves their waiting plate); the order
        price is recomputed by the caller."""
        with self.tx() as c:
            c.execute("UPDATE tags SET status='cancelled', plate_id=NULL WHERE id=? AND status IN ('held', 'queued')",
                      (tid,))

    def set_order_price(self, oid: int, price_cents: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE orders SET price_cents=? WHERE id=?", (price_cents, oid))
            if price_cents == 0:
                c.execute("UPDATE orders SET paid=1 WHERE id=?", (oid,))

    def cancel_order(self, oid: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE tags SET status='cancelled', plate_id=NULL WHERE order_id=? AND status IN "
                      "('held', 'queued')", (oid,))
            c.execute("UPDATE orders SET status='cancelled' WHERE id=?", (oid,))

    def order_done(self, oid: int, now: float | None = None) -> None:
        with self.tx() as c:
            c.execute("UPDATE orders SET status='done', done_at=? WHERE id=?", (now or time.time(), oid))

    # --- plates ---
    def active_plate(self) -> dict | None:
        return self.q1(f"SELECT * FROM plates WHERE status IN ({','.join('?' * len(ACTIVE_PLATE))}) "
                       "ORDER BY id LIMIT 1", *ACTIVE_PLATE)

    def queued_tags(self, color: str | None = None, unassigned: bool = False) -> list[dict]:
        where = "status='queued'" + (" AND plate_id IS NULL" if unassigned else "")
        if color:
            return self.q(f"SELECT * FROM tags WHERE {where} AND text_color=? ORDER BY queued_at, id", color)
        return self.q(f"SELECT * FROM tags WHERE {where} ORDER BY queued_at, id")

    def new_plate(self, color: str, now: float | None = None) -> int:
        with self.tx() as c:
            return c.execute("INSERT INTO plates(text_color, status, created) VALUES(?, 'waiting', ?)",
                             (color, now or time.time())).lastrowid

    def assign(self, tid: int, pid: int | None) -> None:
        with self.tx() as c:
            c.execute("UPDATE tags SET plate_id=? WHERE id=? AND status='queued'", (pid, tid))

    def plate_built(self, pid: int, placed: list[dict], unplaced: list[int], gcode: Path, est_s: int) -> None:
        with self.tx() as c:
            c.executemany("UPDATE tags SET status='queued', plate_id=NULL WHERE id=?", [(t,) for t in unplaced])
            c.execute("UPDATE plates SET map=?, gcode=?, est_s=? WHERE id=?",
                      (json.dumps(placed), str(gcode), est_s, pid))

    def plate_status(self, pid: int, status: str, **fields) -> None:
        """Moves the plate's (live) tags along: building -> plated, done -> printed,
        failed -> queued but kept on the plate, deleted -> queued and unassigned."""
        sets = ", ".join(f"{k}=?" for k in ("status", *fields))
        with self.tx() as c:
            c.execute(f"UPDATE plates SET {sets} WHERE id=?", (status, *fields.values(), pid))
            if status == "building":
                c.execute("UPDATE tags SET status='plated' WHERE plate_id=? AND status IN ('queued','printed')",
                          (pid,))
            elif status == "done":
                c.execute("UPDATE tags SET status='printed' WHERE plate_id=? AND status='plated'", (pid,))
            elif status == "failed":
                c.execute("UPDATE tags SET status='queued' WHERE plate_id=? AND status='plated'", (pid,))
            elif status == "deleted":
                c.execute("UPDATE tags SET status='queued', plate_id=NULL WHERE plate_id=? AND status IN "
                          "('plated','queued')", (pid,))

    def plate(self, pid: int) -> dict | None:
        p = self.q1("SELECT * FROM plates WHERE id=?", pid)
        if p:
            p["map"] = json.loads(p["map"]) if p["map"] else []
            p["tags"] = self.q("SELECT t.*, o.number AS order_number FROM tags t JOIN orders o ON o.id=t.order_id "
                               "WHERE t.plate_id=? ORDER BY t.id", pid)
        return p
