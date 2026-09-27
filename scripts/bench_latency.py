"""Latency of the public availability search on a running deployment.

    uv run python scripts/bench_latency.py https://webook-nu.vercel.app 200

Sends 10 warm-up requests, then N sequential requests over one keep-alive
connection with rotating date ranges. Reports client-observed round trip and
the server-side time from the Server-Timing header (Django, including Postgres).
"""

import http.client
import json
import re
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

base = urlparse(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000")
n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
Conn = http.client.HTTPSConnection if base.scheme == "https" else http.client.HTTPConnection
conn = Conn(base.netloc, timeout=30)


def one(i: int) -> tuple[float, float | None, int]:
    ci = date.today() + timedelta(days=1 + i % 60)
    co = ci + timedelta(days=1 + i % 5)
    path = f"/api/availability?check_in={ci}&check_out={co}&guests={1 + i % 3}"
    t0 = time.perf_counter()
    conn.request("GET", path, headers={"Accept": "application/json"})
    r = conn.getresponse()
    body = r.read()
    rtt = (time.perf_counter() - t0) * 1000
    m = re.search(r"app;dur=([\d.]+)", r.getheader("Server-Timing") or "")
    assert r.status == 200 and json.loads(body)["results"], (r.status, body[:200])
    return rtt, float(m.group(1)) if m else None, r.status


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


for i in range(10):
    one(1000 + i)
samples = [one(i) for i in range(n)]
rtt = [s[0] for s in samples]
app = [s[1] for s in samples if s[1] is not None]
summary = {
    "url": f"{base.scheme}://{base.netloc}/api/availability",
    "measured_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    "requests": n,
    "errors": sum(1 for s in samples if s[2] != 200),
    "client_ms": {"p50": round(pct(rtt, 50), 1), "p95": round(pct(rtt, 95), 1), "p99": round(pct(rtt, 99), 1), "mean": round(statistics.mean(rtt), 1), "max": round(max(rtt), 1)},
    "server_ms": {"p50": round(pct(app, 50), 1), "p95": round(pct(app, 95), 1), "max": round(max(app), 1)} if app else None,
}
print(json.dumps(summary, indent=2))
Path("reports").mkdir(exist_ok=True)
Path("reports/latency.json").write_text(json.dumps(summary, indent=2) + "\n")
