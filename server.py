#!/usr/bin/env python3
"""Matara Garden Planner: local web app (standard library only).

    python server.py

Opens http://localhost:8000 in your browser. Your garden is saved in garden.json.
"""
import argparse
import json
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import planner

HERE = Path(__file__).parent
LOCK = threading.Lock()
NOTE_CACHE = {}
CFG = {}


def parse_day(value):
    return date.fromisoformat(value) if value else date.today()


def current_plan(today):
    with LOCK:
        return planner.build_plan(today, planner.load_json(CFG["garden"]), planner.load_json(CFG["crops"]))


def mutate(fn):
    with LOCK:
        garden = planner.load_json(CFG["garden"])
        data = planner.load_json(CFG["crops"])
        fn(garden, data)
        planner.save_json(CFG["garden"], garden)


class Handler(BaseHTTPRequestHandler):
    server_version = "MataraGarden"

    def log_message(self, fmt, *args):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def host_ok(self):
        # Guards against other websites talking to this server (DNS rebinding).
        if not CFG["loopback"]:
            return True
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        return host in ("localhost", "127.0.0.1", "::1")

    def do_GET(self):
        if not self.host_ok():
            return self.send(403, {"error": "forbidden"})
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
            today = parse_day(qs.get("date", [""])[0])
            if u.path == "/api/plan":
                return self.send(200, current_plan(today))
            if u.path == "/api/note":
                lang = "si" if qs.get("lang", ["en"])[0] == "si" else "en"
                plan = current_plan(today)
                key = (lang, CFG["model"], json.dumps(planner.note_facts(plan), sort_keys=True))
                if key not in NOTE_CACHE:
                    try:
                        NOTE_CACHE[key] = planner.ask_note(plan, CFG["model"], CFG["ollama"], lang)
                    except RuntimeError as e:
                        return self.send(200, {"note": None, "error": str(e)})
                return self.send(200, {"note": NOTE_CACHE[key], "model": CFG["model"]})
            return self.send(404, {"error": "not found"})
        except ValueError as e:
            return self.send(400, {"error": str(e)})
        except Exception as e:  # keep the server alive
            return self.send(500, {"error": f"server error: {e}"})

    def do_POST(self):
        if not self.host_ok() or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self.send(403, {"error": "forbidden"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > 10_000:
                return self.send(413, {"error": "request too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            today = parse_day(body.get("date"))
            path = urlparse(self.path).path
            if path == "/api/check":
                mutate(lambda g, d: planner.set_check(g, d, today, str(body["id"]), bool(body["done"])))
            elif path == "/api/plant":
                mutate(lambda g, d: planner.add_planted(g, d, str(body["crop"]), str(body["planted"])))
            elif path == "/api/unplant":
                mutate(lambda g, d: planner.remove_planted(g, str(body["crop"]), str(body["planted"])))
            elif path == "/api/settings":
                mutate(lambda g, d: planner.set_settings(g, body["sun"], body["size_sqm"]))
            else:
                return self.send(404, {"error": "not found"})
            return self.send(200, current_plan(today))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            return self.send(400, {"error": f"bad request: {e}"})
        except Exception as e:
            return self.send(500, {"error": f"server error: {e}"})


def main():
    ap = argparse.ArgumentParser(description="Matara Garden Planner web app")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it from your phone on the same Wi-Fi")
    ap.add_argument("--model", default="gemma3", help="Ollama model name")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--garden", default=str(HERE / "garden.json"))
    ap.add_argument("--crops", default=str(HERE / "crops.json"))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    CFG.update(garden=a.garden, crops=a.crops, model=a.model, ollama=a.ollama,
               loopback=a.host in ("127.0.0.1", "localhost"))
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://localhost:{a.port}"
    print(f"Matara Garden Planner is running at {url}  (press Ctrl+C to stop)")
    if not a.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
