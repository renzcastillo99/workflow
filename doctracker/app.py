"""
DocTracker DEMO - manual document tracking for one user on Windows.

  * Runs on http://127.0.0.1 only. No login. No background jobs, no folder watcher.
  * The "database" is an Excel file: Documents\\DocTrackerData\\tracker.xlsx
  * Every write: backup to tracker_backup.xlsx first, then save. The workbook is
    opened only for the moment of reading or writing.

  * Only one copy runs at a time. Starting it again just reopens the browser.
  * When built without a console window (PyInstaller --noconsole), messages go to
    Documents\\DocTrackerData\\doctracker_log.txt. To stop it: Task Manager >
    DocTracker > End task (or restart the laptop).

Run:
    pip install flask openpyxl
    python app.py

Build the double-click version (on Windows, in a folder NOT synced by OneDrive):
    pip install pyinstaller
    pyinstaller --onedir --noconsole --name DocTracker app.py
    -> start dist\\DocTracker\\DocTracker.exe
"""

import datetime as dt
import io
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template_string, request, url_for
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# CONFIG - change statuses and defaults here, not in the logic below.
# ---------------------------------------------------------------------------
CONFIG = {
    # Workflow statuses, in order. The first one is given to new uploads.
    "STATUSES": ["Received", "Routed", "Signed/Approved", "Completed"],
    "STATUS_NEW": "Received",       # set on upload
    "STATUS_ROUTED": "Routed",      # suggested when a department is picked while status is STATUS_NEW
    "STATUS_DONE": "Completed",     # no "waiting" count and never overdue
    "DEFAULT_DEPARTMENTS": ["Admin", "Finance", "HR", "Legal", "Records"],
    "DEFAULT_OVERDUE_DAYS": 7,
    "DEFAULT_REF_FORMAT": "DOC-{YYYY}-{SEQ:4}",
    "START_PORT": 5000,
    "MAX_UPLOAD_MB": 100,
}

for _k in ("STATUS_NEW", "STATUS_ROUTED", "STATUS_DONE"):
    if CONFIG[_k] not in CONFIG["STATUSES"]:
        sys.exit(f"CONFIG error: {_k} = {CONFIG[_k]!r} is not in CONFIG['STATUSES'].")

# Exact sheet and column names (row 1 of each sheet).
SHEETS = {
    "Documents": ["Ref No", "Subject", "From", "Date Received", "Status", "Current Dept",
                  "File Link", "Signed Copy Link", "Notes"],
    "History": ["Ref No", "Date", "Status", "Dept"],
    "Departments": ["Name", "Active"],
    "Settings": ["Key", "Value"],
}

LOCKED_MSG = ("Close tracker.xlsx and try again. It is probably open in Excel (or OneDrive is "
              "syncing it - then just wait a few seconds), so Windows will not let the app save it.")
DATE_FMT = "yyyy-mm-dd"
DATETIME_FMT = "yyyy-mm-dd hh:mm"


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def documents_folder() -> Path:
    """The user's real Documents folder (handles OneDrive / redirected folders on Windows)."""
    if os.name == "nt":
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                value, _ = winreg.QueryValueEx(k, "Personal")
            p = Path(os.path.expandvars(value))
            if p.is_dir():
                return p
        except OSError:
            pass
    return Path.home() / "Documents"


DATA_DIR = documents_folder() / "DocTrackerData"
TRACKER = DATA_DIR / "tracker.xlsx"
BACKUP = DATA_DIR / "tracker_backup.xlsx"
PENDING = DATA_DIR / "_pending"   # uploaded files kept here until the Excel save succeeds
LOG_FILE = DATA_DIR / "doctracker_log.txt"                   # used only when there is no console window
URL_FILE = Path(tempfile.gettempdir()) / "DocTracker_url.txt"  # address of the copy that is running


def default_settings() -> dict:
    return {
        "storage_folder": str(DATA_DIR / "Files"),
        "export_folder": str(DATA_DIR / "Exports"),
        "overdue_days": str(CONFIG["DEFAULT_OVERDUE_DAYS"]),
        "ref_format": CONFIG["DEFAULT_REF_FORMAT"],
    }


# ---------------------------------------------------------------------------
# Excel access layer
# ---------------------------------------------------------------------------
class AppError(Exception):
    """A friendly, user-facing problem. Callers keep the user's input when they catch it."""


WRITE_LOCK = threading.Lock()


def read_wb():
    """Load tracker.xlsx into memory and release the file immediately."""
    try:
        with open(TRACKER, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        raise AppError(f"tracker.xlsx was not found in {DATA_DIR}. Restart the app to create a new one.")
    except PermissionError:
        raise AppError("Windows would not let the app read tracker.xlsx. Close it in Excel "
                       "(or wait a few seconds if OneDrive is syncing it) and try again.")
    try:
        return load_workbook(io.BytesIO(data))
    except Exception as e:  # corrupt / not an xlsx
        raise AppError(f"tracker.xlsx could not be read as an Excel file ({e}). "
                       f"You can restore tracker_backup.xlsx from {DATA_DIR}.")


def write_wb(mutator):
    """Read -> change -> backup -> save.

    mutator(wb, created) changes the workbook and may copy files into the storage
    folder; it appends those new files to `created` so they are removed again if
    the save fails. Returns whatever the mutator returns.
    """
    with WRITE_LOCK:
        created: list[Path] = []
        try:
            wb = read_wb()
            result = mutator(wb, created)
            buf = io.BytesIO()
            wb.save(buf)
            try:
                shutil.copy2(TRACKER, BACKUP)
            except PermissionError:
                raise AppError("Close tracker_backup.xlsx and try again. "
                               "(The app makes a backup before every save.)")
            except OSError as e:
                raise AppError(f"Could not create the backup tracker_backup.xlsx ({e}). Nothing was saved.")
            tmp = TRACKER.with_name("~tracker_saving.tmp")
            try:
                tmp.write_bytes(buf.getvalue())
                os.replace(tmp, TRACKER)     # fails with PermissionError while Excel has the file open
            except PermissionError:
                raise AppError(LOCKED_MSG)
            except OSError as e:
                raise AppError(f"Could not save tracker.xlsx ({e}).")
            finally:
                try:
                    if tmp.exists():
                        tmp.unlink()
                except OSError:
                    pass
            return result
        except Exception:
            for p in created:              # roll back copied files
                try:
                    p.unlink()
                except OSError:
                    pass
            raise


def colmap(ws) -> dict:
    return {str(c.value).strip(): i + 1 for i, c in enumerate(ws[1]) if c.value is not None}


def sheet_rows(ws) -> list[dict]:
    cm = colmap(ws)
    out = []
    for r in range(2, ws.max_row + 1):
        rec = {h: ws.cell(r, c).value for h, c in cm.items()}
        if all(v is None or str(v).strip() == "" for v in rec.values()):
            continue
        rec["_row"] = r
        out.append(rec)
    return out


def append_row(ws, rec: dict) -> int:
    cm = colmap(ws)
    r = ws.max_row + 1
    for h, v in rec.items():
        if h in cm:
            ws.cell(r, cm[h], v)
    return r


def set_cell(ws, row, header, value, fmt=None):
    c = ws.cell(row, colmap(ws)[header], value)
    if fmt:
        c.number_format = fmt
    return c


def find_row(ws, ref) -> int | None:
    col = colmap(ws)["Ref No"]
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(r, col).value or "").strip() == ref:
            return r
    return None


