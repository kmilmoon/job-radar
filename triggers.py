#!/usr/bin/env python3
"""Vía B: external triggers for the radar (standard library only).

Runs after fetch_jobs.py in the same workflow. Writes:
  data/vendor_customers.json  customers of Vanta / Drata / Secureframe: full snapshot + the ones that are new
                              since the previous snapshot (weekly)
  data/partners.json          service partners of those platforms (monthly)
  data/auditors.json          audit partners of those platforms, EMEA flagged (monthly)
  data/triggers_state.json    when each part last ran
and adds a "triggers" section to data/run.json. A source that cannot be read is recorded as an error
and handed to the daily web search; it never stops the run.

Set FORCE=1 to run the weekly and monthly parts regardless of the date.
"""
import gzip
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8", "Accept-Language": "en"}
NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
ERRORS = []

EMEA_RE = re.compile(
    r"\b(emea|europe|european|eu\b|uk\b|united kingdom|england|london|ireland|dublin|spain|españa|madrid|barcelona|valencia|"
    r"portugal|lisbon|france|paris|germany|deutschland|berlin|munich|netherlands|amsterdam|belgium|brussels|"
    r"luxembourg|switzerland|zurich|austria|vienna|italy|milan|rome|denmark|copenhagen|sweden|stockholm|norway|oslo|"
    r"finland|helsinki|estonia|tallinn|latvia|lithuania|poland|warsaw|czech|prague|romania|bucharest|greece|athens|"
    r"cyprus|malta|israel|tel aviv|uae|dubai|south africa|nordics?|dach|benelux|baltics?|global|worldwide|international)\b",
    re.I)
VCISO_RE = re.compile(r"\b(v-?ciso|virtual ciso|fractional (ciso|security|cso)|ciso[- ]as[- ]a[- ]service|cisoaas|"
                      r"security leadership as a service|outsourced ciso|interim ciso)\b", re.I)


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return body.decode("utf-8", "replace")


def try_get(url, label):
    try:
        return get(url)
    except Exception as e:
        ERRORS.append(f"{label}: {url}: {type(e).__name__}: {str(e)[:120]}")
        return None


