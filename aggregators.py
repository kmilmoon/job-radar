"""Remote-job aggregators: Jobgether (Lever board), Himalayas, Working Nomads,
and Get on Board.

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
    r"compliance|privacy|trust|ciberseguridad|seguridad de la informaci[oó]n|seguridad inform[aá]tica|"
    r"cumplimiento|protecci[oó]n de datos)\b", re.I)

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
    r"subject matter expert|domain expert|ai tutor|ai trainer|"
    r"director[a]? de operaciones|gerente de operaciones|jef[ea] de operaciones|responsable de operaciones|"
    r"riesgos?|auditor[ií]a|gobierno|jef[ea] de proyectos?|gerente de proyectos?|director[a]? de proyectos?)\b", re.I)

# Titles never worth showing (junior, pure sales/support, engineering-heavy)
EXCLUDE_RE = re.compile(
    r"\b(intern|internship|junior|graduate|entry[- ]level|sdr|bdr|account executive|"
    r"sales (rep|representative|development)|customer support|support agent|call center|"
    r"software engineer|developer|devops|sre|data engineer|machine learning engineer|"
    r"security guard|vigilante|guardia|warehouse|driver|nurse|physician|therapist|language (specialist|expert)|translator)\b", re.I)

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


RAW = {}


def probe(url, timeout=40):
    """GET JSON and remember what came back, so run.json shows why a feed is empty."""
    import json as _j
    import urllib.request as _r
    req = _r.Request(url, headers={"User-Agent": "Mozilla/5.0 (job-radar; personal job search)", "Accept": "application/json"})
    try:
        with _r.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            RAW[url.split("?")[0]] = f"HTTP {resp.status}, {len(body)} bytes"
            return _j.loads(body)
    except Exception as e:  # recorded, not raised: an empty feed must not stop the run
        RAW[url.split("?")[0]] = f"{type(e).__name__}: {str(e)[:120]}"
        return None


def jobgether():
    payload = fj.get_json("https://api.lever.co/v0/postings/jobgether?mode=json", timeout=60)
    RAW["jobgether_raw"] = len(payload or [])
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


def himalayas(pages=25):
    out = []
    for p in range(pages):
        payload = probe(f"https://himalayas.app/jobs/api?limit=100&offset={p * 100}")
        jobs = (payload or {}).get("jobs") or [] if isinstance(payload, dict) else []
        RAW["himalayas_raw"] = RAW.get("himalayas_raw", 0) + len(jobs)
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
    payload = probe("https://www.workingnomads.com/api/exposed_jobs/")
    RAW["workingnomads_raw"] = len(payload or []) if isinstance(payload, list) else 0
    out = []
    for j in payload or []:
        it = _item("workingnomads", str(j.get("url", ""))[-12:].strip("/"), j.get("title", ""),
                   j.get("company_name", ""), j.get("location") or "",
                   j.get("url"), j.get("pub_date"), None, None, j.get("description"),
                   [t for t in (j.get("tags") or "").split(",") if t] if isinstance(j.get("tags"), str) else j.get("tags"))
        if it:
            out.append(it)
    return out


def probe_raw(url, data=None, timeout=40, accept="application/json"):
    """GET (or POST JSON when data is given) and return the body text; records diagnostics in RAW."""
    import json as _j
    import urllib.request as _r
    body = _j.dumps(data).encode() if data is not None else None
    headers = {"User-Agent": "Mozilla/5.0 (job-radar; personal job search)", "Accept": accept}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = _r.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with _r.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
            RAW[url.split("?")[0]] = f"HTTP {resp.status}, {len(text)} bytes"
            return text
    except Exception as e:
        RAW[url.split("?")[0]] = f"{type(e).__name__}: {str(e)[:120]}"
        return None


GOB_QUERIES = ["security", "seguridad", "compliance", "cumplimiento", "grc", "riesgo", "risk", "ciso",
               "operations", "operaciones", "chief of staff", "program manager", "coo"]


def getonboard():
    import json as _j
    out, seen = [], set()
    for q in GOB_QUERIES:
        txt = probe_raw("https://www.getonbrd.com/api/v0/search/jobs?per_page=100&page=1&expand=%5B%22company%22%5D&query="
                        + q.replace(" ", "+"))
        try:
            payload = _j.loads(txt) if txt else {}
        except ValueError:
            payload = {}
        data = payload.get("data") or []
        RAW["getonboard_raw"] = RAW.get("getonboard_raw", 0) + len(data)
        for j in data:
            jid = str(j.get("id", ""))
            if jid in seen:
                continue
            seen.add(jid)
            a = j.get("attributes") or {}
            if not a.get("remote"):
                continue
            mod = a.get("remote_modality") or ""
            countries = a.get("countries") or []
            loc = "Remote " + ("(" + ", ".join(countries) + ")" if countries and mod == "remote_local" else "anywhere")
            if mod == "remote_local" and not any(re.search(r"spain|españa|europe", c, re.I) for c in countries):
                continue
            comp = None
            if a.get("min_salary") or a.get("max_salary"):
                comp = f"USD {a.get('min_salary') or ''}-{a.get('max_salary') or ''} /mes"
            company = (((a.get("company") or {}).get("data") or {}).get("attributes") or {}).get("name") or ""
            posted = a.get("published_at")
            if isinstance(posted, (int, float)):
                posted = datetime.fromtimestamp(posted, timezone.utc).strftime("%Y-%m-%d")
            url = (j.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{jid}"
            it = _item("getonboard", jid[-24:], a.get("title", ""), company, loc, url, str(posted or ""),
                       a.get("modality") or None, comp, (a.get("description") or "") + " " + (a.get("functions") or ""))
            if it:
                out.append(it)
    return out


# RSS feeds of remote job boards. Each entry: (source, url). A feed that fails or changes
# format is recorded in RAW and skipped; it never stops the run.
RSS_FEEDS = [
    ("weworkremotely", "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss"),
    ("weworkremotely", "https://weworkremotely.com/categories/all-other-remote-jobs.rss"),
    ("weworkremotely", "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"),
    ("weworkremotely", "https://weworkremotely.com/categories/remote-customer-support-jobs.rss"),
    ("jobspresso", "https://jobspresso.co/?feed=job_feed"),
    ("nodesk", "https://nodesk.co/remote-jobs/index.xml"),
    ("remoteco", "https://remote.co/remote-jobs/feed/"),
    ("dailyremote", "https://dailyremote.com/feed"),
]


def _rss_items(xml_text):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text)
    for item in root.iter("item"):
        d = {}
        for child in item:
            tag = child.tag.split("}")[-1].lower()
            d.setdefault(tag, (child.text or "").strip())
        yield d


def _rss_date(s):
    from email.utils import parsedate_to_datetime
    try:
        return parsedate_to_datetime(s).strftime("%Y-%m-%d")
    except Exception:
        return (s or "")[:10]


def rss_boards():
    import hashlib
    out = []
    for source, url in RSS_FEEDS:
        txt = probe_raw(url, accept="application/rss+xml, application/xml, text/xml")
        if not txt:
            continue
        try:
            entries = list(_rss_items(txt))
        except Exception as e:
            RAW[url] = f"XML error: {str(e)[:100]}"
            continue
        RAW[source + "_raw"] = RAW.get(source + "_raw", 0) + len(entries)
        for e in entries:
            title, company = e.get("title", ""), e.get("company", "")
            if source == "weworkremotely" and ": " in title and not company:
                company, title = title.split(": ", 1)
            loc = e.get("region") or e.get("location") or e.get("job_listing:location") or ""
            link = e.get("link") or e.get("guid") or ""
            jid = hashlib.sha1(link.encode()).hexdigest()[:10]
            it = _item(source, jid, title, company, loc, link, _rss_date(e.get("pubdate", "")),
                       e.get("type") or e.get("job_type"), None, e.get("description", ""))
            if it:
                out.append(it)
    return out


SOURCES = {"jobgether": jobgether, "himalayas": himalayas, "workingnomads": working_nomads,
           "getonboard": getonboard, "rss": rss_boards}


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
    counts["_raw"] = RAW
    return uniq, counts, errors
