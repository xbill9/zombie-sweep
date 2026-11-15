"""Run the zombiescan checks for one region and store the findings.

Event: {"runId": str, "region": str, "global": bool}
With "global": true it runs only the account-wide checks (Route 53), once,
so a hosted zone is not reported seventeen times.

Read-only: zombiescan's checks make Describe, List and Get calls only.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3

from zombiescan import engine
from zombiescan.pricing import PriceTable

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
TTL_DAYS = 90

engine.load_packs()
PRICING = PriceTable.load()


def handler(event, _context):
    run_id = event["runId"]
    region = event["region"]
    want_global = bool(event.get("global"))
    checks = [c for c in engine.select_checks(()) if c.is_global == want_global]

    started = time.monotonic()
    result = engine.scan(boto3.Session(), [region], checks, PRICING, max_workers=8)
    seconds = round(time.monotonic() - started, 2)

    expires = int(time.time()) + TTL_DAYS * 86400
    with TABLE.batch_writer(overwrite_by_pkeys=["runId", "sk"]) as batch:
        for f in result.findings:
            d = f.to_dict()
            batch.put_item(
                Item={
                    "runId": run_id,
                    "sk": f"zombiescan#{d['region']}#{d['check']}#{d['resource_id']}",
                    "source": "zombiescan",
                    "check": d["check"],
                    "resourceId": d["resource_id"],
                    "resourceType": d["resource_type"],
                    "region": d["region"],
                    "reason": d["reason"],
                    "monthlyCost": Decimal(str(d["monthly_cost"])),
                    "approximate": d["approximate_cost"],
                    "remediation": d["remediation"],
                    "expiresAt": expires,
                }
            )

    return {
        "source": "zombiescan-global" if want_global else "zombiescan",
        "region": region,
        "findings": len(result.findings),
        "monthlyCost": result.total_monthly_cost,
        "errors": [f"{e.check}: {e.message}" for e in result.errors],
        "checksRun": len(checks),
        "seconds": seconds,
    }
