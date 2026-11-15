#!/usr/bin/env python3
"""Record the demo: a real sweep, started and watched live, then the report.

Every number on screen comes from the execution it starts or from the report
that execution publishes. Output: media/zombie-sweep-demo.mp4 (1280x720).
"""

import json
import pathlib
import subprocess
import threading
import time

import boto3
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"
URL = "https://diomvue77lcq.cloudfront.net/"
STACK = "zombie-sweep"
cfn = boto3.client("cloudformation", region_name="us-east-1")
sfn = boto3.client("stepfunctions", region_name="us-east-1")
SM = next(
    o["OutputValue"]
    for o in cfn.describe_stacks(StackName=STACK)["Stacks"][0]["Outputs"]
    if o["OutputKey"] == "StateMachineArn"
)
REGIONS = sorted(
    r["RegionName"] for r in boto3.client("ec2", region_name="us-east-1").describe_regions()["Regions"]
)

CSS = """
:root{--bg:#141412;--fg:#efede6;--mute:#a19f97;--acc:#f08a5d;--ok:#5fbf77;--line:#34322c}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--fg);font:20px/1.4 system-ui,sans-serif;height:720px;overflow:hidden}
.card{display:flex;flex-direction:column;justify-content:center;height:720px;padding:0 90px}
h1{font-size:64px;margin:0 0 10px} h2{font-size:38px;margin:0 0 18px} .mute{color:var(--mute)}
.big{font-size:30px;line-height:1.5} .acc{color:var(--acc)}
#cap{position:fixed;left:50%;transform:translateX(-50%);bottom:28px;max-width:1000px;background:#000d;color:#fff;
 font:600 24px/1.35 system-ui;padding:12px 22px;border-radius:10px;z-index:9;text-align:center}
#cap:empty{display:none}
.grid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-top:18px}
.r{border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:15px;min-height:74px}
.r b{display:block;font-size:16px} .r span{display:block;color:var(--mute);font-size:13px}
.r.zs{border-color:var(--acc)} .r.done{border-color:var(--ok);background:#1d2a20}
.top{display:flex;justify-content:space-between;align-items:baseline}
#clock{font:600 40px ui-monospace,monospace;color:var(--acc)}
"""


def page_html(body):
    return f"<!doctype html><meta charset=utf-8><style>{CSS}</style><body>{body}<div id=cap></div></body>"


def cap(p, text):
    p.evaluate("t=>{document.getElementById('cap').textContent=t}", text)


class Watch:
    """Start a sweep and collect each Lambda result as Step Functions reports it."""

    def __init__(self):
        self.arn = None
        self.started = None
        self.results = []
        self.status = "RUNNING"
        self.output = None

    def run(self):
        self.started = time.monotonic()
        self.arn = sfn.start_execution(stateMachineArn=SM)["executionArn"]
        seen = set()
        while True:
            kw = {"executionArn": self.arn, "maxResults": 1000}
            events = []
            while True:
                page = sfn.get_execution_history(**kw)
                events += page["events"]
                if "nextToken" not in page:
                    break
                kw["nextToken"] = page["nextToken"]
            for e in events:
                d = e.get("taskSucceededEventDetails")
                if d and e["id"] not in seen:
                    seen.add(e["id"])
                    payload = json.loads(d["output"]).get("Payload", {})
                    if "source" in payload:
                        self.results.append(payload)
            desc = sfn.describe_execution(executionArn=self.arn)
            if desc["status"] != "RUNNING":
                self.status = desc["status"]
                self.output = json.loads(desc.get("output") or "{}")
                self.seconds = (desc["stopDate"] - desc["startDate"]).total_seconds()
                return
            time.sleep(0.7)


