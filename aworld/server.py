"""A small web server (Python standard library only) for watching the world.

    GET  /                      the viewer web page
    GET  /api/status            time, speed, headline numbers
    GET  /api/terrain           unchanging map layers (binary)
    GET  /api/frame             current living layers (binary): plants, grazers,
                                predators, snow, temperature, rain, people
    GET  /api/metrics           statistics over time (JSON)
    GET  /api/events            the history log (JSON)
    GET  /api/cell?x=&y=        everything about one spot on the map
    GET  /api/people?x=&y=      the people living in that spot
    GET  /api/person?id=        one person's life: family, traits, fate
    GET  /api/worlds            all saved worlds
    POST /api/control           {"action": "play"|"pause"|"step"|"speed"|"pause_on_major", ...}
    POST /api/save              save a checkpoint now
    POST /api/seek              {"tick": N}  rewind to an exact day
    POST /api/worlds            {"name": "...", "seed": 123}  create a new world
    POST /api/worlds/open       {"id": "..."}  switch to another saved world
"""
from __future__ import annotations

import json
import mimetypes
import traceback
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .runner import SPEEDS, Runner
from .storage import list_worlds

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def make_handler(runner: Runner):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ArtificialWorld/0.1"

        def log_message(self, fmt, *args):   # keep the console quiet
            pass

        # ── helpers ────────────────────────────────────────────
        def _send(self, body: bytes, ctype: str, status=HTTPStatus.OK, headers: dict | None = None):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, str(v))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status=HTTPStatus.OK):
            self._send(json.dumps(obj).encode(), "application/json", status)

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _route(self, method: str):
            url = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                handler = ROUTES.get((method, url.path))
                if handler:
                    return handler(self, q)
                if method == "GET":
                    return self._static(url.path)
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:     # never let one bad request kill the server
                traceback.print_exc()
                self._json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

        def _static(self, path: str):
            rel = "index.html" if path in ("", "/") else path.lstrip("/")
            target = (WEB_DIR / rel).resolve()
            if WEB_DIR not in target.parents or not target.is_file():
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if target.suffix == ".js":
                ctype = "text/javascript"
            self._send(target.read_bytes(), ctype)

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        # ── routes ─────────────────────────────────────────────
        def r_status(self, q):
            self._json(runner.status())

        def r_terrain(self, q):
            st = runner.status()
            self._send(runner.terrain_bytes(), "application/octet-stream",
                       headers={"X-Width": st["world"]["width"], "X-Height": st["world"]["height"],
                                "X-World": st["world"]["id"]})

        def r_frame(self, q):
            with runner.lock:
                tick = runner.world.tick
                body = runner.frame_bytes()
            self._send(body, "application/octet-stream", headers={"X-Tick": tick})

        def r_metrics(self, q):
            names = q["names"].split(",") if q.get("names") else None
            with runner.lock:
                data = runner.store.metric_series(names, int(q.get("points", 600)), runner.world.tick)
                dpy = runner.world.dpy
            self._json({"days_per_year": dpy, "series": data})

        def r_events(self, q):
            with runner.lock:
                ev = runner.store.events(int(q.get("limit", 200)), runner.world.tick)
            self._json(ev)

        def r_cell(self, q):
            self._json(runner.cell(int(q.get("x", 0)), int(q.get("y", 0))))

        def r_people(self, q):
            self._json(runner.people_at(int(q.get("x", 0)), int(q.get("y", 0))))

        def r_person(self, q):
            self._json(runner.person(int(q.get("id", 0))))

        def r_worlds(self, q):
            self._json({"current": runner.store.meta["id"], "worlds": list_worlds(runner.worlds_dir)})

        def r_control(self, q):
            b = self._body()
            action = b.get("action")
            if action == "play":
                runner.running = True
            elif action == "pause":
                runner.running = False
                runner.save()
            elif action == "step":
                runner.step_days(int(b.get("days", 1)))
            elif action == "speed" and b.get("speed") in SPEEDS:
                runner.speed = b["speed"]
            elif action == "pause_on_major":
                runner.pause_on_major = bool(b.get("value"))
            else:
                return self._json({"error": f"unknown action {action!r}"}, HTTPStatus.BAD_REQUEST)
            self._json(runner.status())

        def r_save(self, q):
            runner.save()
            self._json(runner.status())

        def r_seek(self, q):
            b = self._body()
            with runner.lock:
                latest = max(runner.store.checkpoint_ticks() + [runner.world.tick])
            runner.seek(min(int(b.get("tick", 0)), latest))
            self._json(runner.status())

        def r_new_world(self, q):
            b = self._body()
            seed = b.get("seed")
            wid = runner.create_world(name=b.get("name") or "New World",
                                      seed=int(seed) if seed not in (None, "") else None)
            self._json({"id": wid})

        def r_open_world(self, q):
            runner.open_world(self._body()["id"])
            self._json(runner.status())

    ROUTES = {
        ("GET", "/api/status"): Handler.r_status,
        ("GET", "/api/terrain"): Handler.r_terrain,
        ("GET", "/api/frame"): Handler.r_frame,
        ("GET", "/api/metrics"): Handler.r_metrics,
        ("GET", "/api/events"): Handler.r_events,
        ("GET", "/api/cell"): Handler.r_cell,
        ("GET", "/api/worlds"): Handler.r_worlds,
        ("GET", "/api/people"): Handler.r_people,
        ("GET", "/api/person"): Handler.r_person,
        ("POST", "/api/control"): Handler.r_control,
        ("POST", "/api/save"): Handler.r_save,
        ("POST", "/api/seek"): Handler.r_seek,
        ("POST", "/api/worlds"): Handler.r_new_world,
        ("POST", "/api/worlds/open"): Handler.r_open_world,
    }
    return Handler


def serve(runner: Runner, host: str = "0.0.0.0", port: int = 8080) -> None:
    httpd = ThreadingHTTPServer((host, port), make_handler(runner))
    httpd.daemon_threads = True
    print(f"[server] watching at http://{host}:{port}")
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