def text(v) -> str:
    return "" if v is None else str(v).strip()


def is_active(v) -> bool:
    return v is True or text(v).lower() in ("yes", "y", "true", "1", "active")


def to_datetime(v):
    if isinstance(v, dt.datetime):
        return v
    if isinstance(v, dt.date):
        return dt.datetime.combine(v, dt.time())
    if isinstance(v, str):
        for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return dt.datetime.strptime(v.strip(), f)
            except ValueError:
                pass
    return None


def fmt_date(v) -> str:
    d = to_datetime(v)
    return d.strftime("%Y-%m-%d") if d else text(v)


def fmt_datetime(v) -> str:
    d = to_datetime(v)
    return d.strftime("%Y-%m-%d %H:%M") if d else text(v)


# ---------------------------------------------------------------------------
# Workbook creation, validation, settings
# ---------------------------------------------------------------------------
def create_tracker():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)
    widths = {"Documents": [16, 40, 28, 14, 16, 16, 40, 40, 40], "History": [16, 18, 16, 16],
              "Departments": [24, 10], "Settings": [18, 60]}
    for name, cols in SHEETS.items():
        ws = wb.create_sheet(name)
        ws.append(cols)
        for i, c in enumerate(ws[1]):
            c.font = Font(bold=True)
            ws.column_dimensions[c.column_letter].width = widths[name][i]
        ws.freeze_panes = "A2"
    for d in CONFIG["DEFAULT_DEPARTMENTS"]:
        wb["Departments"].append([d, "Yes"])
    for k, v in default_settings().items():
        wb["Settings"].append([k, v])
    wb.save(TRACKER)
    for k in ("storage_folder", "export_folder"):
        Path(default_settings()[k]).mkdir(parents=True, exist_ok=True)


def validate() -> list[str]:
    """Check that every sheet and column exists. Returns a list of problems (empty = OK)."""
    try:
        wb = read_wb()
    except AppError as e:
        return [str(e)]
    errors = []
    for name, cols in SHEETS.items():
        if name not in wb.sheetnames:
            errors.append(f'Sheet "{name}" is missing. Sheets found: {", ".join(wb.sheetnames)}.')
            continue
        cm = colmap(wb[name])
        missing = [c for c in cols if c not in cm]
        if missing:
            found = ", ".join(cm) or "nothing"
            errors.append(f'Sheet "{name}": column(s) {", ".join(missing)} missing from row 1 '
                          f'(row 1 contains: {found}).')
    return errors


def get_settings(wb) -> dict:
    s = default_settings()
    for r in sheet_rows(wb["Settings"]):
        k, v = text(r.get("Key")), text(r.get("Value"))
        if k and v:
            s[k] = v
    try:
        s["overdue_days"] = int(float(s["overdue_days"]))
    except ValueError:
        s["overdue_days"] = CONFIG["DEFAULT_OVERDUE_DAYS"]
    return s


def get_departments(wb) -> list[dict]:
    return [{"name": text(r["Name"]), "active": is_active(r["Active"])}
            for r in sheet_rows(wb["Departments"]) if text(r["Name"])]


def load_all() -> dict:
    wb = read_wb()
    return {"settings": get_settings(wb), "docs": sheet_rows(wb["Documents"]),
            "history": sheet_rows(wb["History"]), "depts": get_departments(wb)}


# ---------------------------------------------------------------------------
# Reference numbers
# ---------------------------------------------------------------------------
SEQ_RX = re.compile(r"\{SEQ(?::(\d+))?\}")


def check_ref_format(fmt: str) -> str | None:
    """Return an error message, or None if the format is valid."""
    if len(SEQ_RX.findall(fmt)) != 1:
        return "Ref format must contain {SEQ} exactly once, e.g. DOC-{YYYY}-{SEQ:4}."
    leftover = SEQ_RX.sub("", fmt)
    for t in ("{YYYY}", "{YY}", "{MM}"):
        leftover = leftover.replace(t, "")
    if "{" in leftover or "}" in leftover:
        return "Unknown token in ref format. Allowed: {YYYY}, {YY}, {MM}, {SEQ} or {SEQ:4}."
    if re.search(r'[\\/:*?"<>|]', leftover):
        return 'Ref format cannot contain \\ / : * ? " < > | (it is used in file names).'
    return None


def next_ref(existing, fmt: str, today: dt.date) -> str:
    """Next free ref no. The counter restarts whenever the year/month part changes."""
    m = SEQ_RX.search(fmt)
    width = int(m.group(1) or 1)

    def fill(s):
        return s.replace("{YYYY}", f"{today:%Y}").replace("{YY}", f"{today:%y}").replace("{MM}", f"{today:%m}")

    prefix, suffix = fill(fmt[:m.start()]), fill(fmt[m.end():])
    rx = re.compile("^" + re.escape(prefix) + r"(\d+)" + re.escape(suffix) + "$")
    existing = {text(r) for r in existing}
    nums = [int(mm.group(1)) for r in existing if (mm := rx.match(r))]
    n = max(nums, default=0) + 1
    while f"{prefix}{n:0{width}d}{suffix}" in existing:
        n += 1
    return f"{prefix}{n:0{width}d}{suffix}"


# ---------------------------------------------------------------------------
# Files and links
# ---------------------------------------------------------------------------
def resolve(settings, rel) -> Path | None:
    rel = text(rel)
    if not rel:
        return None
    p = Path(rel)
    return p if p.is_absolute() else Path(settings["storage_folder"]) / p


def set_link(ws, row, header, settings, rel):
    """Write a relative path into the cell and make it a real Excel hyperlink."""
    c = set_cell(ws, row, header, rel or None)
    if rel:
        c.hyperlink = resolve(settings, rel).absolute().as_uri()
        c.style = "Hyperlink"
    else:
        c.hyperlink = None
        c.style = "Normal"


def safe_part(s: str, n=40) -> str:
    s = re.sub(r"[^A-Za-z0-9 ._-]+", "", s or "")
    return re.sub(r"\s+", " ", s).strip(" .")[:n].strip(" .")


def main_file_name(ref, subject) -> str:
    part = safe_part(subject)
    return f"{ref} - {part}.pdf" if part else f"{ref}.pdf"


def signed_file_name(ref, ext) -> str:
    return f"{ref} - SIGNED{ext or '.pdf'}"


def storage_dir(settings) -> Path:
    p = Path(settings["storage_folder"])
    if not p.is_dir():
        raise AppError(f"The storage folder does not exist: {p}. Fix it in Settings "
                       f"(for example, if the drive letter changed).")
    return p


def copy_into_storage(src: Path, settings, rel: str, created: list) -> None:
    """Copy the file's contents only (some network drives refuse copied dates/attributes).
    Copies to a temporary name first, so a failed copy never leaves a half-written file."""
    dest = storage_dir(settings) / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".copying")
    try:
        shutil.copyfile(src, tmp)
        if not dest.exists():
            created.append(dest)
        os.replace(tmp, dest)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def os_open(path: Path, select=False):
    """Open with the Windows default program, or show it in File Explorer."""
    if os.name == "nt":
        if select:
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(str(path))
    else:  # non-Windows fallback, only for development
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, str(path.parent if select else path)])


