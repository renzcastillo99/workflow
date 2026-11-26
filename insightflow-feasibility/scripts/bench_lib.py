"""Engine-agnostic benchmark harness. A 'dashboard load' = N card queries fired in parallel (what a browser does); wall time = slowest card."""
import time, random, threading, statistics, json, platform, os
from concurrent.futures import ThreadPoolExecutor
from common import pct
BRANCHES = ["Makati","Cebu","Davao","Quezon City","Pasig","Taguig","Iloilo","Baguio","Cagayan de Oro","Bacolod","Zamboanga","Clark"]
def rand_filter(rnd):
    m = rnd.randrange(1, 13); y = rnd.choice([2024, 2025]); import calendar
    return {"branch": rnd.choice(BRANCHES), "from": f"{y}-{m:02d}-01", "to": f"{y}-{m:02d}-{calendar.monthrange(y,m)[1]:02d}"}
def dash_load(card_calls, flt=None):
    """card_calls: list of callables(flt)->(ok:bool). returns (wall_ms, all_ok)"""
    t0 = time.perf_counter()
    with ThreadPoolExecutor(len(card_calls)) as ex: res = list(ex.map(lambda f: f(flt), card_calls))
    return (time.perf_counter() - t0) * 1000, all(res)
def series(card_calls, n, filtered, seed=1):
    rnd = random.Random(seed); ms, fails = [], 0
    for _ in range(n):
        t, ok = dash_load(card_calls, rand_filter(rnd) if filtered else None); ms.append(t); fails += (not ok)
    return {"n": n, "p50_ms": round(pct(ms, .5)), "p95_ms": round(pct(ms, .95)), "max_ms": round(max(ms)), "failures": fails}
def concurrent(card_calls, users, loads_each, filtered=True):
    lat, fails, lock = [], [0], threading.Lock()
    def user(i):
        rnd = random.Random(100 + i)
        for _ in range(loads_each):
            t, ok = dash_load(card_calls, rand_filter(rnd) if filtered else None)
            with lock: lat.append(t); fails[0] += (not ok)
    t0 = time.perf_counter()
    with ThreadPoolExecutor(users) as ex: list(ex.map(user, range(users)))
    wall = time.perf_counter() - t0
    return {"users": users, "dashboard_loads": len(lat), "p50_ms": round(pct(lat, .5)), "p95_ms": round(pct(lat, .95)), "max_ms": round(max(lat)), "failures": fails[0], "wall_s": round(wall, 1)}
def env_info():
    return {"host": f"{os.cpu_count()} vCPU, 15 GiB RAM (shared by engine + engine DB + source Postgres + load generator on ONE VM)", "kernel": platform.release(),
            "network": "loopback / docker bridge (no real network latency)", "source_pg": "postgres:16-alpine, shared_buffers=1GB, work_mem=64MB, PK + btree(date) + btree(branch)",
            "targets": "initial dashboard <=3000 ms, filters <=2000 ms, 20 concurrent viewers (p95)"}
