"""Fake PrusaLink printer (Core One / xBuddy behaviour) for tests and dry runs.

Implements the parts of PrusaLink API v1 the booth uses, following the
official spec (github.com/prusa3d/Prusa-Link-Web, spec/openapi.yaml):

  GET  /api/v1/status                  printer.state, job.id/progress/time_remaining
  GET  /api/v1/storage                 storage_list (USB only, like the Core One)
  PUT  /api/v1/files/usb/<name>        upload, Print-After-Upload: ?1 starts it (201)
  DELETE /api/v1/job/<id>              stop

Auth: HTTP Digest (user + password, MD5, qop=auth) or X-Api-Key.

Behaviour: upload while not IDLE/READY/FINISHED/STOPPED -> 409. A print runs
`duration_s` real seconds, stops in ATTENTION at the M600 line (by file
position) until /fake/resume, ends in FINISHED, which stays until /fake/tap
(the user confirms on the printer screen) -> IDLE.

Control (no auth): POST /fake/resume | /fake/tap | /fake/abort | /fake/offline/<0|1>
| /fake/no_usb/<0|1> | /fake/error/<0|1>,  GET /fake/state

Run:  python -m booth.fakelink --port 8081 --password secret --duration 120
then set the booth printer to prusalink, host 127.0.0.1:8081, user maker.
"""
import argparse
import hashlib
import json
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REALM = "Printer API"


def _md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


class FakePrinter:
    def __init__(self, user="maker", password="", api_key="", duration_s=60.0, clock=time.monotonic):
        self.user, self.password, self.api_key = user, password, api_key
        self.duration_s, self.clock = duration_s, clock
        self.lock = threading.Lock()
        self.state = "IDLE"
        self.job = None              # dict(id, name, start, done, cc_frac, last)
        self.job_counter = 100
        self.files: dict[str, bytes] = {}
        self.offline = self.no_usb = False
        self.nonces: set[str] = set()
        self.log: list[str] = []

    # ---- simulation
    def _advance(self):
        j = self.job
        if not j or self.state != "PRINTING":
            return
        now = self.clock()
        j["done"] += now - j["last"]
        j["last"] = now
        if j["cc_frac"] is not None and j["done"] >= j["cc_frac"] * self.duration_s:
            j["done"] = j["cc_frac"] * self.duration_s
            j["cc_frac"] = None
            self.state = "ATTENTION"
        elif j["done"] >= self.duration_s:
            j["done"] = self.duration_s
            self.state = "FINISHED"

    def status(self) -> dict:
        with self.lock:
            self._advance()
            d = {"printer": {"state": self.state, "temp_nozzle": 215.0, "temp_bed": 60.0}}
            if self.job and self.state in ("PRINTING", "ATTENTION", "PAUSED", "FINISHED"):
                j = self.job
                d["job"] = {"id": j["id"], "progress": round(100 * j["done"] / self.duration_s, 1),
                            "time_remaining": int(self.duration_s - j["done"]), "time_printing": int(j["done"])}
            if not self.no_usb:
                d["storage"] = {"path": "/usb/", "name": "usb", "read_only": False}
            return d

    def upload(self, name: str, data: bytes, print_after: bool, overwrite: bool) -> int:
        with self.lock:
            self._advance()
            if self.no_usb:
                return 404
            if name in self.files and not overwrite:
                return 409
            if print_after and self.state not in ("IDLE", "READY", "FINISHED", "STOPPED"):
                return 409
            self.files[name] = data
            self.log.append(f"upload {name} {len(data)}")
            if print_after:
                text = data.decode(errors="replace")
                at = text.find("\nM600")
                self.job_counter += 1
                self.job = {"id": self.job_counter, "name": name, "done": 0.0, "last": self.clock(),
                            "cc_frac": at / len(text) if at > 0 else None}
                self.state = "PRINTING"
            return 201

    def resume(self):
        with self.lock:
            self._advance()
            if self.state == "ATTENTION":
                self.state = "PRINTING"
                self.job["last"] = self.clock()

    def tap(self):
        """User confirms the finished/stopped print on the printer screen."""
        with self.lock:
            self._advance()
            if self.state in ("FINISHED", "STOPPED"):
                self.state, self.job = "IDLE", None

    def stop(self, job_id: int | None = None) -> int:
        with self.lock:
            if not self.job or (job_id is not None and job_id != self.job["id"]):
                return 404
            self.state = "STOPPED"
            return 204

    # ---- auth
    def check_auth(self, headers) -> bool:
        if self.api_key and headers.get("X-Api-Key") == self.api_key:
            return True
        h = headers.get("Authorization", "")
        if not self.password or not h.startswith("Digest "):
            return False
        f = dict(re.findall(r'(\w+)="?([^",]*)"?', h[7:]))
        if f.get("username") != self.user or f.get("nonce") not in self.nonces:
            return False
        ha1 = _md5(f"{self.user}:{REALM}:{self.password}")
        ha2 = _md5(f"{headers['_method']}:{f.get('uri', '')}")
        if f.get("qop"):
            want = _md5(f"{ha1}:{f['nonce']}:{f.get('nc', '')}:{f.get('cnonce', '')}:{f['qop']}:{ha2}")
        else:
            want = _md5(f"{ha1}:{f['nonce']}:{ha2}")
        return secrets.compare_digest(want, f.get("response", ""))

    def challenge(self) -> str:
        n = secrets.token_hex(16)
        self.nonces.add(n)
        return f'Digest realm="{REALM}", nonce="{n}", qop="auth", algorithm=MD5'


