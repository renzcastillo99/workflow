#!/usr/bin/env python3
"""Deterministic SYNTHETIC data generator for InsightFlow BI feasibility tests.

Schema (spec section 3): transaction_id, date, branch, revenue, cost.
No real or customer data is used anywhere. Money is generated as integer cents and
the expected KPI values are computed with decimal.Decimal, independently of any
database or BI engine, to serve as the "independent readback" for reconciliation.

Outputs (data/, gitignored):
  fixture.csv         two-row spec fixture (100/60, 200/120)
  fixture_zero.csv    zero-revenue edge case (margin must be undefined, not 0)
  bench_5m.csv        5,000,000 rows; 100k/500k/1m datasets are exact prefixes of it
  expected.json       Decimal-exact expected KPIs per dataset and per filter
"""
import csv, json, random, sys, datetime as dt
from decimal import Decimal
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)
BRANCHES = ["Makati", "Cebu", "Davao", "Quezon City", "Pasig", "Taguig",
            "Iloilo", "Baguio", "Cagayan de Oro", "Bacolod", "Zamboanga", "Clark"]
START = dt.date(2024, 1, 1)
CHECKPOINTS = [100_000, 500_000, 1_000_000, 5_000_000]
# Filter used for TC-08-style interaction checks
FILTER = {"branch": "Makati", "date_from": "2025-03-01", "date_to": "2025-03-31"}
F_FROM, F_TO = dt.date.fromisoformat(FILTER["date_from"]), dt.date.fromisoformat(FILTER["date_to"])


def cents(n: int) -> Decimal:
    return Decimal(n).scaleb(-2)


class Acc:
    def __init__(self):
        self.rev = self.cost = 0
        self.ids = 0

    def add(self, r, c):
        self.rev += r
        self.cost += c
        self.ids += 1

    def kpis(self):
        rev, cost = cents(self.rev), cents(self.cost)
        gp = rev - cost
        margin = None if rev == 0 else gp / rev
        return {"revenue": str(rev), "gross_profit": str(gp),
                "margin": None if margin is None else str(margin.quantize(Decimal("0.000001"))),
                "transaction_count": self.ids}


def write_fixtures():
    rows = [("F-001", "2025-01-10", "Makati", "100.00", "60.00"),
            ("F-002", "2025-01-11", "Cebu", "200.00", "120.00")]
    zero = [("Z-001", "2025-01-10", "Makati", "0.00", "0.00"),
            ("Z-002", "2025-01-11", "Cebu", "0.00", "0.00")]
    for name, data in (("fixture", rows), ("fixture_zero", zero)):
        with open(OUT / f"{name}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow(["transaction_id", "date", "branch", "revenue", "cost"]); w.writerows(data)
    return {
        "fixture": {"all": {"revenue": "300.00", "gross_profit": "120.00", "margin": "0.400000", "transaction_count": 2},
                    "first_row_only": {"revenue": "100.00", "gross_profit": "40.00", "margin": "0.400000", "transaction_count": 1}},
        "fixture_zero": {"all": {"revenue": "0.00", "gross_profit": "0.00", "margin": None, "transaction_count": 2}},
    }


def main():
    expected = write_fixtures()
    rnd = random.Random(20261125)  # fixed seed => reproducible
    total, filt = Acc(), Acc()
    per_branch = {b: Acc() for b in BRANCHES}
    snap = {}
    with open(OUT / "bench_5m.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["transaction_id", "date", "branch", "revenue", "cost"])
        for i in range(1, CHECKPOINTS[-1] + 1):
            day = START + dt.timedelta(days=rnd.randrange(730))
            branch = BRANCHES[rnd.randrange(len(BRANCHES))]
            r = rnd.randrange(10_000, 5_000_000)               # PHP 100.00 .. 49,999.99
            c = int(r * rnd.uniform(0.40, 0.95))               # integer cents, no float money stored
            w.writerow((f"T{i:07d}", day.isoformat(), branch, f"{r // 100}.{r % 100:02d}", f"{c // 100}.{c % 100:02d}"))
            total.add(r, c); per_branch[branch].add(r, c)
            if branch == FILTER["branch"] and F_FROM <= day <= F_TO:
                filt.add(r, c)
            if i in CHECKPOINTS:
                snap[i] = {"all": total.kpis(), "filter": filt.kpis(),
                           "per_branch": {b: a.kpis() for b, a in per_branch.items()}}
    for n, v in snap.items():
        expected[f"bench_{'5m' if n == 5_000_000 else '1m' if n == 1_000_000 else str(n // 1000) + 'k'}"] = v
    expected["_filter_definition"] = FILTER
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2))
    print("generated; expected totals for 1m:", json.dumps(expected["bench_1m"]["all"]))


if __name__ == "__main__":
    sys.exit(main())
