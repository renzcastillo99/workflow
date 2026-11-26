"""Portal settings. Secrets come from environment variables (dev: the gitignored ../.env). Nothing secret is hard-coded."""
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1); os.environ.setdefault(k, v)
def _b(name, default): return os.environ.get(name, default).lower() in ("1", "true", "yes")
PORTAL_URL = os.environ.get("PORTAL_URL", "http://127.0.0.1:9000")
COOKIE_SECURE = PORTAL_URL.startswith("https://")
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "http://127.0.0.1:8180/realms/insightflow")      # Entra: https://login.microsoftonline.com/<tenant-id>/v2.0
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "insightflow-portal")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET") or os.environ.get("KC_CLIENT_SECRET", "")
OIDC_REQUIRED_TID = os.environ.get("OIDC_REQUIRED_TID", "")                                  # Entra tenant lock (ignored if empty)
REQUIRE_MFA_CLAIM = _b("REQUIRE_MFA_CLAIM", "false")                                          # reject logins whose token lacks an MFA 'amr'
OIDC_SESSION_SECRET = os.environ.get("PORTAL_SESSION_SECRET", "")
SESSION_IDLE_MIN = int(os.environ.get("SESSION_IDLE_MIN", "30"))
SESSION_ABS_MIN = int(os.environ.get("SESSION_ABS_MIN", "480"))
SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://127.0.0.1:8088")                       # same URL for server and browser in the mini version
SVC_USER, SVC_PASSWORD = os.environ.get("SVC_USER", "portal-svc"), os.environ.get("SVC_PASSWORD", "")
INGEST_DSN = f"host=127.0.0.1 port=15432 dbname=clientdata user=insightflow_ingest password={os.environ.get('INGEST_PW', '')}"
STALE_AFTER_MINUTES = int(os.environ.get("STALE_AFTER_MINUTES", "1440"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(60 * 1024 * 1024)))
MAX_ROWS = int(os.environ.get("MAX_ROWS", "2000000"))
DB_PATH = Path(os.environ.get("PORTAL_DB", str(Path(__file__).resolve().parent / "data" / "portal.db")))
KNOWN_BRANCHES = ["Makati", "Cebu", "Davao", "Quezon City", "Pasig", "Taguig", "Iloilo", "Baguio", "Cagayan de Oro", "Bacolod", "Zamboanga", "Clark"]
for need in ("OIDC_CLIENT_SECRET", "OIDC_SESSION_SECRET", "SVC_PASSWORD"):
    if not globals()[need]: raise SystemExit(f"missing secret {need} (run scripts/p2_00_env.sh)")
