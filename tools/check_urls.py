#!/usr/bin/env python3
"""Check whether job postings are still open.

Reads data/to_check.json: a list of {"id", "coll", "url"} written by the daily radar task
(or by hand), and writes data/url_status.json:
  {"checked": ISO, "items": {"<coll>/<id>": {"status": "open"|"closed"|"unknown", "reason", "http", "url"}}}

Rules, most reliable first:
- Ashby, Greenhouse and Lever: ask the public API for that exact posting.
- Workable: ask its public API for that job's shortcode.
- Anything else: fetch the page. HTTP 404/410, a redirect away from the job, or a page that
  says the job is closed means "closed". A normal page that still shows an apply button or the
  job title means "open". Pages that block robots (LinkedIn) stay "unknown".
"""
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
IN = ROOT / "data" / "to_check.json"
OUT = ROOT / "data" / "url_status.json"
UA = {"User-Agent": "Mozilla/5.0 (job-radar; personal job search)", "Accept": "text/html,application/json"}

CLOSED_RE = re.compile(
    r"(no longer (accepting|available|open)|position (has been|is) (filled|closed)|job (is )?(closed|expired|not found)|"
    r"this (job|role|position|posting) (is|has been) (closed|filled|removed|expired)|"
    r"isn'?t accepting applications|no longer accepting applications|job no longer exists|"
    r"page (you('| a)re looking for|not found)|404 not found|oferta (cerrada|caducada|ya no est[aá] disponible)|"
    r"esta oferta ya no|vacante cerrada|expired)", re.I)
APPLY_RE = re.compile(r"(apply (now|for this|for the)|submit (your )?application|aplicar|inscribirme|postular|candidatar)", re.I)


def fetch(url, timeout=30, accept_json=False):
    req = urllib.request.Request(url, headers=dict(UA, **({"Accept": "application/json"} if accept_json else {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read(600_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception as e:  # network trouble is "unknown", never "closed"
        return None, url, str(e)[:120]


def check_ashby(u):
    m = re.match(r"https?://jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{8,})", u)
    if not m:
        return None
    slug, jid = m.group(1), m.group(2)
    code, _, body = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", accept_json=True)
    if code != 200:
        return ("unknown", f"API de Ashby respondió {code}", code)
    try:
        ids = {j.get("id") for j in json.loads(body).get("jobs", [])}
    except ValueError:
        return ("unknown", "API de Ashby ilegible", code)
    return ("open", "Sigue en el tablón de Ashby", code) if jid in ids else ("closed", "Ya no está en el tablón de Ashby", code)


def check_greenhouse(u):
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", u)
    if not m:
        return None
    code, _, _ = fetch(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}", accept_json=True)
    if code == 200:
        return ("open", "Sigue publicada en Greenhouse", code)
    if code in (404, 410):
        return ("closed", "Greenhouse ya no la tiene", code)
    return ("unknown", f"Greenhouse respondió {code}", code)


def check_lever(u):
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{8,})", u)
    if not m:
        return None
    code, _, _ = fetch(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}", accept_json=True)
    if code == 200:
        return ("open", "Sigue publicada en Lever", code)
    if code in (404, 410):
        return ("closed", "Lever ya no la tiene", code)
    return ("unknown", f"Lever respondió {code}", code)


def check_workable(u):
    m = re.search(r"apply\.workable\.com/([^/]+)/j/([A-Z0-9]+)", u)
    if not m:
        return None
    code, _, body = fetch(f"https://apply.workable.com/api/v2/accounts/{m.group(1)}/jobs/{m.group(2)}", accept_json=True)
    if code == 200:
        try:
            st = (json.loads(body).get("state") or "").lower()
        except ValueError:
            st = ""
        if st in ("closed", "archived"):
            return ("closed", "Workable la marca como cerrada", code)
        return ("open", "Sigue publicada en Workable", code)
    if code in (404, 410):
        return ("closed", "Workable ya no la tiene", code)
    return None  # fall back to the page


def check_generic(u):
    host = urlparse(u).netloc.lower()
    if "linkedin.com" in host:
        return ("unknown", "LinkedIn no deja comprobarlo automáticamente", None)
    code, final, body = fetch(u)
    if code is None:
        return ("unknown", "No se pudo abrir: " + body, None)
    if code in (404, 410):
        return ("closed", f"La página da error {code}", code)
    if code >= 400:
        return ("unknown", f"La página respondió {code}", code)
    fp, op = urlparse(final).path.rstrip("/"), urlparse(u).path.rstrip("/")
    if op and fp != op and op.split("/")[-1] not in final:
        return ("closed", "La página redirige fuera de la oferta (suele indicar que está cerrada)", code)
    text = re.sub(r"<[^>]+>", " ", body)
    if CLOSED_RE.search(text):
        return ("closed", "La página dice que la oferta está cerrada", code)
    if APPLY_RE.search(text):
        return ("open", "La página sigue mostrando la opción de aplicar", code)
    return ("unknown", "La página carga, pero no está claro si admite candidaturas", code)


def check(u):
    for fn in (check_ashby, check_greenhouse, check_lever, check_workable):
        try:
            r = fn(u)
        except Exception as e:
            r = ("unknown", f"Error comprobando: {str(e)[:80]}", None)
        if r:
            return r
    return check_generic(u)


def main():
    items = json.loads(IN.read_text(encoding="utf-8")) if IN.exists() else []
    out = {}
    for it in items:
        url = (it.get("url") or "").strip()
        key = f"{it.get('coll', 'jobs')}/{it.get('id')}"
        if not url.startswith("http"):
            out[key] = {"status": "unknown", "reason": "Sin URL", "http": None, "url": url}
            continue
        status, reason, code = check(url)
        out[key] = {"status": status, "reason": reason, "http": code, "url": url}
    OUT.write_text(json.dumps({"checked": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": out},
                              ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    counts = {}
    for v in out.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
