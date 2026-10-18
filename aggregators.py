"""Remote-job aggregators: Jobgether (Lever board), Himalayas and Working Nomads.

Each source is read through its public JSON feed. Postings are tagged:
  track "core" = security / GRC / compliance titles (main tab)
  track "alt"  = adjacent roles Lara could do well (operations, chief of staff,
                 programme management, risk, AI governance, training, expert AI work)
Only postings open to Spain / Europe / EMEA / worldwide are kept.
"""
import re
from datetime import datetime, timezone

import fetch_jobs as fj

CORE_RE = re.compile(
    r"\b(security|cyber\w*|ciso|grc|infosec|information security|soc ?2|iso ?27001|"
    r"compliance|privacy|trust)\b", re.I)

ALT_RE = re.compile(
    r"\b(coo|chief operating|chief of staff|head of operations|operations (lead|manager|director)|"
    r"director of operations|vp,? operations|business operations|strategy (&|and) operations|bizops|"
    r"integrator|eos implementer|fractional (coo|operations)|"
    r"program(me)? (manager|director|lead)|portfolio manager|pmo|delivery (manager|lead|director)|"
    r"operational risk|risk (manager|lead|director|officer)|third[- ]party risk|vendor risk|"
    r"governance|internal audit|audit (manager|lead)|regulatory|dora|nis2|"
    r"ai (governance|policy|risk|safety)|responsible ai|"
    r"trust (&|and) safety|customer trust|"
    r"implementation (manager|lead|consultant)|transformation|process (excellence|improvement)|"
    r"instructor|trainer|teacher|lecturer|docente|formador|"
    r"subject matter expert|domain expert|ai tutor|ai trainer)\b", re.I)

# Titles never worth showing (junior, pure sales/support, engineering-heavy)
EXCLUDE_RE = re.compile(
    r"\b(intern|internship|junior|graduate|entry[- ]level|sdr|bdr|account executive|"
    r"sales (rep|representative|development)|customer support|support agent|call center|"
    r"software engineer|developer|devops|sre|data engineer|machine learning engineer|"
    r"security guard|warehouse|driver|nurse|physician|therapist)\b", re.I)

GEO_OK_RE = re.compile(
    r"(spain|españa|espana|europe|emea|european union|\beu\b|worldwide|anywhere|global|"
    r"remote\s*$|^remote|cet|cest|gmt|utc[+-]?[0-2]?\b)", re.I)
GEO_BAD_RE = re.compile(r"\b(us only|usa only|united states only|must be (located|based) in the us)\b", re.I)


def classify(title):
    t = title or ""
    if EXCLUDE_RE.search(t):
        return None
    if CORE_RE.search(t):
        return "core"
    if ALT_RE.search(t):
        return "alt"
    return None


def geo_ok(loc):
    loc = (loc or "").strip()
    if not loc:
        return True  # unknown: keep, the radar checks eligibility later
    if GEO_BAD_RE.search(loc):
        return False
    return bool(GEO_OK_RE.search(loc))


def _item(source, id_, title, company, location, url, posted, employment=None, comp=None, excerpt="", tags=None):
    track = classify(title)
    if not track or not geo_ok(location):
        return None
    return {
        "id": f"{source}-{id_}",
        "source": source,
        "track": track,
        "title": title,
        "company": company,
        "location": (location or "")[:300],
        "employment": employment,
        "posted": (posted or "")[:10],
        "url": url,
        "compensation": comp,
        "tags": tags or [],
        "excerpt": fj.strip_html(excerpt, 1200),
    }


def jobgether():
    payload = fj.get_json("https://api.lever.co/v0/postings/jobgether?mode=json", timeout=60)
    out = []
    for j in payload or []:
        cats = j.get("categories") or {}
        loc = "; ".join(filter(None, [cats.get("location")] + (cats.get("allLocations") or [])))
        created = j.get("createdAt")
        posted = datetime.fromtimestamp(created / 1000, timezone.utc).strftime("%Y-%m-%d") if created else ""
        title = re.sub(r"^\s*jobgether\s*[-–:]\s*", "", j.get("text", ""), flags=re.I)
        it = _item("jobgether", str(j.get("id", ""))[:8], title, "Jobgether (empresa oculta)", loc,
                   j.get("hostedUrl"), posted, cats.get("commitment"), None,
                   j.get("descriptionPlain") or j.get("description"))
        if it:
            out.append(it)
    return out


def himalayas(pages=6):
    out = []
    for p in range(pages):
        payload = fj.get_json(f"https://himalayas.app/jobs/api?limit=100&offset={p * 100}", timeout=40)
        jobs = (payload or {}).get("jobs") or []
        if not jobs:
            break
        for j in jobs:
            loc = ", ".join(j.get("locationRestrictions") or []) or "Worldwide"
            comp = None
            if j.get("minSalary") or j.get("maxSalary"):
                comp = f"{j.get('currency', '')} {j.get('minSalary', '')}-{j.get('maxSalary', '')}".strip()
            posted = j.get("pubDate")
            if isinstance(posted, (int, float)):
                posted = datetime.fromtimestamp(posted / (1000 if posted > 1e11 else 1), timezone.utc).strftime("%Y-%m-%d")
            it = _item("himalayas", str(j.get("guid") or j.get("applicationLink") or j.get("title"))[-12:],
                       j.get("title", ""), j.get("companyName", ""), loc,
                       j.get("applicationLink") or j.get("guid"), str(posted or ""),
                       j.get("employmentType"), comp, j.get("excerpt") or j.get("description"),
                       j.get("categories"))
            if it:
                out.append(it)
    return out


def working_nomads():
    payload = fj.get_json("https://www.workingnomads.com/api/exposed_jobs/", timeout=40)
    out = []
    for j in payload or []:
        it = _item("workingnomads", str(j.get("url", ""))[-12:].strip("/"), j.get("title", ""),
                   j.get("company_name", ""), j.get("location") or "",
                   j.get("url"), j.get("pub_date"), None, None, j.get("description"),
                   [t for t in (j.get("tags") or "").split(",") if t] if isinstance(j.get("tags"), str) else j.get("tags"))
        if it:
            out.append(it)
    return out


SOURCES = {"jobgether": jobgether, "himalayas": himalayas, "workingnomads": working_nomads}


def run():
    items, errors, counts = [], [], {}
    for name, fn in SOURCES.items():
        try:
            got = fn()
            counts[name] = len(got)
            items.extend(got)
        except Exception as e:  # one source failing must not stop the others
            errors.append(f"{name}: {type(e).__name__}: {e}")
            counts[name] = 0
    seen, uniq = set(), []
    for it in items:
        key = (it["title"].lower(), (it["company"] or "").lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(it)
    uniq.sort(key=lambda j: j.get("posted") or "", reverse=True)
    return uniq, counts, errors
