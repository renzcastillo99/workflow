"""Upload -> validate -> staging -> reconcile -> ATOMIC publish. A failed job NEVER touches the live (last verified) table.
Rules (client-specific contract, spec s3): exact columns; transaction_id unique & non-empty; ISO date; revenue/cost decimals with <=2 dp;
missing values are REJECTED (never coerced to 0); any invalid row rejects the whole file (strict mode)."""
import csv, io, re, tempfile, datetime as dt, zipfile
from decimal import Decimal, InvalidOperation
import psycopg
from config import INGEST_DSN, MAX_ROWS
REQUIRED = ["transaction_id", "date", "branch", "revenue", "cost"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$"); LIMIT = Decimal("1000000000000")          # numeric(14,2)
LOCK_KEY = 727001
class IngestError(Exception):
    def __init__(self, msg, rejected=None, rows_read=0): super().__init__(msg); self.rejected, self.rows_read = rejected or [], rows_read
class Busy(IngestError): pass
def _rows(filename, data):
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "csv":
        try: text = data.decode("utf-8-sig")
        except UnicodeDecodeError: raise IngestError("File is not valid UTF-8 text (CSV must be UTF-8)")
        rd = csv.reader(io.StringIO(text, newline="")); 
        try: header = [h.strip() for h in next(rd)]
        except StopIteration: raise IngestError("File is empty")
        yield header
        for i, row in enumerate(rd, start=2): yield i, row
    elif ext == "xlsx":
        try:
            import openpyxl; wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except (zipfile.BadZipFile, KeyError, OSError, Exception) as e: raise IngestError(f"Not a valid .xlsx workbook ({type(e).__name__})")
        ws = wb.worksheets[0]; it = ws.iter_rows(values_only=True)
        try: header = [str(h).strip() if h is not None else "" for h in next(it)]
        except StopIteration: raise IngestError("Workbook sheet is empty")
        yield header
        for i, row in enumerate(it, start=2): yield i, list(row)
    else: raise IngestError("Unsupported file type (use .csv or .xlsx)")
def _dec(v, label):
    if v is None or (isinstance(v, str) and v.strip() == ""): return None, f"{label} is missing (not coerced to 0)"
    try: d = Decimal(repr(v)) if isinstance(v, float) else Decimal(str(v).strip())
    except InvalidOperation: return None, f"{label} '{str(v)[:20]}' is not a number"
    if not d.is_finite(): return None, f"{label} is not finite"
    if d.as_tuple().exponent < -2: return None, f"{label} '{v}' has more than 2 decimal places"
    if abs(d) >= LIMIT: return None, f"{label} out of range"
    return d.quantize(Decimal("0.01")), None
def validate(filename, data):
    """Returns (tmp_csv_path, rows, revenue_total, cost_total). Raises IngestError with up to 50 rejected rows when anything is invalid."""
    gen = _rows(filename, data); header = next(gen)
    miss = [c for c in REQUIRED if c not in header]; extra = [c for c in header if c and c not in REQUIRED]
    if miss or extra: raise IngestError(f"Schema mismatch. Missing columns: {miss or 'none'}; unexpected columns: {extra or 'none'}. Required: {REQUIRED}")
    idx = {c: header.index(c) for c in REQUIRED}; seen = set(); rejected = []; bad = 0; n = 0; rev = cost = Decimal(0)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline=""); w = csv.writer(tmp)
    for line, row in gen:
        if not any((str(c).strip() if c is not None else "") for c in row): continue            # blank line
        n += 1
        if n > MAX_ROWS: raise IngestError(f"Too many rows (limit {MAX_ROWS:,})", rejected, n)
        errs = []; g = lambda c: row[idx[c]] if idx[c] < len(row) else None
        tid = g("transaction_id"); tid = (str(int(tid)) if isinstance(tid, float) and tid.is_integer() else str(tid).strip()) if tid is not None else ""
        if not tid: errs.append("transaction_id is missing")
        elif tid in seen: errs.append(f"duplicate transaction_id '{tid[:30]}'")
        d = g("date")
        if isinstance(d, (dt.datetime, dt.date)): d = (d.date() if isinstance(d, dt.datetime) else d).isoformat()
        d = "" if d is None else str(d).strip()
        try:
            if not DATE_RE.match(d): raise ValueError
            dt.date.fromisoformat(d)
        except ValueError: errs.append(f"date '{d[:20]}' is not a valid YYYY-MM-DD date")
        br = g("branch"); br = "" if br is None else str(br).strip()
        if not br: errs.append("branch is missing")
        r, e1 = _dec(g("revenue"), "revenue"); c, e2 = _dec(g("cost"), "cost")
        errs += [e for e in (e1, e2) if e]
        if errs:
            bad += 1
            if len(rejected) < 50: rejected.append({"line": line, "reason": "; ".join(errs)})
            continue
        seen.add(tid); w.writerow([tid, d, br, str(r), str(c)]); rev += r; cost += c
    tmp.close()
    if n == 0: raise IngestError("File has a header but no data rows")
    if bad: raise IngestError(f"{bad} of {n} rows are invalid - file rejected, live data unchanged", rejected, n)
    return tmp.name, n, rev, cost
