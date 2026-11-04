"""Printer link. One interface, two implementations:

SimPrinter      - runs a plate in accelerated time, stops at the colour change
                  until resume() (staff page button or auto after a delay).
PrusaLinkPrinter- Core One over LAN, PrusaLink HTTP API v1 (upload + start,
                  status). NOT yet tested against a real printer.

States (PrinterStatus.state):
  offline   no connection
  idle      ready for a job
  printing
  attention waiting for the user (M600 filament change, errors that need a click)
  paused
  finished  job done, bed not yet cleared (PrusaLink keeps FINISHED until
            the next job / acknowledgement)
  busy      doing something else (homing, calibrating)
  error
"""
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class PrinterStatus:
    state: str
    progress: float = 0.0          # 0..100
    remaining_s: int | None = None
    message: str = ""


class Printer:
    kind = "base"

    def status(self) -> PrinterStatus:
        raise NotImplementedError

    def start(self, gcode: Path, est_s: int) -> None:
        """Upload `gcode` and start printing it."""
        raise NotImplementedError

    def acknowledge(self) -> None:
        """Called when staff confirmed the bed is cleared (finished -> idle)."""

    def abort(self) -> None:
        """Staff cancelled the plate. Real printers: staff stop it on the printer."""


class SimPrinter(Printer):
    """speed: simulated seconds per real second. Colour change at the M600
    line's position in the file (good enough as a time fraction)."""
    kind = "sim"

    def __init__(self, speed: float = 60.0, auto_resume_s: float | None = None, clock=time.monotonic):
        self.speed, self.auto_resume_s, self.clock = speed, auto_resume_s, clock
        self.job = None

    def start(self, gcode: Path, est_s: int) -> None:
        text = gcode.read_text()
        at = text.find("\nM600")
        frac = at / len(text) if at > 0 else None
        self.job = {"est": max(1, est_s), "done_s": 0.0, "last": self.clock(), "cc_frac": frac,
                    "waiting_since": None, "state": "printing", "name": gcode.name}

    def resume(self) -> None:
        if self.job and self.job["state"] == "attention":
            self.job["state"] = "printing"
            self.job["cc_frac"] = None
            self.job["last"] = self.clock()

    def acknowledge(self) -> None:
        if self.job and self.job["state"] == "finished":
            self.job = None

    def abort(self) -> None:
        self.job = None

    def status(self) -> PrinterStatus:
        j = self.job
        if not j:
            return PrinterStatus("idle")
        now = self.clock()
        if j["state"] == "printing":
            j["done_s"] += (now - j["last"]) * self.speed
            if j["cc_frac"] is not None and j["done_s"] >= j["cc_frac"] * j["est"]:
                j["done_s"] = j["cc_frac"] * j["est"]
                j["state"], j["waiting_since"] = "attention", now
            elif j["done_s"] >= j["est"]:
                j["done_s"], j["state"] = j["est"], "finished"
        elif j["state"] == "attention" and self.auto_resume_s is not None \
                and now - j["waiting_since"] >= self.auto_resume_s:
            self.resume()
        j["last"] = now
        msg = "Filamentwechsel (Sim)" if j["state"] == "attention" else ""
        return PrinterStatus(j["state"], 100.0 * j["done_s"] / j["est"],
                             int(j["est"] - j["done_s"]), msg)


_PL_STATES = {"IDLE": "idle", "READY": "idle", "PRINTING": "printing", "PAUSED": "paused",
              "ATTENTION": "attention", "FINISHED": "finished", "STOPPED": "idle", "BUSY": "busy",
              "ERROR": "error"}


class PrusaLinkPrinter(Printer):
    """PrusaLink API v1 (xBuddy firmware: MK4/Core One). Auth with X-Api-Key or
    HTTP digest (user 'maker' + password from the printer's network menu).
    Upload target is the printer's USB stick (storage 'usb'), so a stick must
    be plugged into the printer."""
    kind = "prusalink"

    def __init__(self, host: str, api_key: str = "", user: str = "maker", password: str = "",
                 storage: str = "usb", timeout: float = 5.0):
        headers = {"X-Api-Key": api_key} if api_key else {}
        auth = httpx.DigestAuth(user, password) if password and not api_key else None
        self.storage = storage
        self.http = httpx.Client(base_url=f"http://{host}", headers=headers, auth=auth, timeout=timeout)

    def status(self) -> PrinterStatus:
        try:
            r = self.http.get("/api/v1/status")
            r.raise_for_status()
            d = r.json()
        except (httpx.HTTPError, ValueError) as e:
            return PrinterStatus("offline", message=str(e)[:200])
        p, job = d.get("printer", {}), d.get("job") or {}
        state = _PL_STATES.get(str(p.get("state", "")).upper(), "busy")
        return PrinterStatus(state, float(job.get("progress") or 0), job.get("time_remaining"),
                             str(p.get("state", "")))

    def start(self, gcode: Path, est_s: int) -> None:
        name = gcode.name
        with open(gcode, "rb") as f:
            r = self.http.put(f"/api/v1/files/{self.storage}/{name}", content=f.read(), timeout=120,
                              headers={"Content-Type": "application/octet-stream",
                                       "Print-After-Upload": "?1", "Overwrite": "?1"})
        if r.status_code not in (200, 201, 204):
            raise RuntimeError(f"PrusaLink upload failed: HTTP {r.status_code} {r.text[:200]}")


def make_printer(cfg: dict) -> Printer:
    if cfg.get("type") == "prusalink":
        return PrusaLinkPrinter(cfg["host"], cfg.get("api_key", ""), cfg.get("user", "maker"),
                                cfg.get("password", ""), cfg.get("storage", "usb"))
    return SimPrinter(cfg.get("sim_speed", 60), cfg.get("sim_auto_resume_s"))
