#!/usr/bin/env python3
"""Print the CURRENT 6-digit authenticator code for a demo user, so you can sign in without installing an authenticator app.
Usage: python3 scripts/p2_totp.py viewer.sales        (DEMO/TEST ACCOUNTS ONLY - reads the gitignored docker/keycloak/.totp_raw.json)
Note: Keycloak rejects a code that was already used, so if a login fails, wait for the next 30-second window and run this again."""
import sys, json, hmac, hashlib, struct, time
from pathlib import Path
raw = json.loads((Path(__file__).resolve().parent.parent / "docker/keycloak/.totp_raw.json").read_text())
user = sys.argv[1] if len(sys.argv) > 1 else sys.exit("usage: p2_totp.py <username>   (one of: " + ", ".join(raw) + ")")
h = hmac.new(raw[user].encode(), struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest(); o = h[19] & 15
code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7fffffff) % 1000000
print(f"{code:06d}   (valid for about {30 - int(time.time()) % 30} more seconds)")
