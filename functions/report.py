"""Build the sweep report from one run's rows in DynamoDB.

Event: {"runId": str, "startedAt": str, "results": [per-branch summaries]}
Every total on the page is computed here, from the stored rows, and written
to findings.json beside the page so a reader can recompute it.
"""

from __future__ import annotations

import html
import json
import os
from collections import defaultdict
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

TABLE = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
S3 = boto3.client("s3")
BUCKET = os.environ["BUCKET_NAME"]

# Resource types that appear in Compute Optimizer's idle-recommendation list
# (docs.aws.amazon.com/compute-optimizer/latest/ug/view-idle-recommendations.html).
# A zombiescan finding on one of these is a type Compute Optimizer also reviews;
# every other finding is a type it does not review at all.
CO_TYPES = {"ec2-instance", "ebs-volume", "nat-gateway", "dynamodb-table", "rds-instance"}

# The page is public, so resource names and ids are shortened on it. The full
# rows stay in the DynamoDB table, which only the account can read.
MASK = os.environ.get("MASK_IDS", "true") == "true"


def mask(value: str) -> str:
    if not MASK or len(value) <= 8:
        return value
    head = value.split("-", 1)[0] + "-" if "-" in value[:6] else value[:4]
    return f"{head}…{value[-4:]}"


def _rows(run_id: str) -> list[dict]:
    rows, kwargs = [], {"KeyConditionExpression": Key("runId").eq(run_id)}
    while True:
        page = TABLE.query(**kwargs)
        rows.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            return rows
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _clean(row: dict) -> dict:
    out = {k: v for k, v in row.items() if k not in ("runId", "sk", "expiresAt")}
    out["monthlyCost"] = float(row.get("monthlyCost", 0))
    out["resourceId"] = mask(str(out.get("resourceId", "")))
    out["reason"] = str(out.get("reason", "")).replace(str(row.get("resourceId", "")), out["resourceId"])
    out.pop("remediation", None)
    return out


def summarise(rows: list[dict]) -> dict:
    by_source = defaultdict(lambda: {"findings": 0, "monthlyCost": 0.0})
    by_check = defaultdict(lambda: {"findings": 0, "monthlyCost": 0.0, "source": ""})
    regions = set()
    zs_ids, co_ids = set(), set()
    gap = {"findings": 0, "monthlyCost": 0.0}
    for r in rows:
        cost = round(r["monthlyCost"], 2)
        by_source[r["source"]]["findings"] += 1
        by_source[r["source"]]["monthlyCost"] += cost
        c = by_check[r["check"]]
        c["findings"] += 1
        c["monthlyCost"] += cost
        c["source"] = r["source"]
        regions.add(r["region"])
        if r["source"] == "zombiescan":
            zs_ids.add(r["resourceId"])
            if r.get("resourceType", "").lower() not in CO_TYPES:
                gap["findings"] += 1
                gap["monthlyCost"] += cost
        else:
            co_ids.add(r["resourceId"])
    for d in (*by_source.values(), *by_check.values(), gap):
        d["monthlyCost"] = round(d["monthlyCost"], 2)
    return {
        "findings": len(rows),
        "monthlyCost": round(sum(round(r["monthlyCost"], 2) for r in rows), 2),
        "bySource": dict(by_source),
        "byCheck": dict(sorted(by_check.items(), key=lambda kv: -kv[1]["monthlyCost"])),
        "outsideComputeOptimizerTypes": gap,
        "foundByBoth": len(zs_ids & co_ids),
        "regionsWithFindings": len(regions),
    }


def _money(v: float) -> str:
    return f"${v:,.2f}"


