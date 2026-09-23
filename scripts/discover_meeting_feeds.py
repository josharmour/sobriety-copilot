#!/usr/bin/env python3
"""Find Meeting Guide JSON feeds on candidate intergroup / area websites.

Most local A.A. (and several other fellowships') meeting lists run the
12 Step Meeting List (TSML) WordPress plugin, which publishes every meeting as
Meeting Guide JSON at a predictable URL. Some lists instead live in a
code4recovery Google-Sheets feed that the site links to. This script probes a
list of domains for either and reports what it finds, skipping feeds already
in src/meetings/feeds.py.

    python scripts/discover_meeting_feeds.py aatoronto.org ct-aa.org
    python scripts/discover_meeting_feeds.py -f domains.txt --json out.json
    python scripts/discover_meeting_feeds.py --generate-us   # guess domains for US/CA metros

Status per domain:
    ok          feed found (count = meetings, geo = meetings with coordinates)
    restricted  TSML answered 401: the site has turned off public sharing.
                Respect it — ask the office for a feed key instead.
    none        no feed found

Be courteous: this makes one or two requests per domain, with bounded
concurrency and an honest User-Agent. Don't run it in a loop.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.meetings.feeds import FEEDS, USER_AGENT  # noqa: E402

TSML_PATH = "/wp-admin/admin-ajax.php?action=meetings"
SHEETS_RE = re.compile(r"https://sheets\.code4recovery\.org/storage/[\w-]+\.json")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)

# Seeds for --generate-us: metro / state names combined with the naming
# patterns intergroups actually use (aa{x}.org, {x}aa.org, aa-{x}.org, ...).
METROS = """
albany albuquerque allentown anchorage annarbor asheville atlanta augusta austin
bakersfield baltimore batonrouge berkshire billings birmingham boise boston boulder
buffalo burlington calgary charleston charlotte chattanooga chicago cincinnati
cleveland coloradosprings columbia columbus dallas dayton daytona denver desmoines
detroit durham edmonton elpaso eugene evansville fargo fortcollins fortmyers
fortwayne fortworth fresno grandrapids greensboro greenville halifax hamilton
harrisburg hartford honolulu houston huntsville indianapolis jackson jacksonville
kansascity knoxville lafayette lakeland lancaster lansing lasvegas lexington
lincoln littlerock london longbeach longisland losangeles louisville lubbock madison
manchester memphis miami milwaukee minneapolis mobile modesto montgomery montreal
myrtlebeach naples nashville newhaven neworleans newyork norfolk oakland ocala
oklahomacity omaha orlando ottawa palmsprings pensacola peoria philadelphia phoenix
pittsburgh portland providence provo raleigh reading reno richmond riverside
roanoke rochester rockford sacramento saintlouis salem saltlake sanantonio
sandiego sanfrancisco sanjose santabarbara santacruz santafe sarasota savannah
scranton seattle shreveport siouxfalls southbend spokane springfield stockton
syracuse tacoma tallahassee tampa toledo toronto trenton tucson tulsa vancouver
ventura victoria virginiabeach washington westchester wichita wilmington winnipeg
worcester yakima york youngstown
alabama alaska arizona arkansas california colorado connecticut delaware florida
georgia hawaii idaho illinois indiana iowa kansas kentucky louisiana maine
maryland massachusetts michigan minnesota mississippi missouri montana nebraska
nevada newhampshire newjersey newmexico northcarolina northdakota ohio oregon
pennsylvania rhodeisland southcarolina southdakota tennessee texas utah vermont
virginia westvirginia wisconsin wyoming
""".split()
PATTERNS = ["aa{x}.org", "{x}aa.org", "aa-{x}.org", "{x}-aa.org", "{x}intergroup.org", "aa{x}.com"]


def generated_domains() -> list[str]:
    return [p.format(x=m) for m in METROS for p in PATTERNS]


def _count(data) -> tuple[int, int] | None:
    if isinstance(data, dict):
        data = data.get("meetings")
    if not isinstance(data, list) or not data:
        return None
    geo = sum(
        1 for m in data
        if isinstance(m, dict) and (m.get("latitude") or m.get("lat") or m.get("coordinates"))
    )
    return len(data), geo


async def probe(client: httpx.AsyncClient, domain: str, deep: bool) -> dict:
    domain = re.sub(r"^https?://", "", domain).strip("/ ")
    result = {"domain": domain, "status": "none"}
    for base in (f"https://www.{domain}", f"https://{domain}"):
        try:
            r = await client.get(base + TSML_PATH)
        except httpx.HTTPError:
            continue
        if r.status_code == 401:
            result.update(status="restricted", url=str(r.url))
            break
        try:
            counted = _count(r.json())
        except ValueError:
            counted = None
        if counted:
            result.update(status="ok", url=str(r.url), home=f"{r.url.scheme}://{r.url.host}",
                          count=counted[0], geo=counted[1])
            break
    if deep and result["status"] != "ok":
        # Look for a code4recovery Sheets feed linked from the site.
        for page in ("", "/meetings/", "/meetings"):
            try:
                r = await client.get(f"https://{domain}{page}")
            except httpx.HTTPError:
                continue
            m = SHEETS_RE.search(r.text)
            if not m:
                continue
            try:
                counted = _count((await client.get(m.group(0))).json())
            except (httpx.HTTPError, ValueError):
                counted = None
            if counted:
                result.update(status="ok", url=m.group(0), home=f"https://{domain}",
                              count=counted[0], geo=counted[1])
                break
    if result["status"] == "ok":
        try:
            r = await client.get(result["home"])
            t = TITLE_RE.search(r.text)
            if t:
                result["title"] = re.sub(r"\s+", " ", t.group(1)).strip()[:80]
        except httpx.HTTPError:
            pass
    return result


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("domains", nargs="*")
    ap.add_argument("-f", "--file", help="file with one domain per line")
    ap.add_argument("--generate-us", action="store_true", help="probe generated metro/state domains")
    ap.add_argument("--deep", action="store_true", help="also scan pages for code4recovery Sheets feeds")
    ap.add_argument("--json", help="write all results to this JSON file")
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()

    domains = list(args.domains)
    if args.file:
        domains += [ln.strip() for ln in Path(args.file).read_text().splitlines()
                    if ln.strip() and not ln.startswith("#")]
    if args.generate_us:
        domains += generated_domains()
    known = {re.sub(r"^https?://(www\.)?", "", f["home"]).strip("/") for f in FEEDS}
    domains = [d for d in dict.fromkeys(domains) if re.sub(r"^(www\.)", "", d) not in known]
    if not domains:
        ap.error("no new domains to probe")

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    ) as client:
        async def run(d: str) -> dict:
            async with sem:
                return await probe(client, d, args.deep)
        results = await asyncio.gather(*[run(d) for d in domains])

    known_urls = {f["url"] for f in FEEDS}
    found = [r for r in results if r["status"] == "ok" and r["url"] not in known_urls]
    # Several domains can redirect to the same site — keep one per feed URL.
    found = list({r["url"]: r for r in found}.values())
    found.sort(key=lambda r: -r["count"])
    restricted = [r for r in results if r["status"] == "restricted"]

    for r in found:
        print(f"{r['count']:6d} (geo {r['geo']:6d})  {r['domain']:32s} {r.get('title', '')}")
    print(f"\n{len(found)} new feeds, {sum(r['count'] for r in found)} meetings "
          f"({sum(r['geo'] for r in found)} with coordinates) from {len(domains)} domains probed")
    if restricted:
        print(f"{len(restricted)} restricted (401 — ask for a key): "
              + ", ".join(r["domain"] for r in restricted))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
