#!/usr/bin/env python3
"""Generate upload samples (data/samples/, gitignored) and independent Decimal expectations for each live-data state (evidence/p2_expected.json)."""
import csv, json, os, datetime as dt
from decimal import Decimal
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent; S = ROOT / "data/samples"; S.mkdir(parents=True, exist_ok=True)
HEAD = ["transaction_id", "date", "branch", "revenue", "cost"]
base = []
with open(ROOT / "data/bench_5m.csv") as f:
    rd = csv.reader(f); next(rd)
    for i, row in enumerate(rd):
        if i >= 500000: break
        base.append(row)
v0 = base[:20000]
plus5 = [["T9000001", "2025-12-01", "Makati", "1000.00", "600.00"], ["T9000002", "2025-12-01", "Makati", "2500.50", "1500.25"], ["T9000003", "2025-12-02", "Makati", "700.00", "700.00"],
         ["T9000004", "2025-12-02", "Cebu", "3000.00", "1800.00"], ["T9000005", "2025-12-03", "Cebu", "1200.10", "700.05"]]
plus3 = [["T9000006", "2025-12-04", "Davao", "999.99", "500.00"], ["T9000007", "2025-12-04", "Makati", "10.00", "5.00"], ["T9000008", "2025-12-05", "Davao", "20.20", "10.10"]]
def wcsv(name, rows, head=HEAD):
    with open(S / name, "w", newline="") as f: w = csv.writer(f); w.writerow(head); w.writerows(rows)
wcsv("snapshot_v2_plus5.csv", v0 + plus5)
wcsv("bad_duplicate_ids.csv", v0 + [v0[7]])
wcsv("bad_schema_missing_cost.csv", [r[:4] for r in v0[:50]], HEAD[:4])
wcsv("bad_values.csv", v0[:20] + [["B1", "2025-01-01", "Makati", "", "10.00"], ["B2", "2025-01-01", "Makati", "10.005", "5.00"], ["B3", "01/02/2025", "Cebu", "10.00", "5.00"], ["B4", "2025-02-30", "Cebu", "10.00", "5.00"], ["B5", "2025-01-01", "", "10.00", "5.00"], ["B6", "2025-01-01", "Cebu", "abc", "5.00"]])
wcsv("big_valid_500k.csv", base)
(S / "malformed.xlsx").write_bytes(os.urandom(2048))
import openpyxl
wb = openpyxl.Workbook(write_only=True); ws = wb.create_sheet(); ws.append(HEAD)
for r in v0 + plus5 + plus3: ws.append([r[0], dt.datetime.fromisoformat(r[1]), r[2], float(r[3]), float(r[4])])
wb.save(S / "snapshot_v3_plus8.xlsx")
def kp(rows, branch=None):
    rows = [r for r in rows if branch in (None, r[2])]; rev = sum(Decimal(r[3]) for r in rows); cost = sum(Decimal(r[4]) for r in rows)
    return {"rows": len(rows), "revenue": str(rev), "gross_profit": str(rev - cost), "margin": None if rev == 0 else str(((rev - cost) / rev).quantize(Decimal("0.000001")))}
fmt = lambda d: f"{Decimal(d):,.2f}"
exp = {n: {"all": kp(r), "Makati": kp(r, "Makati"), "revenue_fmt": fmt(kp(r)["revenue"]), "makati_revenue_fmt": fmt(kp(r, "Makati")["revenue"])} for n, r in
       {"v0": v0, "v2": v0 + plus5, "v3": v0 + plus5 + plus3, "big": base}.items()}
(ROOT / "evidence/p2_expected.json").write_text(json.dumps(exp, indent=1))
for n, e in exp.items(): print(n, e["all"]["rows"], "rows | revenue", e["revenue_fmt"], "| makati", e["makati_revenue_fmt"])
print(sorted(p.name for p in S.iterdir()))
