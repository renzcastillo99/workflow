#!/usr/bin/env python3
"""Seed the portal DB: demo reports (from the Superset setup), demo users (pre-provisioned by e-mail; identity bound at first login) and assignments."""
import json, sys
import db; from config import ROOT
db.init()
st = json.load(open(ROOT / "evidence/p2_state.json"))["reports"]
desc = {"sales-live": "Revenue, gross profit, margin and transaction count from the live dataset. Updated by data uploads.", "finance-check": "Reconciliation check on a zero-revenue dataset (margin must show as undefined).", "large-1m": "One million transactions, for responsiveness checks."}
for rid, r in st.items():
    db.run("INSERT INTO reports(id,title,description,dashboard_uuid,dataset_id,live) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, dashboard_uuid=excluded.dashboard_uuid, dataset_id=excluded.dataset_id, live=excluded.live",
           rid, r["title"], desc[rid], r["uuid"], r["dataset_id"], int(r["live"]))
USERS = [("admin.demo@feasibility.invalid", "Ada Admin", "admin"), ("viewer.sales@feasibility.invalid", "Sam Sales", "viewer"), ("viewer.makati@feasibility.invalid", "Mia Makati", "viewer"), ("viewer.none@feasibility.invalid", "Nico Nobody", "viewer")]
for email, name, role in USERS:
    db.run("INSERT INTO users(email,name,role,active,created_at) VALUES(?,?,?,1,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name, role=excluded.role, active=1", email, name, role, db.now())
uid = lambda e: db.one("SELECT id FROM users WHERE email=?", e)["id"]
for email, rid, scope in [("viewer.sales@feasibility.invalid", "sales-live", None), ("viewer.makati@feasibility.invalid", "sales-live", "Makati"), ("viewer.makati@feasibility.invalid", "large-1m", "Makati")]:
    db.run("INSERT OR REPLACE INTO assignments(user_id,report_id,branch_scope,created_at) VALUES(?,?,?,?)", uid(email), rid, scope, db.now())
if not db.one("SELECT 1 FROM refresh_jobs"):
    db.run("INSERT INTO refresh_jobs(started_at,finished_at,source_name,source_type,status,rows_read,rows_published,message,triggered_by) VALUES(?,?,?,?,?,?,?,?,?)",
           db.now(), db.now(), "initial load (seed: first 20,000 synthetic rows)", "seed", "success", 20000, 20000, "Seed snapshot", "system")
print("seeded: reports", len(st), "users", len(USERS)); print("NOT provisioned on purpose: stranger.demo@feasibility.invalid (can authenticate at the IdP, must be denied by the portal)")