# Uploaded files wait in PENDING/<token>/ until the Excel save succeeds, so a
# failed save (Excel open) never forces the user to choose the file again.
TOKEN_RX = re.compile(r"^[0-9a-f]{32}$")


def take_upload(field: str, token: str | None):
    """Return (path, token) for a newly chosen file, or for one kept from a failed attempt."""
    f = request.files.get(field)
    if f and f.filename:
        token = uuid.uuid4().hex
        d = PENDING / token
        d.mkdir(parents=True, exist_ok=True)
        ext = Path(f.filename).suffix.lower()
        name = secure_filename(f.filename) or "upload"
        if not name.lower().endswith(ext):
            name = "upload" + ext
        p = d / name
        f.save(p)
        return p, token
    if token and TOKEN_RX.match(token):
        d = PENDING / token
        files = [x for x in d.iterdir() if x.is_file()] if d.is_dir() else []
        if files:
            return files[0], token
    return None, None


def drop_pending(token):
    if token and TOKEN_RX.match(token):
        shutil.rmtree(PENDING / token, ignore_errors=True)


def clean_old_pending():
    if not PENDING.is_dir():
        return
    cutoff = dt.datetime.now().timestamp() - 86400
    for d in PENDING.iterdir():
        try:
            if d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def is_pdf(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            return f.read(1024).lstrip().startswith(b"%PDF")
    except OSError:
        return False


def make_pdf(lines: list[str]) -> bytes:
    """A tiny valid one-page PDF (used for sample data only)."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    ops = ["BT /F1 14 Tf 72 740 Td 20 TL"] + [f"({esc(x)}) Tj T*" for x in lines] + ["ET"]
    stream = "\n".join(ops).encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


# ---------------------------------------------------------------------------
# View helpers
# ---------------------------------------------------------------------------
def doc_view(doc, history, settings) -> dict:
    ref = text(doc["Ref No"])
    moves = [to_datetime(h["Date"]) for h in history if text(h["Ref No"]) == ref]
    moves = [m for m in moves if m]
    since = max(moves) if moves else to_datetime(doc["Date Received"])
    status = text(doc["Status"])
    waiting = None
    if status != CONFIG["STATUS_DONE"] and since:
        waiting = max(0, (dt.date.today() - since.date()).days)
    return {
        "ref": ref, "subject": text(doc["Subject"]), "sender": text(doc["From"]),
        "received": fmt_date(doc["Date Received"]), "status": status,
        "dept": text(doc["Current Dept"]), "notes": text(doc["Notes"]),
        "file": text(doc["File Link"]), "signed": text(doc["Signed Copy Link"]),
        "waiting": waiting, "overdue": waiting is not None and waiting > settings["overdue_days"],
    }


def find_doc(data, ref):
    for d in data["docs"]:
        if text(d["Ref No"]) == ref:
            return d
    return None


# ---------------------------------------------------------------------------
# Templates (inline)
# ---------------------------------------------------------------------------
BASE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} - DocTracker</title>
<style>
:root{--bg:#f4f6f9;--card:#fff;--ink:#1d2433;--muted:#5d6778;--line:#dde2ea;--accent:#1f5fbf;--red:#b42318;--redbg:#fdecea;--green:#146c43;--greenbg:#e7f6ee;--amber:#8a5a00;--amberbg:#fff6e0}
*{box-sizing:border-box}body{margin:0;font:15px/1.45 "Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{background:#14233c;color:#fff;padding:10px 20px;display:flex;gap:24px;align-items:center;flex-wrap:wrap}
header b{font-size:17px}header a{color:#cfe0ff;text-decoration:none}header a:hover{color:#fff}
main{max-width:1200px;margin:18px auto;padding:0 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-bottom:16px}
h1{font-size:21px;margin:0 0 12px}h2{font-size:17px;margin:0 0 10px}
table{width:100%;border-collapse:collapse;background:#fff}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{background:#eef1f6;font-weight:600;font-size:13px}tr.overdue td{background:var(--redbg)}
.btn,button{display:inline-block;background:var(--accent);color:#fff;border:0;border-radius:6px;padding:7px 12px;font:inherit;cursor:pointer;text-decoration:none;white-space:nowrap}
.btn.light,button.light{background:#e8edf5;color:var(--ink)}.btn.small,button.small{padding:4px 8px;font-size:13px}
button.danger{background:var(--red)}
input,select,textarea{font:inherit;padding:6px 8px;border:1px solid #b9c2d0;border-radius:6px;background:#fff;max-width:100%}
label{display:block;font-weight:600;margin:10px 0 4px}textarea{width:100%;min-height:70px}
.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.muted{color:var(--muted);font-size:13px}
.msg{padding:10px 12px;border-radius:6px;margin-bottom:14px;border:1px solid}
.msg.err{background:var(--redbg);color:var(--red);border-color:#f5c2bd}.msg.ok{background:var(--greenbg);color:var(--green);border-color:#b7e1c8}
.msg.warn{background:var(--amberbg);color:var(--amber);border-color:#f1d79a}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;background:#e8edf5;font-size:13px}
.late{color:var(--red);font-weight:600}.grid{display:grid;grid-template-columns:170px 1fr;gap:4px 12px}
.inline{display:inline}.wide{width:100%}
</style></head><body>
<header><b>DocTracker <span class="muted" style="color:#9fb3d6">demo</span></b>
<a href="{{ url_for('index') }}">Documents</a><a href="{{ url_for('upload') }}">Upload</a><a href="{{ url_for('settings') }}">Settings</a></header>
<main>
<div id="msgbox" class="msg" hidden></div>
{% for cat, m in get_flashed_messages(with_categories=true) %}<div class="msg {{ cat }}">{{ m }}</div>{% endfor %}
{{ body|safe }}
</main>
<script>
async function postJSON(url){
  const box=document.getElementById('msgbox');
  try{
    const r=await fetch(url,{method:'POST'}); const j=await r.json();
    box.innerHTML=''; box.className='msg '+(j.ok?'ok':'err');
    const s=document.createElement('span'); s.textContent=j.message; box.appendChild(s);
    if(j.relink){const a=document.createElement('a'); a.href=j.relink; a.textContent='Relink...'; a.className='btn small'; a.style.marginLeft='10px'; box.appendChild(a);}
  }catch(e){ box.className='msg err'; box.textContent='The app did not respond. Is it still running?'; }
  box.hidden=false; window.scrollTo(0,0);
}
</script>
</body></html>"""

INDEX = """
<div class="row" style="justify-content:space-between;margin-bottom:12px">
  <h1 style="margin:0">Documents</h1>
  <div class="row">
    <a class="btn" href="{{ url_for('upload') }}">Upload scanned PDF</a>
    <button class="light" type="button" onclick="postJSON('{{ url_for('open_excel') }}')">Open Excel file</button>
    <form class="inline" method="post" action="{{ url_for('export') }}"><button class="light">Export to Excel</button></form>
    <form class="inline" method="post" action="{{ url_for('sample') }}" onsubmit="return confirm('Add 6 fake demo documents?')"><button class="light">Load sample data</button></form>
  </div>
</div>
<form class="card row" method="get">
  <input name="q" value="{{ q }}" placeholder="Search ref no., subject, from, notes" style="flex:1;min-width:220px">
  <select name="status"><option value="">All statuses</option>{% for s in statuses %}<option {{ 'selected' if s==status }}>{{ s }}</option>{% endfor %}</select>
  <select name="dept"><option value="">All departments</option>{% for d in dept_names %}<option {{ 'selected' if d==dept }}>{{ d }}</option>{% endfor %}</select>
  <button>Filter</button>{% if q or status or dept %}<a class="btn light" href="{{ url_for('index') }}">Clear</a>{% endif %}
</form>
<div class="card" style="padding:0;overflow-x:auto">
<table>
<tr><th>Ref no.</th><th>Subject / From</th><th>Date received</th><th>Status</th><th>With</th><th>Waiting</th><th>File</th></tr>
{% for d in docs %}
<tr class="{{ 'overdue' if d.overdue }}">
  <td><a href="{{ url_for('detail', ref=d.ref) }}"><b>{{ d.ref }}</b></a></td>
  <td>{{ d.subject }}<div class="muted">{{ d.sender }}</div></td>
  <td>{{ d.received }}</td>
  <td><span class="badge">{{ d.status }}</span></td>
  <td>{{ d.dept or '-' }}</td>
  <td>{% if d.waiting is none %}-{% else %}<span class="{{ 'late' if d.overdue }}">{{ d.waiting }} day{{ '' if d.waiting==1 else 's' }}</span>{% endif %}</td>
  <td class="row">
    <button class="small" type="button" data-url="{{ url_for('open_target', ref=d.ref, which='file') }}" onclick="postJSON(this.dataset.url)">Open file</button>
    <button class="small light" type="button" data-url="{{ url_for('open_target', ref=d.ref, which='folder') }}" onclick="postJSON(this.dataset.url)">Open folder</button>
  </td>
</tr>
{% else %}
<tr><td colspan="7" class="muted" style="padding:20px">No documents found. Upload a scanned PDF, or click "Load sample data" for a demo.</td></tr>
{% endfor %}
</table></div>
<p class="muted">{{ docs|length }} of {{ total }} document(s). Rows in red have waited more than {{ overdue_days }} days with the same department. Data file: {{ tracker }}</p>
"""

UPLOAD = """
<h1>Upload scanned PDF</h1>
{% if error %}<div class="msg err">{{ error }}{% if kept %} Your entries are still here.{% endif %}</div>{% endif %}
<form class="card" method="post" enctype="multipart/form-data" style="max-width:640px">
  <label>Scanned PDF</label>
  {% if pending_name %}<div class="msg warn">File kept: <b>{{ pending_name }}</b>. You don't need to choose it again (or choose another one below).</div>{% endif %}
  <input type="file" name="pdf" accept=".pdf,application/pdf" {{ '' if pending_name else 'required' }}>
  <input type="hidden" name="pending" value="{{ token or '' }}">
  <label>Subject</label><input class="wide" name="subject" value="{{ f.subject }}" required>
  <label>From</label><input class="wide" name="sender" value="{{ f.sender }}" required>
  <label>Date received</label><input type="date" name="date_received" value="{{ f.date_received }}" required>
  <label>Notes</label><textarea name="notes">{{ f.notes }}</textarea>
  <p class="muted">The ref no. (e.g. {{ example_ref }}) is created automatically. The PDF is copied into the storage folder; your original file is not touched.</p>
  <button>Save document</button> <a class="btn light" href="{{ url_for('index') }}">Cancel</a>
</form>
"""

DETAIL = """
<div class="row" style="justify-content:space-between"><h1>{{ d.ref }}</h1><a class="btn light" href="{{ url_for('index') }}">&larr; Back to list</a></div>
{% if error %}<div class="msg err">{{ error }} Your entries are still here.</div>{% endif %}
<div class="card grid">
  <b>Subject</b><span>{{ d.subject }}</span><b>From</b><span>{{ d.sender }}</span>
  <b>Date received</b><span>{{ d.received }}</span><b>Status</b><span><span class="badge">{{ d.status }}</span></span>
  <b>With</b><span>{{ d.dept or '-' }}</span>
  <b>Waiting</b><span>{% if d.waiting is none %}-{% else %}<span class="{{ 'late' if d.overdue }}">{{ d.waiting }} day(s){{ ' (overdue)' if d.overdue }}</span>{% endif %}</span>
  <b>Notes</b><span style="white-space:pre-wrap">{{ d.notes or '-' }}</span>
</div>

<div class="card">
  <h2>Files</h2>
  <div class="row" style="margin-bottom:8px"><b style="width:120px">Scanned PDF</b>
  {% if file_ok %}
    <button type="button" data-url="{{ url_for('open_target', ref=d.ref, which='file') }}" onclick="postJSON(this.dataset.url)">Open file</button>
    <button class="light" type="button" data-url="{{ url_for('open_target', ref=d.ref, which='folder') }}" onclick="postJSON(this.dataset.url)">Open folder</button>
    <span class="muted">{{ d.file }}</span>
  {% else %}<span class="late">{{ 'Missing: ' ~ file_path if d.file else 'No file linked.' }}</span>{% endif %}
  </div>
  <div class="row"><b style="width:120px">Signed copy</b>
  {% if d.signed and signed_ok %}
    <button type="button" data-url="{{ url_for('open_target', ref=d.ref, which='signed') }}" onclick="postJSON(this.dataset.url)">Open signed copy</button>
    <span class="muted">{{ d.signed }}</span>
  {% elif d.signed %}<span class="late">Missing: {{ signed_path }}</span>
  {% else %}<span class="muted">None attached.</span>{% endif %}
  </div>
  <form method="post" action="{{ url_for('attach_signed', ref=d.ref) }}" enctype="multipart/form-data" class="row" style="margin-top:12px">
    <label style="margin:0">{{ 'Replace signed copy' if d.signed else 'Attach signed copy' }}:</label>
    {% if pend.signed %}<span class="msg warn" style="margin:0;padding:4px 8px">Kept: {{ pend.signed[1] }}</span>{% endif %}
    <input type="file" name="signed" {{ '' if pend.signed else 'required' }}>
    <input type="hidden" name="pending" value="{{ pend.signed[0] if pend.signed else '' }}">
    <button class="light">Attach</button>
  </form>
</div>

{% if not file_ok or (d.signed and not signed_ok) %}
<div class="card" id="relink" style="border-color:#f1d79a">
  <h2>Relink a missing file</h2>
  <p class="muted">The file was moved, renamed or deleted, or the storage folder in Settings is wrong (for example, a changed drive letter: fix that once in Settings).
  To relink, choose the file again (it is copied into the storage folder) <b>or</b> type its current full path.</p>
  {% for which, label, ok in [('file','Scanned PDF',file_ok), ('signed','Signed copy', signed_ok or not d.signed)] if not ok %}
  <form method="post" action="{{ url_for('relink', ref=d.ref) }}" enctype="multipart/form-data" class="row" style="margin-bottom:10px">
    <input type="hidden" name="which" value="{{ which }}"><b style="width:120px">{{ label }}</b>
    {% if pend[which] %}<span class="msg warn" style="margin:0;padding:4px 8px">Kept: {{ pend[which][1] }}</span>{% endif %}
    <input type="file" name="newfile">
    <input type="hidden" name="pending" value="{{ pend[which][0] if pend[which] else '' }}">
    <span class="muted">or</span><input name="path" placeholder="C:\\path\\to\\file.pdf" style="min-width:280px" value="{{ relink_path if relink_which==which else '' }}">
    <button>Relink</button>
  </form>
  {% endfor %}
</div>
{% endif %}

<form class="card" method="post" action="{{ url_for('save', ref=d.ref) }}">
  <h2>Update status / route</h2>
  <div class="row">
    <div><label>Status</label><select name="status" id="status">{% for s in statuses %}<option {{ 'selected' if s==form_status }}>{{ s }}</option>{% endfor %}</select></div>
    <div><label>Route to department</label><select name="dept" id="dept">
      <option value="">- not routed -</option>
      {% for x in dept_options %}<option value="{{ x.name }}" {{ 'selected' if x.name==form_dept }}>{{ x.name }}{{ ' (disabled)' if not x.active }}</option>{% endfor %}
    </select></div>
    <div style="align-self:flex-end"><button>Save</button></div>
  </div>
  <p class="muted" id="autonote" hidden>Status changed to "{{ routed }}" because you picked a department. You can change it back before saving.</p>
  <p class="muted">Each save adds a row to the History sheet. Nothing is overwritten.</p>
</form>

<div class="card" style="padding:0"><h2 style="padding:14px 16px 0">History</h2>
<table><tr><th>Date</th><th>Status</th><th>Dept</th></tr>
{% for h in history %}<tr><td>{{ h.date }}</td><td>{{ h.status }}</td><td>{{ h.dept or '-' }}</td></tr>
{% else %}<tr><td colspan="3" class="muted">No history yet.</td></tr>{% endfor %}
</table></div>
<script>
(function(){
  const st=document.getElementById('status'), dp=document.getElementById('dept'), note=document.getElementById('autonote');
  const NEW={{ new_status|tojson }}, ROUTED={{ routed|tojson }};
  dp.addEventListener('change',function(){ if(dp.value && st.value===NEW){ st.value=ROUTED; note.hidden=false; } });
})();
</script>
"""

SETTINGS = """
<h1>Settings</h1>
{% if error %}<div class="msg err">{{ error }} Your entries are still here.</div>{% endif %}
<div class="card">
  <h2>Departments</h2>
  <table>
  <tr><th>Name</th><th>Active</th><th>Rename</th><th></th></tr>
  {% for x in depts %}
  <tr>
    <td>{{ x.name }}</td><td>{{ 'Yes' if x.active else 'No (hidden from routing)' }}</td>
    <td><form method="post" class="row"><input type="hidden" name="action" value="rename_dept"><input type="hidden" name="old" value="{{ x.name }}">
      <input name="new" value="{{ f.new if f.old==x.name else '' }}" placeholder="New name" required><button class="small light">Rename</button></form></td>
    <td><form method="post"><input type="hidden" name="action" value="toggle_dept"><input type="hidden" name="name" value="{{ x.name }}">
      <button class="small {{ 'danger' if x.active else '' }}">{{ 'Disable' if x.active else 'Enable' }}</button></form></td>
  </tr>
  {% endfor %}
  </table>
  <form method="post" class="row" style="margin-top:12px"><input type="hidden" name="action" value="add_dept">
    <input name="name" value="{{ f.name or '' }}" placeholder="New department name" required><button>Add department</button></form>
  <p class="muted">Renaming also updates documents currently with that department. Past History rows are never changed.</p>
</div>
<form class="card" method="post" style="max-width:760px">
  <h2>General</h2><input type="hidden" name="action" value="save_settings">
  <label>Storage folder (where PDFs are kept)</label><input class="wide" name="storage_folder" value="{{ s.storage_folder }}">
  <div class="muted">Links are saved relative to this folder. If the drive letter changes, update this one setting. Files are not moved.</div>
  <label>Export folder</label><input class="wide" name="export_folder" value="{{ s.export_folder }}">
  <label>Overdue after (days with the same department)</label><input type="number" min="0" max="3650" name="overdue_days" value="{{ s.overdue_days }}">
  <label>Ref format</label><input name="ref_format" value="{{ s.ref_format }}">
  <div class="muted">Tokens: {YYYY} year, {YY} 2-digit year, {MM} month, {SEQ:4} counter with 4 digits. The counter restarts when the year part changes. Next ref: <b>{{ example_ref }}</b></div>
  <p><button>Save settings</button></p>
</form>
<p class="muted">Data folder: {{ data_dir }}<br>Workbook: {{ tracker }} (backup before every save: {{ backup }})</p>
"""

MESSAGE = """
<div class="card"><h1>{{ heading }}</h1>
{% for e in errors %}<div class="msg err">{{ e }}</div>{% endfor %}
{% if fix %}<p>{{ fix }}</p>{% endif %}
<div class="row">{% if recheck %}<form method="post" action="{{ url_for('recheck') }}"><button>Check again</button></form>
<button class="light" type="button" onclick="postJSON('{{ url_for('open_excel') }}')">Open Excel file</button>{% endif %}
<a class="btn light" href="{{ url_for('index') }}">Go to documents</a></div></div>
"""


# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["MAX_CONTENT_LENGTH"] = CONFIG["MAX_UPLOAD_MB"] * 1024 * 1024
STARTUP_ERRORS: list[str] = []


def render(title, body_tpl, **ctx):
    body = render_template_string(body_tpl, **ctx)
    return render_template_string(BASE, title=title, body=body)


def message_page(heading, errors, fix=None, recheck=False, code=200):
    return render(heading, MESSAGE, heading=heading, errors=errors, fix=fix, recheck=recheck), code


@app.before_request
def block_if_invalid():
    if STARTUP_ERRORS and request.endpoint not in ("recheck", "open_excel", "ping", "static"):
        return message_page(
            "tracker.xlsx has a problem", STARTUP_ERRORS,
            fix=f"Open {TRACKER} in Excel, fix the sheet/column names listed above (row 1 of each sheet), "
                f"save, close Excel, then click Check again. Or restore tracker_backup.xlsx.",
            recheck=True, code=500)


@app.errorhandler(AppError)
def handle_app_error(e):
    return message_page("Something needs your attention", [str(e)])


@app.errorhandler(413)
def too_large(_e):
    return message_page("File too large", [f"Files must be smaller than {CONFIG['MAX_UPLOAD_MB']} MB."], code=413)


@app.get("/ping")
def ping():
    """Lets a second launch check that this copy is running."""
    return "DocTracker"


@app.post("/recheck")
def recheck():
    global STARTUP_ERRORS
    STARTUP_ERRORS = validate()
    if not STARTUP_ERRORS:
        flash("tracker.xlsx looks good.", "ok")
    return redirect(url_for("index"))


# ---- Main list ------------------------------------------------------------
@app.get("/")
def index():
    data = load_all()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    dept = request.args.get("dept", "")
    views = [doc_view(d, data["history"], data["settings"]) for d in reversed(data["docs"])]
    shown = []
    for v in views:
        if status and v["status"] != status:
            continue
        if dept and v["dept"] != dept:
            continue
        if q and q.lower() not in " ".join([v["ref"], v["subject"], v["sender"], v["notes"]]).lower():
            continue
        shown.append(v)
    dept_names = sorted({x["name"] for x in data["depts"]} | {v["dept"] for v in views if v["dept"]}, key=str.lower)
    return render("Documents", INDEX, docs=shown, total=len(views), q=q, status=status, dept=dept,
                  statuses=CONFIG["STATUSES"], dept_names=dept_names,
                  overdue_days=data["settings"]["overdue_days"], tracker=TRACKER)


# ---- Open file / folder / Excel -------------------------------------------
@app.post("/open/<ref>/<which>")
def open_target(ref, which):
    if which not in ("file", "signed", "folder"):
        return jsonify(ok=False, message="Unknown action.")
    try:
        data = load_all()
    except AppError as e:
        return jsonify(ok=False, message=str(e))
    doc = find_doc(data, ref)
    if not doc:
        return jsonify(ok=False, message=f"{ref} was not found in tracker.xlsx.")
    rel = text(doc["Signed Copy Link"] if which == "signed" else doc["File Link"])
    relink = url_for("detail", ref=ref) + "#relink"
    if not rel:
        return jsonify(ok=False, message=f"No file is linked to {ref}.", relink=relink)
    p = resolve(data["settings"], rel)
    if not p.is_file():
        return jsonify(ok=False, relink=relink,
                       message=f"File not found: {p}. It may have been moved, renamed or deleted, "
                               f"or the storage folder setting is wrong.")
    try:
        os_open(p, select=(which == "folder"))
    except OSError as e:
        return jsonify(ok=False, message=f"Windows could not open it ({e}).")
    return jsonify(ok=True, message=f"Opened {'the folder of ' if which == 'folder' else ''}{p.name}.")


@app.post("/open-excel")
def open_excel():
    if not TRACKER.is_file():
        return jsonify(ok=False, message=f"tracker.xlsx not found in {DATA_DIR}.")
    try:
        os_open(TRACKER)
    except OSError as e:
        return jsonify(ok=False, message=f"Windows could not open tracker.xlsx ({e}).")
    return jsonify(ok=True, message="Opening tracker.xlsx in Excel. Close it before saving in the app.")


# ---- Upload ---------------------------------------------------------------
@app.route("/upload", methods=["GET", "POST"])
def upload():
    data = load_all()
    s = data["settings"]
    example = next_ref([d["Ref No"] for d in data["docs"]], s["ref_format"], dt.date.today()) \
        if not check_ref_format(s["ref_format"]) else "(invalid ref format - fix it in Settings)"
    f = {"subject": "", "sender": "", "date_received": dt.date.today().isoformat(), "notes": ""}
    if request.method == "GET":
        return render("Upload", UPLOAD, f=f, error=None, token=None, pending_name=None, example_ref=example)

    f = {k: request.form.get(k, "").strip() for k in f}
    pdf, token = take_upload("pdf", request.form.get("pending"))

    def again(error, kept=True):
        return render("Upload", UPLOAD, f=f, error=error, kept=kept, token=token,
                      pending_name=pdf.name if pdf else None, example_ref=example)

    if not pdf:
        return again("Choose a PDF file.")
    if pdf.suffix.lower() != ".pdf" or not is_pdf(pdf):
        drop_pending(token)
        pdf = token = None
        return again("That file is not a PDF. Choose a scanned PDF file.")
    if not f["subject"] or not f["sender"]:
        return again("Subject and From are required.")
    try:
        received = dt.date.fromisoformat(f["date_received"])
    except ValueError:
        return again("Enter a valid date received.")
    if err := check_ref_format(s["ref_format"]):
        return again(err + " (Settings)")

    def mutate(wb, created):
        st = get_settings(wb)
        docs_ws, hist_ws = wb["Documents"], wb["History"]
        ref = next_ref([r["Ref No"] for r in sheet_rows(docs_ws)], st["ref_format"], dt.date.today())
        rel = main_file_name(ref, f["subject"])
        copy_into_storage(pdf, st, rel, created)
        r = append_row(docs_ws, {"Ref No": ref, "Subject": f["subject"], "From": f["sender"],
                                 "Status": CONFIG["STATUS_NEW"], "Current Dept": None, "Notes": f["notes"] or None})
        set_cell(docs_ws, r, "Date Received", received, DATE_FMT)
        set_link(docs_ws, r, "File Link", st, rel)
        h = append_row(hist_ws, {"Ref No": ref, "Status": CONFIG["STATUS_NEW"], "Dept": None})
        set_cell(hist_ws, h, "Date", dt.datetime.now().replace(microsecond=0), DATETIME_FMT)
        return ref

    try:
        ref = write_wb(mutate)
    except AppError as e:
        return again(str(e))
    except OSError as e:
        return again(f"Could not copy the PDF into the storage folder ({e}).")
    drop_pending(token)
    flash(f"Saved as {ref}. The PDF was copied into the storage folder.", "ok")
    return redirect(url_for("detail", ref=ref))


# ---- Detail ---------------------------------------------------------------
def render_detail(ref, error=None, form_status=None, form_dept=None, pend=None,
                  relink_which=None, relink_path=""):
    data = load_all()
    doc = find_doc(data, ref)
    if not doc:
        return message_page("Not found", [f"Document {ref} was not found in tracker.xlsx."], code=404)
    s = data["settings"]
    d = doc_view(doc, data["history"], s)
    fp, sp = resolve(s, d["file"]), resolve(s, d["signed"])
    history = sorted(
        ({"date": fmt_datetime(h["Date"]), "sort": to_datetime(h["Date"]) or dt.datetime.min,
          "status": text(h["Status"]), "dept": text(h["Dept"])}
         for h in data["history"] if text(h["Ref No"]) == ref),
        key=lambda h: h["sort"])
    dept_options = [x for x in data["depts"] if x["active"] or x["name"] == d["dept"]]
    if d["dept"] and d["dept"] not in [x["name"] for x in dept_options]:
        dept_options.append({"name": d["dept"], "active": False})
    pend = pend or {}
    pend = {"file": pend.get("file"), "signed": pend.get("signed")}
    return render(ref, DETAIL, d=d, error=error, statuses=CONFIG["STATUSES"],
                  form_status=form_status if form_status is not None else d["status"],
                  form_dept=form_dept if form_dept is not None else d["dept"],
                  dept_options=dept_options, history=history,
                  file_ok=bool(fp and fp.is_file()), file_path=fp,
                  signed_ok=bool(sp and sp.is_file()), signed_path=sp,
                  pend=pend, relink_which=relink_which, relink_path=relink_path,
                  new_status=CONFIG["STATUS_NEW"], routed=CONFIG["STATUS_ROUTED"])


@app.get("/doc/<ref>")
def detail(ref):
    return render_detail(ref)


@app.post("/doc/<ref>/save")
def save(ref):
    status = request.form.get("status", "")
    dept = request.form.get("dept", "").strip()
    data = load_all()
    doc = find_doc(data, ref)
    if not doc:
        return message_page("Not found", [f"Document {ref} was not found."], code=404)
    if status not in CONFIG["STATUSES"]:
        return render_detail(ref, "Choose a valid status.", status, dept)
    allowed = {x["name"] for x in data["depts"] if x["active"]} | {text(doc["Current Dept"])}
    if dept and dept not in allowed:
        return render_detail(ref, f'"{dept}" is not an active department.', status, dept)
    if status == text(doc["Status"]) and dept == text(doc["Current Dept"]):
        flash("Nothing changed, so no History row was added.", "warn")
        return redirect(url_for("detail", ref=ref))

    def mutate(wb, created):
        ws, hist = wb["Documents"], wb["History"]
        r = find_row(ws, ref)
        if not r:
            raise AppError(f"{ref} is no longer in tracker.xlsx.")
        set_cell(ws, r, "Status", status)
        set_cell(ws, r, "Current Dept", dept or None)
        h = append_row(hist, {"Ref No": ref, "Status": status, "Dept": dept or None})
        set_cell(hist, h, "Date", dt.datetime.now().replace(microsecond=0), DATETIME_FMT)

    try:
        write_wb(mutate)
    except AppError as e:
        return render_detail(ref, str(e), status, dept)
    flash(f"Saved: {status}" + (f", with {dept}." if dept else "."), "ok")
    return redirect(url_for("detail", ref=ref))


@app.post("/doc/<ref>/signed")
def attach_signed(ref):
    up, token = take_upload("signed", request.form.get("pending"))
    if not up:
        return render_detail(ref, "Choose a file to attach.")
    ext = up.suffix.lower() or ".pdf"

    def mutate(wb, created):
        st = get_settings(wb)
        ws = wb["Documents"]
        r = find_row(ws, ref)
        if not r:
            raise AppError(f"{ref} is no longer in tracker.xlsx.")
        rel = signed_file_name(ref, ext)
        copy_into_storage(up, st, rel, created)
        set_link(ws, r, "Signed Copy Link", st, rel)

    try:
        write_wb(mutate)
    except (AppError, OSError) as e:
        return render_detail(ref, str(e), pend={"signed": (token, up.name)})
    drop_pending(token)
    flash("Signed copy attached.", "ok")
    return redirect(url_for("detail", ref=ref))


@app.post("/doc/<ref>/relink")
def relink(ref):
    which = request.form.get("which")
    if which not in ("file", "signed"):
        return render_detail(ref, "Unknown file type.")
    header = "File Link" if which == "file" else "Signed Copy Link"
    typed = request.form.get("path", "").strip().strip('"')
    up, token = take_upload("newfile", request.form.get("pending"))
    pend = {which: (token, up.name)} if up else None

    def fail(msg):
        return render_detail(ref, msg, pend=pend, relink_which=which, relink_path=typed)

    if not up and not typed:
        return fail("Choose the file again, or type its full path.")
    if which == "file" and up and not is_pdf(up):
        drop_pending(token)
        pend = None
        return fail("That file is not a PDF.")

    def mutate(wb, created):
        st = get_settings(wb)
        ws = wb["Documents"]
        r = find_row(ws, ref)
        if not r:
            raise AppError(f"{ref} is no longer in tracker.xlsx.")
        subject = text(ws.cell(r, colmap(ws)["Subject"]).value)
        storage = storage_dir(st)
        if up:
            src = up
        else:
            src = Path(typed)
            if not src.is_absolute():
                src = storage / src
            if not src.is_file():
                raise AppError(f"No file at {src}. Check the path and try again.")
            try:   # already inside the storage folder: just link it, no copy
                rel = src.resolve().relative_to(storage.resolve()).as_posix()
                set_link(ws, r, header, st, rel)
                return
            except ValueError:
                pass
        rel = main_file_name(ref, subject) if which == "file" else signed_file_name(ref, src.suffix.lower())
        copy_into_storage(src, st, rel, created)
        set_link(ws, r, header, st, rel)

    try:
        write_wb(mutate)
    except (AppError, OSError) as e:
        return fail(str(e))
    drop_pending(token)
    flash("File relinked.", "ok")
    return redirect(url_for("detail", ref=ref))


# ---- Settings -------------------------------------------------------------
@app.route("/settings", methods=["GET", "POST"])
def settings():
    error = None
    form = {}
    if request.method == "POST":
        form = {k: v.strip() for k, v in request.form.items()}
        try:
            msg = settings_action(form)
            flash(msg, "ok")
            return redirect(url_for("settings"))
        except AppError as e:
            error = str(e)
    data = load_all()
    s = dict(data["settings"])
    if form.get("action") == "save_settings":   # keep what the user typed
        s.update({k: form.get(k, "") for k in ("storage_folder", "export_folder", "overdue_days", "ref_format")})
    example = next_ref([d["Ref No"] for d in data["docs"]], s["ref_format"], dt.date.today()) \
        if not check_ref_format(str(s["ref_format"])) else "(invalid format)"
    return render("Settings", SETTINGS, depts=data["depts"], s=s, f=form, error=error, example_ref=example,
                  data_dir=DATA_DIR, tracker=TRACKER, backup=BACKUP)


def settings_action(form) -> str:
    action = form.get("action")

    if action == "add_dept":
        name = form.get("name", "")
        if not name:
            raise AppError("Enter a department name.")

        def mutate(wb, created):
            if name.lower() in [d["name"].lower() for d in get_departments(wb)]:
                raise AppError(f'A department named "{name}" already exists.')
            append_row(wb["Departments"], {"Name": name, "Active": "Yes"})
        write_wb(mutate)
        return f'Department "{name}" added.'

    if action == "rename_dept":
        old, new = form.get("old", ""), form.get("new", "")
        if not new:
            raise AppError("Enter the new name.")

        def mutate(wb, created):
            ws = wb["Departments"]
            names = [d["name"] for d in get_departments(wb)]
            if new.lower() in [n.lower() for n in names if n != old]:
                raise AppError(f'A department named "{new}" already exists.')
            rows = [r for r in sheet_rows(ws) if text(r["Name"]) == old]
            if not rows:
                raise AppError(f'Department "{old}" was not found.')
            set_cell(ws, rows[0]["_row"], "Name", new)
            docs = wb["Documents"]
            for r in sheet_rows(docs):
                if text(r["Current Dept"]) == old:
                    set_cell(docs, r["_row"], "Current Dept", new)
        write_wb(mutate)
        return f'Renamed "{old}" to "{new}".'

    if action == "toggle_dept":
        name = form.get("name", "")

        def mutate(wb, created):
            ws = wb["Departments"]
            rows = [r for r in sheet_rows(ws) if text(r["Name"]) == name]
            if not rows:
                raise AppError(f'Department "{name}" was not found.')
            now_active = not is_active(rows[0]["Active"])
            set_cell(ws, rows[0]["_row"], "Active", "Yes" if now_active else "No")
            return now_active
        active = write_wb(mutate)
        return f'"{name}" {"enabled" if active else "disabled"}.'

    if action == "save_settings":
        storage = form.get("storage_folder", "").strip('"')
        export = form.get("export_folder", "").strip('"')
        fmt = form.get("ref_format", "")
        if not storage or not Path(storage).is_absolute():
            raise AppError("Storage folder must be a full path, e.g. D:\\DocTrackerData\\Files.")
        if not Path(storage).is_dir():
            raise AppError(f"Storage folder does not exist: {storage}. Check the drive letter, or create the folder first.")
        if not export or not Path(export).is_absolute():
            raise AppError("Export folder must be a full path.")
        try:
            Path(export).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise AppError(f"Could not create the export folder ({e}).")
        try:
            days = int(form.get("overdue_days", ""))
            if not 0 <= days <= 3650:
                raise ValueError
        except ValueError:
            raise AppError("Overdue days must be a whole number between 0 and 3650.")
        if err := check_ref_format(fmt):
            raise AppError(err)
        new = {"storage_folder": storage, "export_folder": export, "overdue_days": days, "ref_format": fmt}

        def mutate(wb, created):
            ws = wb["Settings"]
            existing = {text(r["Key"]): r["_row"] for r in sheet_rows(ws)}
            for k, v in new.items():
                if k in existing:
                    set_cell(ws, existing[k], "Value", v)
                else:
                    append_row(ws, {"Key": k, "Value": v})
            st = get_settings(wb)   # re-point every hyperlink at the (possibly new) storage folder
            docs = wb["Documents"]
            for r in sheet_rows(docs):
                for h in ("File Link", "Signed Copy Link"):
                    if text(r[h]):
                        set_link(docs, r["_row"], h, st, text(r[h]))
        write_wb(mutate)
        return "Settings saved."

    raise AppError("Unknown action.")


# ---- Sample data & export -------------------------------------------------
SAMPLES = [
    # subject, from, days ago received, [(days ago, status index, department), ...]
    ("Request for budget realignment", "City Treasurer's Office", 20, [(20, 0, ""), (18, 1, "Finance")]),
    ("Leave application - J. Santos", "Juan Santos", 9, [(9, 0, ""), (8, 1, "HR"), (3, 2, "HR")]),
    ("Contract review: IT maintenance", "ABC Tech Solutions", 5, [(5, 0, ""), (4, 1, "Legal")]),
    ("Invitation to regional summit", "Regional Office", 2, [(2, 0, "")]),
    ("Purchase request PR-118", "Supply Unit", 30, [(30, 0, ""), (29, 1, "Admin"), (25, 2, "Admin"), (22, 3, "Records")]),
    ("Records disposal schedule", "Records Section", 12, [(12, 0, ""), (10, 1, "Records")]),
]


@app.post("/sample")
def sample():
    statuses = CONFIG["STATUSES"]

    def mutate(wb, created):
        st = get_settings(wb)
        if err := check_ref_format(st["ref_format"]):
            raise AppError(err + " (Settings)")
        storage = storage_dir(st)
        depts = [d["name"] for d in get_departments(wb) if d["active"]]
        docs_ws, hist_ws = wb["Documents"], wb["History"]
        refs = [r["Ref No"] for r in sheet_rows(docs_ws)]
        now = dt.datetime.now().replace(second=0, microsecond=0)
        for subject, sender, ago, moves in SAMPLES:
            ref = next_ref(refs, st["ref_format"], dt.date.today())
            refs.append(ref)
            rel = main_file_name(ref, subject)
            dest = storage / rel
            created.append(dest)
            dest.write_bytes(make_pdf(["SAMPLE DOCUMENT - for demo only", "", f"Ref No: {ref}",
                                       f"Subject: {subject}", f"From: {sender}"]))
            final_status, final_dept = statuses[0], ""
            for m_ago, si, dname in moves:
                dname = dname if (not dname or dname in depts) else (depts[0] if depts else "")
                final_status, final_dept = statuses[min(si, len(statuses) - 1)], dname
                h = append_row(hist_ws, {"Ref No": ref, "Status": final_status, "Dept": dname or None})
                set_cell(hist_ws, h, "Date", now - dt.timedelta(days=m_ago), DATETIME_FMT)
            r = append_row(docs_ws, {"Ref No": ref, "Subject": subject, "From": sender, "Status": final_status,
                                     "Current Dept": final_dept or None, "Notes": "SAMPLE - fake demo document"})
            set_cell(docs_ws, r, "Date Received", dt.date.today() - dt.timedelta(days=ago), DATE_FMT)
            set_link(docs_ws, r, "File Link", st, rel)

    try:
        write_wb(mutate)
        flash("6 sample documents added.", "ok")
    except (AppError, OSError) as e:
        flash(str(e), "err")
    return redirect(url_for("index"))


@app.post("/export")
def export():
    try:
        folder = Path(load_all()["settings"]["export_folder"])
        folder.mkdir(parents=True, exist_ok=True)
        base = f"tracker_{dt.date.today():%Y-%m-%d}"
        dest, n = folder / f"{base}.xlsx", 2
        while dest.exists():
            dest, n = folder / f"{base}_{n}.xlsx", n + 1
        shutil.copy2(TRACKER, dest)
        flash(f"Exported to {dest}", "ok")
    except AppError as e:
        flash(str(e), "err")
    except OSError as e:
        flash(f"Export failed ({e}). Check the export folder in Settings.", "err")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Start-up
# ---------------------------------------------------------------------------
def find_free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def log_to_file_if_hidden():
    """With no console window (PyInstaller --noconsole) Python has nowhere to print.
    Send messages and error details to a log file instead, so nothing is silently lost."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        f = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except OSError:
        f = open(os.devnull, "w")
    sys.stdout = sys.stdout or f
    sys.stderr = sys.stderr or f
    print(f"\n--- DocTracker started {dt.datetime.now():%Y-%m-%d %H:%M:%S} ---")


def quiet_server():
    """Hide Flask's technical start-up banner and per-click log lines. Errors are still shown."""
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None


_MUTEX = None   # kept for the life of the program; Windows releases it when the program ends


def claim_single_instance() -> bool:
    """Windows only: True if this is the first copy of DocTracker for this user, False if one
    is already running. Uses a named mutex (a system-wide 'occupied' sign), so even two quick
    double-clicks cannot start two copies."""
    global _MUTEX
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    _MUTEX = k32.CreateMutexW(None, 0, "Local\\DocTrackerSingleInstance")
    return not (_MUTEX and ctypes.get_last_error() == 183)   # 183 = ERROR_ALREADY_EXISTS


def running_url() -> str | None:
    """Address of a DocTracker copy that is running and answering, or None."""
    try:
        url = URL_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not url.startswith("http://127.0.0.1:"):
        return None
    try:   # ProxyHandler({}): never send this through a company proxy
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url + "ping", timeout=2) as r:
            return url if r.read() == b"DocTracker" else None
    except Exception:
        return None


