"""InsightFlow feasibility config for Apache Superset. All secrets come from environment (never committed)."""
import os
from datetime import timedelta
SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]                       # image REFUSES to boot with the default key (verified)
SQLALCHEMY_DATABASE_URI = "postgresql+psycopg2://superset:{}@ss-pg:5432/superset".format(os.environ["SS_DB_PASSWORD"])
FEATURE_FLAGS = {"EMBEDDED_SUPERSET": True, "DASHBOARD_RBAC": True}
# --- embedding (guest tokens issued by OUR portal backend) ---
GUEST_ROLE_NAME = "InsightFlowGuest"
GUEST_TOKEN_JWT_SECRET = os.environ["SS_GUEST_TOKEN_SECRET"]
GUEST_TOKEN_JWT_EXP_SECONDS = 300                                     # short-lived
GUEST_TOKEN_JWT_ALGO = "HS256"
# --- caching (Redis) ---
CACHE_CONFIG = {"CACHE_TYPE": "RedisCache", "CACHE_DEFAULT_TIMEOUT": 300, "CACHE_KEY_PREFIX": "sscache_", "CACHE_REDIS_URL": "redis://ss-redis:6379/0"}
STORE_CACHE_KEYS_IN_METADATA_DB = True   # REQUIRED for /api/v1/cachekey/invalidate to work (default False => invalidate silently does nothing; verified)
# /api/v1/cachekey/invalidate deletes through cache_manager.cache (CACHE_CONFIG) only; chart data lives in DATA_CACHE_CONFIG.
# They MUST share the same Redis DB + key prefix or invalidation silently misses the data (verified).
DATA_CACHE_CONFIG = dict(CACHE_CONFIG)
# --- session / hardening ---
PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get("SS_SESSION_MINUTES", "480")))
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = os.environ.get("SS_COOKIE_SECURE", "false") == "true"   # MUST be true behind HTTPS in any real deployment
WTF_CSRF_ENABLED = True
RATELIMIT_APPLICATION = os.environ.get("SS_RATELIMIT", "50 per second")   # per-IP global limit (Superset default 50/s; verified: 429 under burst). Raise only for single-IP proxies/benchmarks.
RATELIMIT_STORAGE_URI = "redis://ss-redis:6379/2"   # shared counter across gunicorn workers (in-memory default is per-process)
AUTH_RATE_LIMITED = True
AUTH_RATE_LIMIT = "5 per 40 second"
TALISMAN_ENABLED = True
# Embedding: allow framing ONLY by the portal origin (CSP frame-ancestors allowlist); default is SAMEORIGIN which blocks the portal (verified in browser).
import copy
from superset import config as _default_cfg
TALISMAN_CONFIG = copy.deepcopy(_default_cfg.TALISMAN_CONFIG)
_origins = [o for o in os.environ.get("SS_PORTAL_ORIGINS", "").split(",") if o]
TALISMAN_CONFIG["frame_options"] = None                      # drop X-Frame-Options (cannot express an allowlist)
TALISMAN_CONFIG["content_security_policy"]["frame-ancestors"] = ["'self'"] + _origins
# Theming (Superset 6.x token-based theme) - evaluated against spec colours
THEME_DEFAULT = {"token": {"colorPrimary": "#2563EB", "colorBgBase": "#FFFFFF", "colorTextBase": "#0F172A", "colorBgLayout": "#F1F5F9", "colorBorder": "#CBD5E1",
                           "fontFamily": "Inter, system-ui, -apple-system, 'Segoe UI', Arial, sans-serif", "borderRadius": 8}, "algorithm": "default"}
THEME_DARK = {"token": {"colorPrimary": "#60A5FA", "colorBgBase": "#1E293B", "colorTextBase": "#E2E8F0", "colorBgLayout": "#0F172A", "colorBorder": "#334155",
                        "fontFamily": "Inter, system-ui, -apple-system, 'Segoe UI', Arial, sans-serif", "borderRadius": 8}, "algorithm": "dark"}
ENABLE_PROXY_FIX = True
SQLLAB_CTAS_NO_LIMIT = False
