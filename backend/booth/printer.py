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

    def __init__(self, speed: float = 60.0, auto_resume_s: float | None = None, clock=time.monotonic,
                 prep_s: float = 0.0):
        self.speed, self.auto_resume_s, self.clock = speed, auto_resume_s, clock
        self.prep_s = prep_s                  # heat-up/levelling before the estimated part (progress stays 0)
        self.job = None

    def start(self, gcode: Path, est_s: int) -> None:
        text = gcode.read_text()
        at = text.find("\nM600")
        frac = at / len(text) if at > 0 else None
        self.job = {"est": max(1, est_s), "done_s": -self.prep_s, "last": self.clock(), "cc_frac": frac,
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
        done = max(0.0, j["done_s"])
        return PrinterStatus(j["state"], 100.0 * done / j["est"], int(j["est"] - done), msg)


_PL_STATES = {"IDLE": "idle", "READY": "idle", "PRINTING": "printing", "PAUSED": "paused",
              "ATTENTION": "attention", "FINISHED": "finished", "STOPPED": "idle", "BUSY": "busy",
              "ERROR": "error"}


class PrinterNotReady(RuntimeError):
    """Upload/start refused; the message is meant for the staff page."""


class PrusaLinkPrinter(Printer):
    """PrusaLink API v1 (xBuddy firmware: MK4/Core One), checked against the
    official spec (Prusa-Link-Web spec/openapi.yaml) and booth/fakelink.py.
    Auth: HTTP digest with user 'maker' + password from the printer's
    network menu (spec default), or an X-Api-Key on older firmware.
    Upload target is the printer's USB stick (storage 'usb') - the Core One
    has no internal storage, so a stick must be plugged in."""
    kind = "prusalink"

    def __init__(self, host: str, api_key: str = "", user: str = "maker", password: str = "",
                 storage: str = "usb", timeout: float = 5.0):
        headers = {"X-Api-Key": api_key} if api_key else {}
        auth = httpx.DigestAuth(user, password) if password and not api_key else None
        self.storage = storage
        self.host = host
        self.http = httpx.Client(base_url=f"http://{host}", headers=headers, auth=auth, timeout=timeout)

    def _get(self, path: str) -> dict:
        r = self.http.get(path)
        if r.status_code == 401:
            raise PrinterNotReady("Zugangsdaten falsch (Benutzer/Passwort oder API-Key)")
        r.raise_for_status()
        return r.json() if r.content else {}

    def status(self) -> PrinterStatus:
        try:
            d = self._get("/api/v1/status")
        except PrinterNotReady as e:
            return PrinterStatus("offline", message=str(e))
        except httpx.TransportError as e:
            return PrinterStatus("offline", message=f"nicht erreichbar ({type(e).__name__})")
        except (httpx.HTTPError, ValueError) as e:
            return PrinterStatus("offline", message=str(e)[:200])
        p, job = d.get("printer", {}), d.get("job") or {}
        state = _PL_STATES.get(str(p.get("state", "")).upper(), "busy")
        return PrinterStatus(state, float(job.get("progress") or 0), job.get("time_remaining"),
                             str(p.get("state", "")))

    def check(self) -> PrinterStatus:
        """Status plus 'is the USB stick there' (connection test on the staff page)."""
        st = self.status()
        if st.state == "offline":
            return st
        try:
            lst = self._get("/api/v1/storage").get("storage_list", [])
        except (httpx.HTTPError, ValueError, PrinterNotReady):
            return st                                  # older firmware: no storage endpoint
        ok = [x for x in lst if x.get("available") and not x.get("read_only")
              and str(x.get("path", "")).strip("/") == self.storage]
        if not ok:
            st.message = f"Speicher '{self.storage}' fehlt - USB-Stick in den Drucker stecken!"
        else:
            st.message = f"{st.message}, USB ok".strip(", ")
        return st

    def start(self, gcode: Path, est_s: int) -> None:
        name = gcode.name
        try:
            r = self.http.put(f"/api/v1/files/{self.storage}/{name}", content=gcode.read_bytes(), timeout=180,
                              headers={"Content-Type": "application/octet-stream",
                                       "Print-After-Upload": "?1", "Overwrite": "?1"})
        except httpx.HTTPError as e:
            raise PrinterNotReady(f"Upload zum Drucker fehlgeschlagen ({type(e).__name__})") from None
        if r.status_code in (200, 201, 204):
            return
        if r.status_code == 409:
            raise PrinterNotReady("Drucker nicht bereit (409): am Drucker das Druckende bestätigen / "
                                  "laufenden Druck beenden, dann Weiter")
        if r.status_code == 404:
            raise PrinterNotReady(f"Speicher '{self.storage}' nicht gefunden (404): USB-Stick im Drucker?")
        if r.status_code == 401:
            raise PrinterNotReady("Zugangsdaten falsch (401)")
        raise PrinterNotReady(f"Upload fehlgeschlagen: HTTP {r.status_code} {r.text[:200]}")

    def abort(self) -> None:
        """Stop the running job on the printer (best effort)."""
        try:
            job = (self._get("/api/v1/status").get("job") or {}).get("id")
            if job is not None:
                self.http.delete(f"/api/v1/job/{job}")
        except (httpx.HTTPError, ValueError, PrinterNotReady):
            pass


def make_printer(cfg: dict) -> Printer:
    if cfg.get("type") == "prusalink":
        return PrusaLinkPrinter(cfg["host"], cfg.get("api_key", ""), cfg.get("user", "maker"),
                                cfg.get("password", ""), cfg.get("storage", "usb"))
    return SimPrinter(cfg.get("sim_speed", 60), cfg.get("sim_auto_resume_s"))
