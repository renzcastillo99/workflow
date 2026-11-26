"""Minimal Superset REST client (requests). Local synthetic instance only."""
import requests, time, json
BASE = "http://127.0.0.1:8088"
class SS:
    def __init__(self, base=BASE):
        self.base, self.s, self.h = base, requests.Session(), {}
    def login(self, user, pw):
        r = self.s.post(f"{self.base}/api/v1/security/login", json={"username": user, "password": pw, "provider": "db", "refresh": True})
        if r.status_code != 200: return None
        self.h = {"Authorization": "Bearer " + r.json()["access_token"]}
        c = self.s.get(f"{self.base}/api/v1/security/csrf_token/", headers=self.h)
        if c.status_code == 200: self.h["X-CSRFToken"] = c.json()["result"]; self.h["Referer"] = self.base
        return self.h["Authorization"]
    def call(self, method, path, **kw):
        t0 = time.perf_counter()
        r = self.s.request(method, self.base + path, headers={**self.h, **kw.pop("headers", {})}, timeout=kw.pop("timeout", 300), **kw)
        try: d = r.json()
        except Exception: d = r.text[:300]
        return r.status_code, d, (time.perf_counter() - t0) * 1000
