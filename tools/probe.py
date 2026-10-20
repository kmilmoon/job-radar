"""Discovery probe, round 3: save raw HTML for offline parsing."""
import urllib.request, gzip
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36",
      "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"}
def get(u):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=30) as r:
            b = r.read()
            if b[:2] == b"\x1f\x8b": b = gzip.decompress(b)
            return b.decode("utf-8", "replace")
    except Exception as e:
        return "ERROR " + str(e)
pages = {"vanta_find": "https://www.vanta.com/partners/find-a-partner", "vanta_auditors": "https://www.vanta.com/partners/auditors",
         "sf_dir1": "https://secureframe.com/partner-directory", "sf_dir2": "https://secureframe.com/partner-directory?page=2",
         "sf_partner": "https://secureframe.com/partner-directory/partner/conformly-as",
         "vanta_ref": "https://www.vanta.com/referral-partners/advantagepartners"}
import os
os.makedirs("data/probe", exist_ok=True)
for k, u in pages.items():
    open(f"data/probe/{k}.html", "w").write(get(u))
