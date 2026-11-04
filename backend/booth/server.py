"""HTTP API (FastAPI). Kiosk: /api/*, staff: /api/staff/* (PIN -> token).

Run:  backend/.venv/bin/python -m booth.server  (from backend/)
      --setup nozzle040s --port 8080 --data /data/nametag
"""
import argparse
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nametag import FONT_DIR, REPO

from .config import load_config
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

    @app.exception_handler(BoothError)
    async def booth_error(_, e: BoothError):
        return JSONResponse({"error": e.code, "message": str(e)}, status_code=409 if e.code in (
            "queue_full", "bad_state", "tag_on_plate") else 400)

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
    async def shape_icon(shape: str):
        return await run_in_threadpool(booth.shape_icon, shape)

    @app.post("/api/orders")
    def order(req: OrderReq):
        return booth.place_order([t.model_dump() for t in req.tags])

    # ---------------- staff
    @app.post("/api/staff/login")
    def login(req: Pin):
        if not secrets.compare_digest(req.pin, booth.cfg.staff_pin):
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
        ("tags", "cancel"): booth.staff_cancel_tag,
        ("plates", "cleared"): booth.staff_plate_cleared,
        ("plates", "cancel"): booth.staff_plate_cancel,
    }

    @app.post("/api/staff/{kind}/{item_id}/{action}", dependencies=[Depends(staff)])
    def staff_action(kind: str, item_id: int, action: str):
        fn = actions.get((kind, action))
        if not fn:
            raise HTTPException(404)
        fn(item_id)
        return {"ok": True}

    @app.post("/api/staff/start_now/{color}", dependencies=[Depends(staff)])
    def start_now(color: str):
        booth.staff_start_now(color)
        return {"ok": True}

    @app.post("/api/staff/pause/{on}", dependencies=[Depends(staff)])
    def pause(on: int):
        booth.staff_pause(bool(on))
        return {"ok": True}

    @app.post("/api/staff/sim/resume", dependencies=[Depends(staff)])
    def sim_resume():
        booth.staff_sim_resume()
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
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    import uvicorn
    booth = Booth(load_config(data_dir=a.data), setup_name=a.setup)
    uvicorn.run(create_app(booth), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