def text_of(page, limit=20000):
    page = re.sub(r"<(script|style|noscript|svg).*?</\1>", " ", page, flags=re.S | re.I)
    page = re.sub(r"<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page)).strip()[:limit]


def load(name, default):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save(name, obj):
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def due(state, key, days):
    if os.environ.get("FORCE") == "1":
        return True
    last = state.get(key)
    if not last:
        return True
    try:
        return NOW - datetime.fromisoformat(last) >= timedelta(days=days)
    except ValueError:
        return True


def pretty(slug):
    words = re.sub(r"[-_]+", " ", slug).strip().split()
    return " ".join(w.upper() if len(w) <= 2 and w.isalpha() and w not in ("of", "on", "to", "in") else w.capitalize()
                    for w in words)


def sitemap_urls(url, label, depth=0):
    """(loc, lastmod) pairs from a sitemap or sitemap index (one level of nesting)."""
    body = try_get(url, label)
    if not body:
        return []
    out = []
    for block in re.findall(r"<(url|sitemap)>(.*?)</\1>", body, flags=re.S):
        loc = re.search(r"<loc>\s*([^<\s]+)\s*</loc>", block[1])
        mod = re.search(r"<lastmod>\s*([^<\s]+)\s*</lastmod>", block[1])
        if not loc:
            continue
        if block[0] == "sitemap" and depth == 0:
            out.extend(sitemap_urls(loc.group(1), label, 1))
        else:
            out.append((loc.group(1), (mod.group(1) if mod else "")[:10]))
    return out


# ---------------------------------------------------------------- vendor customers (weekly)
VENDOR_CUSTOMERS = {
    "Vanta": {"sitemaps": ["https://www.vanta.com/sitemap.xml"],
              "pattern": re.compile(r"^https://www\.vanta\.com/customers/([a-z0-9-]+)/?$", re.I)},
    "Secureframe": {"sitemaps": ["https://secureframe.com/sitemap.xml"],
                    "pattern": re.compile(r"^https://secureframe\.com/customers/([a-z0-9-]+)/?$", re.I)},
    "Drata": {"sitemaps": ["https://drata.com/sitemap.xml"],
              "pattern": re.compile(r"^https://drata\.com/(?:customers|case-studies|customer-stories)/([a-z0-9-]+)/?$", re.I)},
}


def vendor_customers(prev):
    prev_keys = {(c["vendor"], c["slug"]) for c in prev.get("customers", [])}
    had_prev = {v for v in VENDOR_CUSTOMERS if any(c["vendor"] == v for c in prev.get("customers", []))}
    customers, new, counts = [], [], {}
    for vendor, cfg in VENDOR_CUSTOMERS.items():
        seen = set()
        for sm in cfg["sitemaps"]:
            for loc, mod in sitemap_urls(sm, f"{vendor} customers"):
                m = cfg["pattern"].match(loc)
                if not m or m.group(1) in seen:
                    continue
                seen.add(m.group(1))
                item = {"vendor": vendor, "slug": m.group(1), "name": pretty(m.group(1)), "url": loc, "lastmod": mod}
                customers.append(item)
                if vendor in had_prev and (vendor, item["slug"]) not in prev_keys:
                    new.append({**item, "firstSeen": TODAY})
        counts[vendor] = len(seen)
        if not seen:
            ERRORS.append(f"{vendor} customers: nothing readable; covered by the daily web search")
    # Keep vendors that failed this time from the previous snapshot, so a temporary error does not reset them
    for c in prev.get("customers", []):
        if counts.get(c["vendor"], 0) == 0:
            customers.append(c)
    # Customers added since the previous snapshot stay "new" for 30 days
    cutoff = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
    keep = [c for c in prev.get("new", []) if c.get("firstSeen", "") >= cutoff and (c["vendor"], c["slug"]) not in {(n["vendor"], n["slug"]) for n in new}]
    recent_cut = (NOW - timedelta(days=45)).strftime("%Y-%m-%d")
    recent = sorted([c for c in customers if c.get("lastmod", "") >= recent_cut], key=lambda c: c["lastmod"], reverse=True)
    return {"generatedAt": NOW.isoformat(timespec="seconds"), "counts": counts,
            "baseline": [v for v in VENDOR_CUSTOMERS if v not in had_prev and counts.get(v)],
            "new": new + keep, "recentlyUpdated": recent[:60],
            "note": "new = case studies that appeared since the previous weekly snapshot (empty on the first run of a vendor: "
                    "that run is the baseline). recentlyUpdated = pages whose sitemap date is in the last 45 days: "
                    "may be new or just edited, check the page before scoring.",
            "customers": sorted(customers, key=lambda c: (c["vendor"], c["slug"]))}


# ---------------------------------------------------------------- partners and auditors (monthly)
def vanta_partner_cards():
    """Every card of vanta.com/partners/find-a-partner (Webflow list, 12 per page)."""
    cards, page = [], 1
    while page <= 60:
        url = "https://www.vanta.com/partners/find-a-partner" + (f"?429fc2b6_page={page}" if page > 1 else "")
        body = try_get(url, "Vanta partners")
        if not body:
            break
        chunks = body.split('class="partners_grid-card"')[1:]
        for c in chunks:
            title = re.search(r'fs-cmsfilter-field="title"[^>]*>([^<]+)<', c)
            if not title:
                continue
            tags = [html.unescape(t).strip() for t in re.findall(r'fs-cmsfilter-field="filters"[^>]*>([^<]+)<', c)]
            desc = re.search(r'integrations_grid-card-desc[^>]*>(.*?)</p>', c, re.S)
            link = re.search(r'href="(https?://[^"]+)"[^>]*class="button-secondary', c) or \
                re.search(r'class="button-secondary[^"]*"[^>]*href="(https?://[^"]+)"', c)
            cards.append({"name": html.unescape(title.group(1)).strip(), "tags": tags,
                          "description": text_of(desc.group(1)) if desc else "",
                          "web": link.group(1) if link else "", "partnerOf": "Vanta",
                          "source": "https://www.vanta.com/partners/find-a-partner"})
        if f"429fc2b6_page={page + 1}" not in body or not chunks:
            break
        page += 1
    return cards


def nuxt_payload(page):
    m = re.search(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return None
    arr = json.loads(m.group(1))
    seen = {}

    def r(i, depth=0):
        if not isinstance(i, int) or i < 0 or i >= len(arr) or depth > 60:
            return None
        if i in seen:
            return seen[i]
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("ShallowReactive", "Reactive", "Ref", "ShallowRef", "EmptyRef",
                                                         "EmptyShallowRef", "NuxtError", "Set", "Map", "Date"):
                out = r(v[1], depth + 1) if len(v) > 1 and isinstance(v[1], int) else None
            else:
                out = [r(x, depth + 1) for x in v]
        elif isinstance(v, dict):
            out = {}
            seen[i] = out
            for k, x in v.items():
                out[k] = r(x, depth + 1)
            return out
        else:
            out = v
        seen[i] = out
        return out
    return r(0)


def walk(obj, fn):
    if isinstance(obj, dict):
        fn(obj)
        for v in obj.values():
            walk(v, fn)
    elif isinstance(obj, list):
        for v in obj:
            walk(v, fn)


def secureframe_partner_cards():
    body = try_get("https://secureframe.com/partner-directory", "Secureframe partners")
    if not body:
        return []
    try:
        root = nuxt_payload(body)
    except Exception as e:
        ERRORS.append(f"Secureframe partners: payload not parsed: {type(e).__name__}: {e}")
        return []
    found = {}

    def take(d):
        if "slug" in d and "title" in d and "website" in d and isinstance(d.get("slug"), str):
            found[d["slug"]] = d
    walk(root, take)
    cards = []
    for slug, d in found.items():
        callouts = d.get("callouts") or []
        tags = [c.get("title") or c.get("name") or "" for c in callouts if isinstance(c, dict)]
        cards.append({"name": str(d.get("title") or slug).strip(), "tags": [t for t in tags if t],
                      "description": text_of(" ".join(str(d.get(k) or "") for k in ("headline", "description")), 1500),
                      "web": d.get("website") or "", "partnerOf": "Secureframe", "availability": d.get("availability"),
                      "source": f"https://secureframe.com/partner-directory/partner/{slug}"})
    if not cards:
        ERRORS.append("Secureframe partners: no entries found in the page payload")
    return cards


ATS_RE = re.compile(r"https?://(?:jobs\.ashbyhq\.com|job-boards(?:\.eu)?\.greenhouse\.io|boards\.greenhouse\.io|jobs\.(?:eu\.)?lever\.co|"
                    r"[a-z0-9-]+\.(?:recruitee|teamtailor|workable|personio|bamboohr|breezy)\.(?:com|de|hr|io))/[^\"'\s<>]*", re.I)


def enrich(card):
    """Visit the partner's own website: region, vCISO/fractional offer, careers page and ATS."""
    out = dict(card)
    out.update({"region": "", "vciso": bool(VCISO_RE.search(" ".join(card.get("tags", [])) + " " + card.get("description", ""))),
                "careers": "", "ats": "", "webChecked": False})
    web = card.get("web")
    if web:
        try:
            page = get(web, timeout=15)
            out["webChecked"] = True
            text = text_of(page, 30000)
            hits = sorted({m.group(0).strip().lower() for m in EMEA_RE.finditer(text + " " + card.get("description", ""))})
            out["regionHints"] = hits[:12]
            if VCISO_RE.search(text):
                out["vciso"] = True
            ats = ATS_RE.search(page)
            if ats:
                out["ats"] = ats.group(0)
            car = re.search(r"""href=["']([^"']*(?:careers|jobs|join-us|work-with-us|vacancies|trabaja)[^"']*)["']""", page, re.I)
            if car:
                href = car.group(1)
                out["careers"] = href if href.startswith("http") else web.rstrip("/") + "/" + href.lstrip("/")
        except Exception as e:
            out["webError"] = f"{type(e).__name__}: {str(e)[:80]}"
    hints = out.get("regionHints") or []
    specific = {h for h in hints if h not in ("global", "worldwide", "international", "eu")}
    tld_eu = re.search(r"\.(eu|es|de|fr|nl|no|se|dk|fi|ie|uk|it|pt|be|ch|at|pl|cz|ee|lt|lv)$",
                       re.sub(r"^https?://", "", (web or "")).split("/")[0], re.I)
    if tld_eu or len(specific) >= 2:
        out["region"] = "EMEA"
    elif specific:
        out["region"] = "Posible EMEA (" + ", ".join(sorted(specific)) + ")"
    elif set(hints) & {"global", "worldwide", "international"}:
        out["region"] = "Global (sin confirmar EMEA)"
    return out


def partners_and_auditors():
    from concurrent.futures import ThreadPoolExecutor
    cards = vanta_partner_cards() + secureframe_partner_cards()
    # Drata's directory is behind a bot wall (HTTP 403): recorded, and covered by the daily web search
    if try_get("https://drata.com/service-partners/directory", "Drata partners") is None:
        pass
    merged = {}
    for c in cards:
        k = re.sub(r"[^a-z0-9]", "", c["name"].lower())
        if k in merged:
            m = merged[k]
            m["partnerOf"] = sorted(set((m["partnerOf"] if isinstance(m["partnerOf"], list) else [m["partnerOf"]]) + [c["partnerOf"]]))
            m["tags"] = sorted(set(m["tags"] + c["tags"]))
            m["web"] = m["web"] or c["web"]
        else:
            merged[k] = {**c, "partnerOf": [c["partnerOf"]]}
    items = list(merged.values())
    with ThreadPoolExecutor(max_workers=12) as ex:
        items = list(ex.map(enrich, items[:400]))
    tools_only = re.compile(r"^(security tools|storage / encryption tools|administrative tools|security training providers|"
                            r"technology partner|integration)$", re.I)
    partners, auditors = [], []
    for it in items:
        tags = [t.lower() for t in it.get("tags", [])]
        is_audit = any("audit" in t for t in tags) or re.search(r"\b(cpa|audit firm|attestation|certification body|"
                                                                 r"accredited|ukas|registrar)\b", it.get("description", ""), re.I)
        is_service = any(t in ("service partner", "vciso", "penetration testing", "msp", "mssp", "consulting") for t in tags) \
            or it.get("vciso") or (not tags and it["partnerOf"] == ["Secureframe"])
        if tags and all(tools_only.match(t) for t in it.get("tags", [])):
            continue
        row = {"name": it["name"], "web": it.get("web", ""), "region": it.get("region", ""),
               "regionHints": it.get("regionHints", []), "partnerOf": it["partnerOf"], "tags": it.get("tags", []),
               "vciso": bool(it.get("vciso")), "careers": it.get("careers", ""), "ats": it.get("ats", ""),
               "description": it.get("description", "")[:600], "source": it.get("source", ""),
               "emea": it.get("region") == "EMEA", "maybeEmea": "EMEA" in it.get("region", "") or "Global" in it.get("region", "")}
        if is_audit:
            auditors.append(row)
        if is_service or not is_audit:
            partners.append(row)
    stamp = NOW.isoformat(timespec="seconds")
    note = "Drata: its partner and auditor directories block automated reads (HTTP 403); the daily web search covers them."
    return ({"generatedAt": stamp, "count": len(partners), "emea": sum(1 for p in partners if p["emea"]), "note": note,
             "maybeEmea": sum(1 for p in partners if p["maybeEmea"] and not p["emea"]),
             "partners": sorted(partners, key=lambda p: (not p["emea"], not p["maybeEmea"], not p["vciso"], p["name"].lower()))},
            {"generatedAt": stamp, "count": len(auditors), "emea": sum(1 for a in auditors if a["emea"]), "note": note,
             "auditors": sorted(auditors, key=lambda a: (not a["emea"], a["name"].lower()))})


# ---------------------------------------------------------------- main
def main():
    DATA.mkdir(exist_ok=True)
    state = load("triggers_state.json", {})
    summary = {"ranAt": NOW.isoformat(timespec="seconds"), "ran": []}
    try:
        if due(state, "vendorCustomers", 6):
            vc = vendor_customers(load("vendor_customers.json", {}))
            save("vendor_customers.json", vc)
            state["vendorCustomers"] = NOW.isoformat(timespec="seconds")
            summary["ran"].append("vendorCustomers")
            summary["vendorCustomers"] = {"counts": vc["counts"], "new": len(vc["new"]), "baseline": vc["baseline"]}
    except Exception as e:
        ERRORS.append(f"vendor customers: {type(e).__name__}: {e}")
    try:
        if due(state, "partners", 27):
            partners, auditors = partners_and_auditors()
            save("partners.json", partners)
            save("auditors.json", auditors)
            state["partners"] = NOW.isoformat(timespec="seconds")
            summary["ran"].append("partners")
            summary["partners"] = {"count": partners["count"], "emea": partners["emea"]}
            summary["auditors"] = {"count": auditors["count"], "emea": auditors["emea"]}
    except Exception as e:
        ERRORS.append(f"partners: {type(e).__name__}: {e}")
    save("triggers_state.json", state)
    summary["errors"] = ERRORS
    summary["webSearchFallback"] = ["Drata: clientes, partners y auditores (bloquea la lectura automática)",
                                    "Secureframe: auditores partner (no publica un listado)"]
    run = load("run.json", {})
    run["triggers"] = summary
    save("run.json", run)
    print(json.dumps({k: v for k, v in summary.items() if k != "errors"}, ensure_ascii=False), "errors:", len(ERRORS))
    for e in ERRORS:
        print(" -", e)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never break the workflow
        print("triggers.py failed:", type(e).__name__, e)
        sys.exit(0)