def main():
    MEDIA.mkdir(exist_ok=True)
    tiles = "".join(
        f"<div class=r id='r-{r}'><b>{r}</b><span class=zsv>zombiescan …</span><span class=cov>Compute Optimizer …</span></div>"
        for r in REGIONS
    )
    with sync_playwright() as w:
        b = w.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(
            viewport=dict(width=1280, height=720),
            record_video_dir=str(MEDIA / "raw"),
            record_video_size=dict(width=1280, height=720),
        )
        p = ctx.new_page()

        # 1. Title
        p.set_content(page_html(
            "<div class=card><h1>Zombie Sweep</h1>"
            "<div class='big mute'>A daily serverless sweep for AWS resources nobody is using,<br>"
            "and what they cost.</div></div>"))
        p.wait_for_timeout(4500)
        cap(p, "AWS already ships an idle-resource finder: Compute Optimizer.")
        p.wait_for_timeout(4500)
        cap(p, "It reviews 12 resource types. This sweep checks what sits outside that list.")
        p.wait_for_timeout(5000)

        # 2. Architecture
        svg = (ROOT / "docs/architecture.svg").read_text()
        p.set_content(page_html(f"<div style='padding:30px 60px;background:#fbfaf7;height:720px'>{svg}</div>"))
        cap(p, "One CloudFormation stack. EventBridge Scheduler starts Step Functions once a day.")
        p.wait_for_timeout(6000)
        cap(p, "A Map state fans out to every enabled region: zombiescan checks and Compute Optimizer side by side.")
        p.wait_for_timeout(6500)
        cap(p, "Findings land in DynamoDB. A report Lambda totals them and publishes to S3 and CloudFront.")
        p.wait_for_timeout(6000)

        # 3. A live sweep
        p.set_content(page_html(
            "<div style='padding:40px 60px'><div class=top><h2>Live sweep</h2><div id=clock>0.0 s</div></div>"
            f"<div class=mute id=exec>starting…</div><div class=grid>{tiles}</div></div>"))
        cap(p, "Starting a real sweep now.")
        watch = Watch()
        t = threading.Thread(target=watch.run)
        t.start()
        shown = 0
        while t.is_alive() or shown < len(watch.results):
            if watch.started:
                p.evaluate("s=>{document.getElementById('clock').textContent=s}",
                           f"{time.monotonic() - watch.started:.1f} s")
            if watch.arn:
                p.evaluate("s=>{document.getElementById('exec').textContent=s}",
                           "execution " + watch.arn.rsplit(":", 1)[-1])
            for r in watch.results[shown:]:
                p.evaluate(
                    """r=>{const el=document.getElementById('r-'+r.region); if(!el) return;
                    if(r.source==='zombiescan'){el.querySelector('.zsv').textContent=
                      'zombiescan '+r.findings+' · $'+r.monthlyCost.toFixed(2); el.classList.add('zs')}
                    if(r.source==='compute-optimizer'){el.querySelector('.cov').textContent=
                      'Compute Optimizer '+r.findings}
                    if(el.querySelector('.zsv').textContent.indexOf('…')<0 &&
                       el.querySelector('.cov').textContent.indexOf('…')<0) el.classList.add('done')}""",
                    r,
                )
                shown += 1
            if shown > 8:
                cap(p, "Each tile is one region: two Lambda functions report as they finish.")
            p.wait_for_timeout(250)
        t.join()
        o = watch.output
        p.evaluate("s=>{document.getElementById('clock').textContent=s}", f"{watch.seconds:.1f} s")
        cap(p, f"{watch.status}: {len(REGIONS)} regions in {watch.seconds:.0f} seconds. "
               f"{o['findings']} findings, ${o['monthlyCost']:.2f} a month.")
        p.wait_for_timeout(6000)
        co = sum(r["findings"] for r in watch.results if r["source"] == "compute-optimizer")
        cap(p, f"Compute Optimizer: {co} idle recommendations. "
               f"{o['outsideComputeOptimizerTypes']['findings']} findings are types it does not review.")
        p.wait_for_timeout(6500)

        # 4. The report
        p.goto(URL + f"runs/{o['runId']}/index.html")  # a fresh key: never in the CDN cache
        p.add_style_tag(content="#cap{position:fixed;left:50%;transform:translateX(-50%);bottom:28px;max-width:1000px;"
                        "background:#000d;color:#fff;font:600 24px/1.35 system-ui;padding:12px 22px;border-radius:10px;"
                        "z-index:9;text-align:center}#cap:empty{display:none}")
        p.evaluate("()=>{const d=document.createElement('div');d.id='cap';document.body.append(d)}")
        p.wait_for_timeout(1500)
        cap(p, "The report it just published, served from S3 through CloudFront.")
        p.wait_for_timeout(5500)
        p.evaluate("document.querySelectorAll('h2')[0].scrollIntoView({behavior:'smooth'})")
        cap(p, "By check: old container images, an unused AMI, secrets nobody reads, a zone that resolves nothing.")
        p.wait_for_timeout(6500)
        p.evaluate("document.querySelectorAll('h2')[1].scrollIntoView({behavior:'smooth'})")
        cap(p, "Every finding names the resource, its monthly cost and why it looks unused.")
        p.wait_for_timeout(6500)
        p.evaluate("document.querySelectorAll('h2')[2].scrollIntoView({behavior:'smooth'})")
        cap(p, "Each daily sweep adds a row, so new waste shows up the day after it appears.")
        p.wait_for_timeout(5500)

        # 5. Cost
        cost = (ROOT / "docs/evidence/cost-measured-2026-11-15.txt").read_text().splitlines()
        total = next(l for l in cost if l.startswith("TOTAL")).split()[1].split("/")[0]
        p.set_content(page_html(
            "<div class=card><h2>What it costs</h2>"
            f"<div class=big><span class=acc>{total}</span> per sweep, measured from billed Lambda time and state transitions.<br>"
            "Nothing runs between sweeps.<br><br>"
            "<span class=mute>Read-only role. Deletes nothing. Public page shortens resource ids.</span><br><br>"
            "<span class=mute>github.com/xbill9/zombie-sweep</span></div></div>"))
        cap(p, "No servers, no pipeline. ./deploy.sh creates the whole stack.")
        p.wait_for_timeout(7000)
        cap(p, "")
        p.wait_for_timeout(1500)
        video = p.video.path()
        ctx.close()
        b.close()

    out = MEDIA / "zombie-sweep-demo.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "20", "-movflags", "+faststart", str(out)],
        check=True,
    )
    pathlib.Path(video).unlink()
    print("run", o["runId"], watch.status, f"{watch.seconds:.1f}s", o["findings"], o["monthlyCost"])
    print("wrote", out)


if __name__ == "__main__":
    main()
