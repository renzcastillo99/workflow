#!/usr/bin/env python3
"""Generate the Keycloak realm (runtime secrets from .env; output is GITIGNORED) + demo account sheet, then you start keycloak.compose.yml.
Demo users all share DEMO_PASSWORD and each has a pre-enrolled TOTP secret (so MFA is demonstrable and automatable)."""
from common import *
import json, base64, secrets, string
out = ROOT / "docker/keycloak/realm"; out.mkdir(parents=True, exist_ok=True)
USERS = [("admin.demo", "Ada", "Admin"), ("viewer.sales", "Sam", "Sales"), ("viewer.makati", "Mia", "Makati"), ("viewer.none", "Nico", "Nobody"), ("stranger.demo", "Sol", "Stranger")]
alphabet = string.ascii_letters + string.digits; sheet = ["# SYNTHETIC demo accounts for the LOCAL Keycloak only. Password for all: " + ENV["DEMO_PASSWORD"],
                                                          "# TOTP: add the base32 secret to any authenticator app (Microsoft Authenticator works), 6 digits, 30 s.", ""]
users = []; secrets_map = {}
for u, f, l in USERS:
    raw = "".join(secrets.choice(alphabet) for _ in range(20)); b32 = base64.b32encode(raw.encode()).decode().rstrip("=")
    secrets_map[u] = raw; sheet.append(f"{u}@feasibility.invalid   user={u}   totp_base32={b32}")
    users.append({"username": u, "email": f"{u}@feasibility.invalid", "emailVerified": True, "enabled": True, "firstName": f, "lastName": l,
                  "credentials": [{"type": "password", "value": ENV["DEMO_PASSWORD"], "temporary": False},
                                  {"type": "otp", "userLabel": "demo", "secretData": json.dumps({"value": raw}), "credentialData": json.dumps({"subType": "totp", "digits": 6, "counter": 0, "period": 30, "algorithm": "HmacSHA1"})}]})
realm = {"realm": "insightflow", "enabled": True, "sslRequired": "none", "registrationAllowed": False, "resetPasswordAllowed": False, "rememberMe": False,
         "bruteForceProtected": True, "failureFactor": 5, "waitIncrementSeconds": 60, "minimumQuickLoginWaitSeconds": 60, "maxFailureWaitSeconds": 900, "permanentLockout": False,
         "accessTokenLifespan": 300, "ssoSessionIdleTimeout": 1800, "ssoSessionMaxLifespan": 28800,
         "clients": [{"clientId": "insightflow-portal", "name": "InsightFlow portal", "protocol": "openid-connect", "enabled": True, "publicClient": False, "secret": ENV["KC_CLIENT_SECRET"],
                      "standardFlowEnabled": True, "implicitFlowEnabled": False, "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
                      "redirectUris": ["http://127.0.0.1:9000/auth/callback"], "webOrigins": [],
                      "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "http://127.0.0.1:9000/*"}}],
         "users": users}
(out / "insightflow-realm.json").write_text(json.dumps(realm, indent=1)); (ROOT / "docker/keycloak/demo_accounts.txt").write_text("\n".join(sheet) + "\n")
json.dump(secrets_map, open(ROOT / "docker/keycloak/.totp_raw.json", "w"))   # raw secrets for the e2e test only (gitignored dir)
print("realm written;", len(users), "users; sheet: docker/keycloak/demo_accounts.txt")
