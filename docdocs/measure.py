"""Measure each ref with Lighthouse, so cards show real numbers.

    "measure": {"system": "demo", "page": "/products?delay=1500", "network": "slow-4g",
                "refs": ["before", "after"], "runs": 3, "lighthouse": "13.5.0"}

Each ref is checked out, built and served (see serve.py), then measured with
real throttling (--throttling-method=devtools), so late images and fonts
really arrive late. The medians and every run go to measurements.json next
to the storyboard, with the Lighthouse version, the profile and the date.
"""

import datetime
import json
import os
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urljoin

from docdocs.hosts import check_url
from docdocs.network import profile
from docdocs.serve import RefServer
from docdocs.storyboard import Storyboard

METRICS = {"cls": "cumulative-layout-shift", "lcp": "largest-contentful-paint"}


class MeasureError(Exception):
    pass


def chrome_path() -> str:
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        return pw.chromium.executable_path


def lighthouse_once(url: str, version: str, chrome: str) -> dict:
    npx = shutil.which("npx")
    if not npx:
        raise MeasureError("npx was not found. Install Node.js 18 or newer to run Lighthouse.")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        cmd = [
            npx, "-y", f"lighthouse@{version}", url,
            "--only-categories=performance", "--throttling-method=devtools",
            "--output=json", f"--output-path={out}", "--chrome-flags=--headless=new", "--quiet",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, env={**os.environ, "CHROME_PATH": chrome})
        if result.returncode != 0 or not out.exists():
            raise MeasureError(f"lighthouse failed:\n{(result.stdout + result.stderr)[-1500:]}")
        report = json.loads(out.read_text(encoding="utf-8"))
    return {key: report["audits"][audit]["numericValue"] for key, audit in METRICS.items()}


def measure(storyboard: Storyboard, runs: int | None = None, log=print) -> Path:
    m = storyboard.measure
    if not m:
        raise MeasureError(f"{storyboard.path.name} has no 'measure' block")
    if m.get("network", "slow-4g") != "slow-4g":
        raise MeasureError("phase 1 measures with the slow-4g profile only (Lighthouse's own mobile profile)")
    system_name = m.get("system") or next(iter(storyboard.systems))
    system = storyboard.systems[system_name]
    repo = storyboard.resolve(system.get("repo", "."))
    url = urljoin(system["baseUrl"], m.get("page", "/"))
    check_url(url)
    version = m.get("lighthouse", "13.5.0")
    runs = runs or int(m.get("runs", 3))
    chrome = chrome_path()

    results = {}
    for ref in m.get("refs", [None]):
        name = ref or "working tree"
        log(f"measuring {name}: {runs} run(s) of {url}")
        with RefServer(system, repo, ref, log=log):
            values = {k: [] for k in METRICS}
            for i in range(runs):
                one = lighthouse_once(url, version, chrome)
                for k, v in one.items():
                    values[k].append(v)
                log(f"  run {i + 1}: CLS {one['cls']:.3f}, LCP {one['lcp'] / 1000:.1f} s")
        results[name] = {k: {"runs": v, "median": statistics.median(v)} for k, v in values.items()}

    out = storyboard.base_dir / "measurements.json"
    out.write_text(
        json.dumps(
            {
                "date": datetime.date.today().isoformat(),
                "lighthouse": version,
                "network": profile("slow-4g")["label"],
                "runs": runs,
                "page": m.get("page", "/"),
                "refs": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    log(f"wrote {out}")
    return out
