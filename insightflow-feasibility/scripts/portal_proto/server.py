"""FEASIBILITY-ONLY mini 'portal': serves the host page and mints short-lived, RLS-scoped Superset guest tokens SERVER-SIDE.
The browser never sees any Superset credential - only the 300s guest token. Secrets are read from the gitignored .env."""
import http.server, json, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from common import ENV, ROOT
from ssapi import SS
STATE = json.load(open(ROOT / "evidence/ss_state.json")); EMB = json.load(open(ROOT / "evidence/_ss_emb.json"))["emb"]
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=str(pathlib.Path(__file__).parent), **k)
    def do_GET(self):
        if self.path.startswith("/token"):
            ss = SS(); ss.login("admin", ENV["SS_ADMIN_PASSWORD"])
            body = {"user": {"username": "portal-user-makati", "first_name": "P", "last_name": "U"}, "resources": [{"type": "dashboard", "id": EMB["bench_1m"]}],
                    "rls": [{"dataset": STATE["datasets"]["bench_1m"], "clause": "branch = 'Makati'"}]}
            c, d, _ = ss.call("POST", "/api/v1/security/guest_token/", json=body); self.send_response(200); self.end_headers(); self.wfile.write(d["token"].encode()); return
        return super().do_GET()
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", 9000), H).serve_forever()