def render(run: dict, summary: dict, rows: list[dict], history: list[dict]) -> str:
    e = html.escape
    co = summary["bySource"].get("compute-optimizer", {"findings": 0, "monthlyCost": 0.0})
    zs = summary["bySource"].get("zombiescan", {"findings": 0, "monthlyCost": 0.0})
    gap = summary["outsideComputeOptimizerTypes"]
    check_rows = "".join(
        f"<tr><td>{e(k)}</td><td>{e(v['source'])}</td><td class=n>{v['findings']}</td>"
        f"<td class=n>{_money(v['monthlyCost'])}</td></tr>"
        for k, v in summary["byCheck"].items()
    )
    top = sorted(rows, key=lambda r: -r["monthlyCost"])[:25]
    finding_rows = "".join(
        f"<tr><td>{e(r['region'])}</td><td>{e(r['check'])}</td><td class=id>{e(r['resourceId'])}</td>"
        f"<td class=n>{_money(r['monthlyCost'])}</td><td>{e(r['reason'])}</td></tr>"
        for r in top
    )
    hist_rows = "".join(
        f"<tr><td>{e(h['startedAt'][:16].replace('T', ' '))}</td><td class=n>{h['findings']}</td>"
        f"<td class=n>{_money(h['monthlyCost'])}</td><td class=n>{h.get('computeOptimizer', 0)}</td></tr>"
        for h in reversed(history[-14:])
    )
    branches = run.get("results", [])
    secs = [b.get("seconds", 0) for b in branches]
    errors = [f"{b['region']}: {m}" for b in branches for m in b.get("errors", [])]
    err_html = (
        "<h2>Errors</h2><ul>" + "".join(f"<li>{e(m)}</li>" for m in errors[:30]) + "</ul>"
        if errors
        else ""
    )
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Zombie Sweep</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--mute:#666;--line:#ddd8cc;--acc:#b8471d;--card:#fff}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151513;--fg:#ecebe6;--mute:#a19f97;--line:#34322c;--acc:#f08a5d;--card:#1e1d1a}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 64px}}
h1{{font-size:1.9rem;margin:.2em 0}} h2{{margin-top:2em;font-size:1.2rem}}
.sub{{color:var(--mute)}} .tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:20px 0}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.tile b{{display:block;font-size:1.7rem;color:var(--acc)}} .tile span{{color:var(--mute);font-size:.9rem}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:.92rem}}
td,th{{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}}
.n{{text-align:right;white-space:nowrap}} .id{{font-family:ui-monospace,monospace;font-size:.82rem;word-break:break-all}}
footer{{margin-top:40px;color:var(--mute);font-size:.85rem}}
</style></head><body><main>
<h1>Zombie Sweep</h1>
<p class=sub>Daily serverless sweep for unused AWS resources. Run {e(run['runId'])}, started {e(run['startedAt'])},
{len(branches)} Lambda branches, slowest {max(secs, default=0):.1f} s.</p>
<div class=tiles>
<div class=tile><b>{_money(summary['monthlyCost'])}</b><span>estimated waste a month, {summary['findings']} findings in {summary['regionsWithFindings']} regions</span></div>
<div class=tile><b>{co['findings']}</b><span>Compute Optimizer idle recommendations ({_money(co['monthlyCost'])} a month)</span></div>
<div class=tile><b>{zs['findings']}</b><span>zombiescan findings ({_money(zs['monthlyCost'])} a month)</span></div>
<div class=tile><b>{_money(gap['monthlyCost'])}</b><span>{gap['findings']} findings on resource types outside Compute Optimizer's idle list</span></div>
</div>
<h2>By check</h2><div class=wrap><table><tr><th>Check</th><th>Source</th><th class=n>Findings</th><th class=n>Monthly</th></tr>{check_rows}</table></div>
<h2>Costliest findings</h2><div class=wrap><table><tr><th>Region</th><th>Check</th><th>Resource</th><th class=n>Monthly</th><th>Why</th></tr>{finding_rows}</table></div>
<h2>Recent sweeps</h2><div class=wrap><table><tr><th>Started (UTC)</th><th class=n>Findings</th><th class=n>Monthly</th><th class=n>Compute Optimizer</th></tr>{hist_rows}</table></div>
{err_html}
<footer>Estimates from AWS list prices, not your bill. The sweep is read-only and deleted nothing.
Every figure here is in <a href="findings.json">findings.json</a>.</footer>
</main></body></html>"""


def _history(entry: dict) -> list[dict]:
    try:
        body = S3.get_object(Bucket=BUCKET, Key="history.json")["Body"].read()
        history = json.loads(body)
    except S3.exceptions.NoSuchKey:
        history = []
    history = [h for h in history if h["runId"] != entry["runId"]] + [entry]
    return history[-90:]


def _put(key: str, body: str, content_type: str) -> None:
    S3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=body.encode(),
        ContentType=content_type,
        CacheControl="max-age=60",
    )


def _flatten(value):
    """Step Functions nests branch output: [[[zs, co], ...], global]."""
    if isinstance(value, dict):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _flatten(v)


def handler(event, _context):
    run_id = event["runId"]
    run = {
        "runId": run_id,
        "startedAt": event.get("startedAt") or datetime.now(timezone.utc).isoformat(),
        "results": list(_flatten(event.get("results", []))),
    }
    rows = [_clean(r) for r in _rows(run_id)]
    summary = summarise(rows)
    co = summary["bySource"].get("compute-optimizer", {"findings": 0})
    history = _history(
        {
            "runId": run_id,
            "startedAt": run["startedAt"],
            "findings": summary["findings"],
            "monthlyCost": summary["monthlyCost"],
            "computeOptimizer": co["findings"],
        }
    )
    doc = json.dumps(
        {"run": run, "summary": summary, "findings": rows}, indent=1, default=str
    )
    page = render(run, summary, rows, history)
    for prefix in (f"runs/{run_id}/", ""):
        _put(prefix + "findings.json", doc, "application/json")
        _put(prefix + "index.html", page, "text/html; charset=utf-8")
    _put("history.json", json.dumps(history, indent=1), "application/json")
    return {"runId": run_id, **{k: summary[k] for k in ("findings", "monthlyCost")},
            "outsideComputeOptimizerTypes": summary["outsideComputeOptimizerTypes"],
            "foundByBoth": summary["foundByBoth"]}
