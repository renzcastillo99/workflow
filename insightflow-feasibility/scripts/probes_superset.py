#!/usr/bin/env python3
"""Superset probes run INLINE during the session, saved afterwards (transcribed; NOT re-executed in this saved form).
Usage: python3 probes_superset.py [throttle|governance]. finalize_evidence.py holds the corrected/relabelled rows."""
import sys, re, json, subprocess, requests
from common import *; from ssapi import SS
def throttle():
    base = SS().base; s = requests.Session(); tok = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', s.get(base + "/login/").text).group(1)
    print("form", [s.post(base + "/login/", data={"csrf_token": tok, "username": "lockout.probe", "password": f"bad{i}"}, allow_redirects=False).status_code for i in range(12)])
    print("limiter keys:", subprocess.run(["docker", "exec", "if-ss-redis", "redis-cli", "-n", "2", "keys", "*"], capture_output=True, text=True).stdout.split())
    print("rest", [requests.post(base + "/api/v1/security/login", json={"username": "lockout.probe", "password": f"bad{i}", "provider": "db"}).status_code for i in range(12)])
def governance():
    q = lambda c, u, d, sql: subprocess.run(["docker", "exec", "-i", c, "psql", "-U", u, "-d", d, "-At", "-c", sql], capture_output=True, text=True).stdout.strip()
    ro = ENV["DATA_PG_RO_PASSWORD"]
    print("metabase conn details plaintext?", ro in q("if-mb-pg", "metabase", "metabase", "select details from metabase_database where name='clientdata_ro'"))
    print("superset conn row plaintext?", ro in q("if-ss-pg", "superset", "superset", "select sqlalchemy_uri, password from dbs where database_name='clientdata_ro'"))
    print(q("if-mb-pg", "metabase", "metabase", "select context, count(*) filter (where executor_id is null), count(*) filter (where executor_id is not null) from query_execution group by 1"))
    for name, cont in [("superset", "if-superset"), ("metabase", "if-metabase")]:
        blob = subprocess.run(["docker", "logs", cont], capture_output=True, text=True); blob = blob.stdout + blob.stderr
        print(name, "secrets in logs:", {k: (v in blob) for k, v in ENV.items() if len(v) > 12})
if __name__ == "__main__": globals()[sys.argv[1]]()
