#!/usr/bin/env python3
"""Daily fetcher for public ATS job boards (Ashby, Greenhouse, Lever).

Reads companies.json, finds which ATS each company uses (trying slug
variants), downloads the full public board, keeps postings whose title
matches security / GRC / compliance / risk keywords, and writes:

  data/jobs.json     all matching open postings, newest first
  data/ats_map.json  company -> detected ATS and slug (cache for next run)
  data/run.json      run time, counts and errors

Standard library only, so the GitHub Actions runner needs no installs.
"""
import html
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UA = {"User-Agent": "job-radar/1.0 (personal job search; contact via GitHub)"}

TITLE_RE = re.compile(
    r"\b(security|cyber|ciso|cso|grc|compliance|risk|privacy|trust|governance|"
    r"infosec|information security|soc ?2|iso ?27001|audit|assurance)\b",
    re.I,
)
# Titles that match the keywords but are never relevant
TITLE_EXCLUDE = re.compile(r"\b(guard|officer, armed|physical security guard|security guard)\b", re.I)

ENDPOINTS = {
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "greenhouse-eu": "https://boards-api.eu.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "lever-eu": "https://api.eu.lever.co/v0/postings/{slug}?mode=json",
}


def get_json(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (404, 400, 403, 410):
            return None
        raise
    except urllib.error.URLError as e:
        # A host that does not resolve (e.g. a regional endpoint that does not exist) means "no board here"
        if isinstance(getattr(e, "reason", None), socket.gaierror):
            return None
        raise
    except json.JSONDecodeError:
        return None


def slug_candidates(company):
    if company.get("slugs"):
        return company["slugs"]
    name = company["name"].lower()
    name = re.sub(r"\(.*?\)", "", name)
    base = re.sub(r"[^a-z0-9 .-]", "", name).strip()
    words = base.split()
    cands = [
        "".join(words),
        "-".join(words),
        base.replace(" ", "").replace(".", ""),
    ]
    trimmed = [w for w in words if w not in {"ai", "security", "inc", "group", "labs", "technologies", "systems"}]
    if trimmed and trimmed != words:
        cands += ["".join(trimmed), "-".join(trimmed)]
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def board_has_jobs(ats, payload):
    if payload is None:
        return False
    if ats == "ashby":
        return isinstance(payload, dict) and "jobs" in payload
    if ats.startswith("greenhouse"):
        return isinstance(payload, dict) and "jobs" in payload
    if ats.startswith("lever"):
        return isinstance(payload, list)
    return False


def detect(company, cache):
    """Return (ats, slug, payload) or (None, None, None)."""
    key = company["name"]
    order = []
    if key in cache:
        order.append((cache[key]["ats"], cache[key]["slug"]))
    forced = company.get("ats")
    for slug in slug_candidates(company):
        for ats in ENDPOINTS:
            if forced and not ats.startswith(forced):
                continue
            order.append((ats, slug))
    tried = set()
    for ats, slug in order:
        if (ats, slug) in tried:
            continue
        tried.add((ats, slug))
        payload = get_json(ENDPOINTS[ats].format(slug=slug))
        if board_has_jobs(ats, payload):
            return ats, slug, payload
        time.sleep(0.2)
    return None, None, None


def strip_html(s, limit=1800):
    if not s:
        return ""
    s = html.unescape(s)
    s = re.sub(r"<(script|style).*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def norm_ashby(company, slug, payload):
    out = []
    for j in payload.get("jobs", []):
        if not j.get("isListed", True):
            continue
        comp = j.get("compensation") or {}
        locs = [j.get("location") or ""] + [
            (s.get("location") if isinstance(s, dict) else str(s)) for s in (j.get("secondaryLocations") or [])
        ]
        out.append({
            "id": f"ashby-{slug}-{str(j.get('id', ''))[:8]}",
            "company": company["name"],
            "ats": "ashby",
            "title": j.get("title", ""),
            "location": "; ".join([l for l in locs if l])[:300],
            "remote": j.get("isRemote"),
            "workplace": j.get("workplaceType"),
            "employment": j.get("employmentType"),
            "posted": (j.get("publishedAt") or "")[:10],
            "url": j.get("jobUrl") or j.get("applyUrl"),
            "compensation": comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary"),
            "excerpt": strip_html(j.get("descriptionPlain") or j.get("descriptionHtml")),
        })
    return out


def norm_greenhouse(company, ats, slug, payload):
    out = []
    for j in payload.get("jobs", []):
        out.append({
            "id": f"gh-{slug}-{j.get('id')}",
            "company": company["name"],
            "ats": ats,
            "title": j.get("title", ""),
            "location": ((j.get("location") or {}).get("name") or "")[:300],
            "remote": None,
            "workplace": None,
            "employment": None,
            "posted": (j.get("first_published") or j.get("updated_at") or "")[:10],
            "url": j.get("absolute_url"),
            "compensation": None,
            "excerpt": strip_html(j.get("content")),
        })
    return out


def norm_lever(company, ats, slug, payload):
    out = []
    for j in payload:
        cats = j.get("categories") or {}
        sal = j.get("salaryRange") or {}
        comp = None
        if sal.get("min") or sal.get("max"):
            comp = f"{sal.get('currency', '')} {sal.get('min', '')}-{sal.get('max', '')} {sal.get('interval', '')}".strip()
        created = j.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, timezone.utc).strftime("%Y-%m-%d") if created else ""
        out.append({
            "id": f"lever-{slug}-{str(j.get('id', ''))[:8]}",
            "company": company["name"],
            "ats": ats,
            "title": j.get("text", ""),
            "location": "; ".join(filter(None, [cats.get("location")] + (cats.get("allLocations") or [])))[:300],
            "remote": (j.get("workplaceType") == "remote") if j.get("workplaceType") else None,
            "workplace": j.get("workplaceType"),
            "employment": cats.get("commitment"),
            "posted": posted,
            "url": j.get("hostedUrl"),
            "compensation": comp,
            "excerpt": strip_html(j.get("descriptionPlain") or j.get("description")),
        })
    return out


def normalise(company, ats, slug, payload):
    if ats == "ashby":
        return norm_ashby(company, slug, payload)
    if ats.startswith("greenhouse"):
        return norm_greenhouse(company, ats, slug, payload)
    return norm_lever(company, ats, slug, payload)


def relevant(job):
    t = job.get("title") or ""
    return bool(TITLE_RE.search(t)) and not TITLE_EXCLUDE.search(t)


def main():
    companies = json.loads((ROOT / "companies.json").read_text(encoding="utf-8"))
    DATA.mkdir(exist_ok=True)
    cache_path = DATA / "ats_map.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    jobs, errors, not_found, checked = [], [], [], 0
    for c in companies:
        if c.get("skip"):
            continue
        try:
            ats, slug, payload = detect(c, cache)
        except Exception as e:  # network trouble on one company must not stop the run
            errors.append(f"{c['name']}: {type(e).__name__}: {e}")
            continue
        if not ats:
            not_found.append(c["name"])
            continue
        checked += 1
        cache[c["name"]] = {"ats": ats, "slug": slug}
        found = [j for j in normalise(c, ats, slug, payload) if relevant(j)]
        jobs.extend(found)

    jobs.sort(key=lambda j: j.get("posted") or "", reverse=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (DATA / "jobs.json").write_text(json.dumps(jobs, ensure_ascii=False, indent=1), encoding="utf-8")
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (DATA / "run.json").write_text(json.dumps({
        "ranAt": now,
        "companies": len(companies),
        "boardsRead": checked,
        "matchingJobs": len(jobs),
        "noBoardFound": not_found,
        "errors": errors,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{now}: {checked} boards read, {len(jobs)} matching jobs, {len(not_found)} without a public board, {len(errors)} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