DDL = "CREATE TABLE staging.transactions (transaction_id text PRIMARY KEY, date date NOT NULL, branch text NOT NULL, revenue numeric(14,2) NOT NULL, cost numeric(14,2) NOT NULL)"
import contextlib
@contextlib.contextmanager
def exclusive():
    """Advisory lock around the WHOLE job (validate + stage + publish): refresh jobs never overlap."""
    with psycopg.connect(INGEST_DSN, autocommit=True) as lock:
        if not lock.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]: raise Busy("Another refresh is already running - try again when it finishes")
        try: yield
        finally: lock.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
def publish(tmp_path, n, rev, cost):
    """Stage -> reconcile against independently computed Decimal totals -> atomic swap. Call inside exclusive(). Returns rows published."""
    if True:
        try:
            with psycopg.connect(INGEST_DSN) as c:                                      # 1) load staging (one transaction)
                c.execute("DROP TABLE IF EXISTS staging.transactions"); c.execute(DDL)
                with c.cursor().copy("COPY staging.transactions FROM STDIN WITH (FORMAT csv)") as cp, open(tmp_path, "rb") as f:
                    while chunk := f.read(1 << 20): cp.write(chunk)
                cnt, srev, scost = c.execute("SELECT count(*), coalesce(sum(revenue),0), coalesce(sum(cost),0) FROM staging.transactions").fetchone()
                if cnt != n or Decimal(srev) != rev or Decimal(scost) != cost:
                    raise IngestError(f"Reconciliation FAILED: file says {n} rows / {rev} / {cost}; staging has {cnt} / {srev} / {scost}. Live data unchanged")
                c.execute("CREATE INDEX ON staging.transactions (date)"); c.execute("CREATE INDEX ON staging.transactions (branch)")
            with psycopg.connect(INGEST_DSN) as c:                                      # 2) atomic swap (one short transaction)
                c.execute("DROP TABLE live.transactions"); c.execute("ALTER TABLE staging.transactions SET SCHEMA live"); c.execute("GRANT SELECT ON live.transactions TO insightflow_ro")
            with psycopg.connect(INGEST_DSN, autocommit=True) as c: c.execute("ANALYZE live.transactions")
            return n
        except IngestError: raise
        except Exception as e: raise IngestError(f"Publish failed ({type(e).__name__}); live data unchanged")
        finally:
            try:
                with psycopg.connect(INGEST_DSN, autocommit=True) as c: c.execute("DROP TABLE IF EXISTS staging.transactions")
            except Exception: pass
def live_summary():
    with psycopg.connect(INGEST_DSN, autocommit=True) as c:
        n, rev, cost, mn, mx = c.execute("SELECT count(*), coalesce(sum(revenue),0), coalesce(sum(cost),0), min(date), max(date) FROM live.transactions").fetchone()
    return {"rows": n, "revenue": rev, "cost": cost, "from": mn, "to": mx}
