"""One-off discovery probe: which vendor pages and sitemaps are readable from GitHub Actions."""
import json, re, urllib.request, gzip
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
out = {}
pages = ["https://www.vanta.com/customers", "https://www.vanta.com/partners", "https://www.vanta.com/partners/directory",
         "https://www.vanta.com/sitemap.xml", "https://drata.com/customers", "https://drata.com/service-partners/directory",
         "https://drata.com/sitemap.xml", "https://drata.com/sitemap_index.xml", "https://drata.com/audit-partners",
         "https://secureframe.com/customers", "https://secureframe.com/partners", "https://secureframe.com/sitemap.xml",
         "https://secureframe.com/partner-directory", "https://www.vanta.com/partners/auditors"]
for u in pages:
    st, body = get(u)
    links = sorted(set(re.findall(r'(?:href=["\']|<loc>)(https?://[^"\'<\s]+|/[^"\'<\s]+)', body)))
    interesting = [l for l in links if re.search(r'customer|case-stud|partner|auditor|directory', l, re.I)]
    out[u] = {"status": st, "bytes": len(body), "nlinks": len(links), "interesting_count": len(interesting),
              "interesting": interesting[:60], "sitemaps": [l for l in links if "sitemap" in l][:30],
              "nextdata": "__NEXT_DATA__" in body, "webflow": "webflow" in body.lower(), "algolia": "algolia" in body.lower()}
open("data/probe.json", "w").write(json.dumps(out, indent=1))
