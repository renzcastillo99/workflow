"""Shared helpers (stdlib only). Secrets come from the gitignored .env, never from source."""
import json, os, subprocess, time, statistics, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
EVID = ROOT / "evidence"; EVID.mkdir(exist_ok=True)

def env():
    e = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); e[k] = v
    return e

ENV = env()
EXPECTED = json.loads((ROOT / "data" / "expected.json").read_text())

def psql(sql, role="ro", db="clientdata"):
    user, pw = ("insightflow_ro", ENV["DATA_PG_RO_PASSWORD"]) if role == "ro" else ("insightflow_admin", ENV["DATA_PG_ADMIN_PASSWORD"])
    p = subprocess.run(["docker", "exec", "-i", "-e", f"PGPASSWORD={pw}", "if-data-pg", "psql", "-h", "127.0.0.1", "-U", user, "-d", db, "-At", "-F", "|", "-c", sql],
                       capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()

class Evidence:
    """Collects test results with timestamp/environment, writes JSON + prints a table."""
    def __init__(self, name):
        self.name, self.rows = name, []
    def record(self, tc, check, expected, observed, passed, note="", status=None):
        self.rows.append({"tc": tc, "check": check, "expected": str(expected), "observed": str(observed)[:400],
                          "status": status or ("PASS" if passed else "FAIL"), "note": note,
                          "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")})
        print(f"[{status or ('PASS' if passed else 'FAIL')}] {tc} {check} | expected={expected} | observed={str(observed)[:160]}")
    def save(self):
        (EVID / f"{self.name}.json").write_text(json.dumps(self.rows, indent=2))
        p = sum(r["status"] == "PASS" for r in self.rows); g = sum(r["status"] in ("GAP","LIMITATION","LEAK-REPRODUCED","INFO") for r in self.rows)
        print(f"\n{self.name}: {p}/{len(self.rows)} PASS, {g} flagged gap/limitation/info -> evidence/{self.name}.json")

def pct(xs, q):
    xs = sorted(xs); k = (len(xs) - 1) * q; f = int(k); c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)
