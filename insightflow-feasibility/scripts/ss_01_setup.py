#!/usr/bin/env python3
"""Connect Superset to the READ-ONLY synthetic source (SQL Lab exposure, DML, CTAS/CVAS, file upload all off)."""
from common import *; from ssapi import SS
ss = SS(); assert ss.login("admin", ENV["SS_ADMIN_PASSWORD"])
body = {"database_name": "clientdata_ro", "sqlalchemy_uri": f"postgresql+psycopg2://insightflow_ro:{ENV['DATA_PG_RO_PASSWORD']}@if-data-pg:5432/clientdata",
        "expose_in_sqllab": False, "allow_dml": False, "allow_run_async": False, "allow_ctas": False, "allow_cvas": False, "allow_file_upload": False}
print(ss.call("POST", "/api/v1/database/", json=body)[:2])