def make_handler(fake: FakePrinter):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: dict | None = None, headers: dict | None = None):
            data = json.dumps(body).encode() if body is not None else b""
            self.send_response(code)
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if body is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _fake(self) -> bool:
            p = self.path.strip("/").split("/")
            if p[0] != "fake":
                return False
            if p[1:] == ["state"]:
                self._send(200, {"state": fake.state, "files": sorted(fake.files), "log": fake.log})
            elif p[1] in ("resume", "tap"):
                getattr(fake, p[1])()
                self._send(204)
            elif p[1] == "abort":
                self._send(fake.stop())
            elif p[1] in ("offline", "no_usb") and len(p) == 3:
                setattr(fake, p[1], p[2] == "1")
                self._send(204)
            elif p[1] == "error" and len(p) == 3:
                fake.state = "ERROR" if p[2] == "1" else "IDLE"
                self._send(204)
            else:
                self._send(404, {"title": "unknown fake command"})
            return True

        def _api(self, method: str):
            if self._fake():
                return
            if fake.offline:                       # like a printer that dropped off the network
                self.close_connection = True
                self.connection.close()
                return
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(n) if n else b""
            hdr = {k: v for k, v in self.headers.items()} | {"_method": method}
            if not fake.check_auth(hdr):
                return self._send(401, {"title": "Unauthorized"}, {"WWW-Authenticate": fake.challenge()})
            path = self.path.split("?")[0]
            if method == "GET" and path == "/api/v1/status":
                return self._send(200, fake.status())
            if method == "GET" and path == "/api/v1/storage":
                lst = [] if fake.no_usb else [{"name": "USB", "type": "USB", "path": "/usb",
                                               "available": True, "read_only": False}]
                return self._send(200, {"storage_list": lst})
            if method == "PUT" and path.startswith("/api/v1/files/"):
                storage, _, name = path[len("/api/v1/files/"):].partition("/")
                if storage != "usb":
                    return self._send(404, {"title": "Not Found", "message": f"storage {storage}"})
                code = fake.upload(name, body, self.headers.get("Print-After-Upload") == "?1",
                                   self.headers.get("Overwrite") == "?1")
                return self._send(code, None if code == 201 else {"title": "Conflict" if code == 409 else "Not Found"})
            m = re.fullmatch(r"/api/v1/job/(\d+)", path)
            if method == "DELETE" and m:
                return self._send(fake.stop(int(m[1])))
            self._send(404, {"title": "Not Found"})

        def do_GET(self):
            self._api("GET")

        def do_PUT(self):
            self._api("PUT")

        def do_DELETE(self):
            self._api("DELETE")

        def do_POST(self):
            if not self._fake():
                self._send(404)
    return H


def serve(fake: FakePrinter, host="127.0.0.1", port=0) -> ThreadingHTTPServer:
    """Start in a background thread; returns the server (server.server_address)."""
    srv = ThreadingHTTPServer((host, port), make_handler(fake))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name="fakelink").start()
    return srv


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--user", default="maker")
    ap.add_argument("--password", default="secret")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--duration", type=float, default=120, help="real seconds per print")
    a = ap.parse_args()
    srv = serve(FakePrinter(a.user, a.password, a.api_key, a.duration), a.host, a.port)
    print(f"fake PrusaLink on http://{a.host}:{srv.server_address[1]}  user={a.user} password={a.password}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
