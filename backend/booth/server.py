"""HTTP API (FastAPI). Kiosk: /api/*, staff: /api/staff/* (PIN -> token).

Run:  backend/.venv/bin/python -m booth.server  (from backend/)
      --setup nozzle040s --port 8080 --data /data/nametag
"""
import argparse
import logging
import os
import re
import secrets
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nametag import FONT_DIR, REPO

from .config import CONFIG, load_config
from .service import Booth, BoothError

STATIC = Path(__file__).resolve().parent / "static"
KIOSK_DIST = REPO / "frontend" / "dist"


class NameFont(BaseModel):
    name: str = Field(max_length=40)
    font: str


class PreviewReq(NameFont):
    shape: str


class OrderItem(BaseModel):
    preview_id: str
    text_color: str


class OrderReq(BaseModel):
    tags: list[OrderItem]
    customer: str = Field(default="", max_length=40)


class Pin(BaseModel):
    pin: str


def create_app(booth: Booth, run_loop: bool = True) -> FastAPI:
    tokens: set[str] = set()

    @asynccontextmanager
    async def lifespan(app):
        if run_loop:
            booth.start_loop()
        yield
        booth.stop_loop()

    app = FastAPI(title="3DNameTagBooth", lifespan=lifespan)

    @app.middleware("http")
    async def no_stale_pages(request, call_next):
        """Staff page + kiosk index are not versioned: browsers must ask every time
        (ETag -> 304), else an update shows new HTML with old CSS. Hashed kiosk
        assets may stay cached."""
        resp = await call_next(request)
        path = request.url.path
        if path.startswith("/staff") or (path.startswith("/kiosk") and not path.startswith("/kiosk/assets/")):
            resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.exception_handler(BoothError)
    async def booth_error(_, e: BoothError):
        return JSONResponse({"error": e.code, "message": str(e)}, status_code=409 if e.code in (
            "queue_full", "bad_state", "tag_on_plate", "printer_busy") else 400)

    def staff(x_staff_token: str = Header(default=""), token: str = Query(default="")):
        t = x_staff_token or token
        if t not in tokens:
            raise HTTPException(401, "staff login required")

    # ---------------- kiosk
    @app.get("/api/config")
    def config():
        return booth.public_config()

    @app.get("/api/status")
    def status():
        return booth.public_status()

    @app.post("/api/fit")
    def fit(req: NameFont):
        return booth.fit(req.name, req.font)

    @app.post("/api/preview")
    async def preview(req: PreviewReq):
        p = await run_in_threadpool(booth.preview, req.name, req.font, req.shape)
        return {"preview_id": p.id, "name": p.name, "outline": p.outline, "text": p.text,
                "size_mm": [p.w_mm, p.h_mm], "estimated_min": round(booth.tag_estimate_s(p.area_mm2) / 60, 1)}

    @app.get("/api/shapes/{shape}/icon")
    async def shape_icon(shape: str, name: str = Query(default="", max_length=40), font: str = ""):
        return await run_in_threadpool(booth.shape_icon, shape, name, font)

    @app.post("/api/orders")
    def order(req: OrderReq):
        return booth.place_order([t.model_dump() for t in req.tags], req.customer)

    # ---------------- staff
    @app.post("/api/staff/login")
    def login(req: Pin):
        if not secrets.compare_digest(req.pin.encode(), booth.cfg.staff_pin.encode()):
            raise HTTPException(403, "wrong PIN")
        t = secrets.token_urlsafe(16)
        tokens.add(t)
        return {"token": t}

    @app.get("/api/staff/overview", dependencies=[Depends(staff)])
    def overview():
        return booth.staff_overview()

    actions = {
        ("orders", "paid"): booth.staff_paid,
        ("orders", "cancel"): booth.staff_cancel_order,
        ("orders", "handed_out"): booth.staff_handed_out,
        ("orders", "pickup"): booth.staff_pickup,
        ("tags", "cancel"): booth.staff_cancel_tag,
        ("tags", "reprint"): booth.staff_reprint_tag,
        ("plates", "start"): booth.staff_plate_start,
        ("plates", "delete"): booth.staff_plate_delete,
    }

    @app.post("/api/staff/{kind}/{item_id}/{action}", dependencies=[Depends(staff)])
    def staff_action(kind: str, item_id: int, action: str):
        fn = actions.get((kind, action))
        if not fn:
            raise HTTPException(404)
        fn(item_id)
        return {"ok": True}

    @app.post("/api/staff/sim/resume", dependencies=[Depends(staff)])
    def sim_resume():
        booth.staff_sim_resume()
        return {"ok": True}

    @app.get("/api/staff/settings", dependencies=[Depends(staff)])
    def get_settings():
        return booth.staff_settings()

    @app.put("/api/staff/settings", dependencies=[Depends(staff)])
    def put_settings(req: dict = Body(...)):
        return booth.staff_update_settings(req)

    @app.post("/api/staff/printer/test", dependencies=[Depends(staff)])
    async def test_printer(req: dict = Body(...)):
        return await run_in_threadpool(booth.staff_test_printer, req)

    @app.get("/api/staff/stats", dependencies=[Depends(staff)])
    def stats():
        return booth.staff_stats()

    @app.post("/api/staff/close_day", dependencies=[Depends(staff)])
    def close_day():
        return booth.staff_close_day()

    @app.post("/api/staff/backup", dependencies=[Depends(staff)])
    def backup_now():
        return {"file": str(booth.backup(tag="manual"))}

    @app.get("/api/staff/export.csv", dependencies=[Depends(staff)])
    def export(day: str = Query(default="")):
        if day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise HTTPException(400, "day: YYYY-MM-DD")
        name = f"namensanhaenger-{day or 'alle'}.csv"
        return Response("\ufeff" + booth.export_csv(day or None), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ---------------- system (Pi only: BOOTH_ALLOW_SYSTEM=1, sudoers rule from deploy/pi/install.sh)
    allow_system = os.environ.get("BOOTH_ALLOW_SYSTEM") == "1"

    @app.get("/api/staff/system", dependencies=[Depends(staff)])
    def system_info():
        return {"allowed": allow_system, "time": time.time()}

    @app.post("/api/staff/system/time", dependencies=[Depends(staff)])
    def set_time(req: dict = Body(...)):
        if not allow_system:
            raise HTTPException(403, "not allowed on this machine")
        t = req.get("time")
        if not isinstance(t, (int, float)) or not 1.7e9 < t < 4e9:
            raise HTTPException(400, "time: unix seconds")
        r = subprocess.run(["sudo", "-n", "/usr/bin/date", "-s", f"@{int(t)}"], capture_output=True, text=True)
        if r.returncode:
            raise HTTPException(500, f"date failed: {r.stderr.strip()[:200]}")
        subprocess.run(["sudo", "-n", "/usr/sbin/hwclock", "-w"], capture_output=True)   # keep it in the RTC
        return {"time": time.time()}

    @app.post("/api/staff/system/{action}", dependencies=[Depends(staff)])
    def power(action: str):
        if not allow_system:
            raise HTTPException(403, "not allowed on this machine")
        if action not in ("poweroff", "reboot"):
            raise HTTPException(404)
        booth.backup(tag=action)
        subprocess.Popen(["sudo", "-n", "/usr/bin/systemctl", action])
        return {"ok": True}

    @app.get("/api/staff/plates/{pid}/gcode", dependencies=[Depends(staff)])
    def gcode(pid: int):
        p = booth.plate_gcode(pid)
        return FileResponse(p, filename=p.name, media_type="text/x.gcode")

    # ---------------- static
    app.mount("/fonts", StaticFiles(directory=FONT_DIR / "woff2"), name="fonts")
    app.mount("/staff", StaticFiles(directory=STATIC / "staff", html=True), name="staff")
    if KIOSK_DIST.exists():
        app.mount("/kiosk", StaticFiles(directory=KIOSK_DIST, html=True), name="kiosk")

    @app.get("/")
    def root():
        return RedirectResponse("/kiosk/" if KIOSK_DIST.exists() else "/staff/")

    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--setup", help="print setup from config/print.json (default: active)")
    ap.add_argument("--data", type=Path, default=os.environ.get("BOOTH_DATA"))
    ap.add_argument("--config", type=Path, default=os.environ.get("BOOTH_CONFIG") or CONFIG,
                    help="booth.json (default config/booth.json)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)   # printer poll every 2 s: ~43k lines/day
    import uvicorn
    booth = Booth(load_config(a.config, data_dir=a.data), setup_name=a.setup)
    uvicorn.run(create_app(booth), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
