#!/usr/bin/env python3
"""Group cost-measured-2026-11-15.txt into the article's cost table, rounded as printed."""
import pathlib, re
rows = {}
for line in (pathlib.Path(__file__).parent / "cost-measured-2026-11-15.txt").read_text().splitlines():
    m = re.match(r"(.+?)\s+\$([\d.]+)/sweep\s+\$([\d.]+)/month", line)
    if m:
        rows[m[1].strip()] = (float(m[2]), float(m[3]))
groups = {
    "Step Functions": ["Step Functions"],
    "Lambda (arm64)": ["Lambda scan", "Lambda optimizer", "Lambda report"],
    "DynamoDB, S3, CloudWatch Logs": ["DynamoDB writes", "S3 requests", "CloudWatch Logs"],
}
for name, keys in groups.items():
    print(f"{name:32} ${sum(rows[k][0] for k in keys):.5f} per sweep")
print(f"{'Total':32} ${rows['TOTAL'][0]:.4f} per sweep")
print(f"{'Per month, one sweep a day':32} ${rows['TOTAL'][1]:.2f}")
