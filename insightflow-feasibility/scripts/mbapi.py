"""Minimal Metabase REST client (stdlib). Used only against the local synthetic instance."""
import json, urllib.request, urllib.error, time
from decimal import Decimal
BASE = "http://127.0.0.1:3000"
class MB:
    def __init__(self, base=BASE): self.base, self.token = base, None
    def call(self, method, path, body=None, token="self", timeout=300):
        h = {"Content-Type": "application/json"}
        t = self.token if token == "self" else token
        if t: h["X-Metabase-Session"] = t
        req = urllib.request.Request(self.base + path, method=method, headers=h,
                                     data=None if body is None else json.dumps(body).encode())
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read(); code = r.status
        except urllib.error.HTTPError as e:
            raw = e.read(); code = e.code
        dt_ms = (time.perf_counter() - t0) * 1000
        try: data = json.loads(raw, parse_float=Decimal) if raw else None
        except Exception: data = raw.decode(errors="replace")[:300]
        return code, data, dt_ms
    def login(self, user, pw):
        c, d, _ = self.call("POST", "/api/session", {"username": user, "password": pw}, token=None)
        return d["id"] if c == 200 else None