def main():
    global STARTUP_ERRORS
    log_to_file_if_hidden()
    quiet_server()

    # Already running? Just reopen the browser and stop.
    first = claim_single_instance()
    url = running_url()
    if not first and not url:
        for _ in range(30):            # the other copy may still be starting up (max 15 s)
            time.sleep(0.5)
            url = running_url()
            if url:
                break
    if url:
        print(f"DocTracker is already running at {url} - opening the browser.")
        webbrowser.open(url)
        return
    if not first:
        print("Another DocTracker copy seems stuck (not answering). Starting a new one.")

    if not TRACKER.exists():
        try:
            create_tracker()
            print(f"Created {TRACKER}")
        except OSError as e:
            STARTUP_ERRORS = [f"Could not create {TRACKER} ({e})."]
    if not STARTUP_ERRORS:
        STARTUP_ERRORS = validate()
    for e in STARTUP_ERRORS:
        print("PROBLEM:", e)
    clean_old_pending()
    port = find_free_port(CONFIG["START_PORT"])
    url = f"http://127.0.0.1:{port}/"
    try:
        URL_FILE.write_text(url, encoding="utf-8")
    except OSError as e:
        print(f"Could not write {URL_FILE} ({e}). A second launch may start a second copy.")
    print(f"DocTracker running at {url}  (press Ctrl+C to stop)")
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
