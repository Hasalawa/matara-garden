import http.client
import json
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


class ApiSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        shutil.copy(ROOT / "crops.json", cls.tmp / "crops.json")
        (cls.tmp / "garden.json").write_text(json.dumps({
            "size_sqm": 20, "sun": "full",
            "planted": [{"crop": "okra", "date": "2026-08-20"}]}))
        server.CFG.update(garden=str(cls.tmp / "garden.json"), crops=str(cls.tmp / "crops.json"),
                          model="gemma3", ollama="http://127.0.0.1:1", loopback=True)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def call(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        hdrs.update(headers or {})
        conn.request(method, path, json.dumps(body) if body is not None else None, hdrs)
        res = conn.getresponse()
        raw = res.read()
        conn.close()
        try:
            return res.status, json.loads(raw)
        except ValueError:
            return res.status, raw

    def test_page_is_served(self):
        status, body = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Matara Garden", body)

    def test_plan_tick_and_persist(self):
        status, plan = self.call("GET", "/api/plan?date=2026-10-08")
        self.assertEqual(status, 200)
        self.assertEqual([h["title"] for h in plan["harvest"]], ["Okra"])
        status, plan = self.call("POST", "/api/check", {"id": "harvest:okra@2026-08-20", "done": True, "date": "2026-10-08"})
        self.assertEqual(status, 200)
        self.assertTrue(plan["harvest"][0]["done"])
        saved = json.loads((self.tmp / "garden.json").read_text())
        self.assertEqual(saved["planted"][0]["harvested"], "2026-10-08")

    def test_note_degrades_gracefully_without_ollama(self):
        status, r = self.call("GET", "/api/note?date=2026-10-08")
        self.assertEqual(status, 200)
        self.assertIsNone(r["note"])
        self.assertIn("Ollama", r["error"])

    def test_bad_requests(self):
        self.assertEqual(self.call("POST", "/api/check", {"id": "sow:unicorn", "done": True})[0], 400)
        self.assertEqual(self.call("GET", "/api/plan?date=nope")[0], 400)
        self.assertEqual(self.call("GET", "/api/missing")[0], 404)

    def test_blocks_cross_site_requests(self):
        # a form post from another website can't send application/json without a preflight
        status, _ = self.call("POST", "/api/check", None, {"Content-Type": "text/plain"})
        self.assertEqual(status, 403)
        status, _ = self.call("GET", "/api/plan", None, {"Host": "evil.example"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
