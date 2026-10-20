"""Discovery probe, round 2."""
import json, re, urllib.request, gzip, html
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "text/html,application/xml,application/json;q=0.9,*/*;q=0.8"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
            b = r.read()
            if b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
            return r.status, b.decode("utf-8", "replace")
    except Exception as e:
        return str(e)[:100], ""
def text(b):
    b = re.sub(r"<(script|style).*?</\1>", " ", b, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", b)))[:3000]
out = {}
st, sm = get("https://www.vanta.com/sitemap.xml")
locs = re.findall(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", sm)
out["vanta_sitemap"] = {"n": len(locs), "with_lastmod": sum(1 for l in locs if l[1]),
    "partner_urls": [l for l in locs if re.search("partner", l[0])][:80],
    "customers_sample": [l for l in locs if "/customers/" in l[0]][:10],
    "customers_n": sum(1 for l in locs if "/customers/" in l[0])}
for u in ["https://www.vanta.com/partners/find-a-partner?filters=Service+Partner", "https://www.vanta.com/partners/service-providers",
          "https://www.vanta.com/partners/find-a-partner", "https://secureframe.com/audit-partner",
          "https://secureframe.com/partner-directory?page=2", "https://secureframe.com/partner-directory/partner/adversis",
          "https://secureframe.com/partners/service-providers"]:
    st, b = get(u)
    links = sorted(set(re.findall(r'href=["\']([^"\']+)', b)))
    out[u] = {"status": st, "bytes": len(b), "links": [l for l in links if re.search(r"partner|auditor|http", l)][:120], "text": text(b)[:1500]}
for sm_url in ["https://secureframe.com/sitemap-main.xml"]:
    st, b = get(sm_url)
    locs = re.findall(r"<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", b)
    out[sm_url] = {"status": st, "n": len(locs), "customers": [l for l in locs if "/customers/" in l[0]][:15],
                   "customers_n": sum(1 for l in locs if "/customers/" in l[0]),
                   "partner": [l for l in locs if "partner" in l[0]][:40]}
open("data/probe.json", "w").write(json.dumps(out, indent=1))
