"""Offline test for triggers.py with saved pages (data/probe/*.html) and fake sitemaps."""
import json, os, shutil, tempfile
from pathlib import Path
import triggers as tg

PROBE = Path(__file__).parent / "tests" / "fixtures"
VANTA_SM = """<urlset><url><loc>https://www.vanta.com/customers/acme</loc><lastmod>2026-10-10T00:00:00Z</lastmod></url>
<url><loc>https://www.vanta.com/customers/beta-co</loc><lastmod>2026-01-01T00:00:00Z</lastmod></url>
<url><loc>https://www.vanta.com/pricing</loc></url></urlset>"""
SF_SM = """<sitemapindex><sitemap><loc>https://secureframe.com/sitemap-main.xml</loc></sitemap></sitemapindex>"""
SF_MAIN = """<urlset><url><loc>https://secureframe.com/customers/oth-security</loc><lastmod>2026-08-03</lastmod></url>
<url><loc>https://secureframe.com/customers/oth-security.md</loc></url></urlset>"""
state = {"vanta": VANTA_SM}

def fake_get(url, timeout=40):
    if url == "https://www.vanta.com/sitemap.xml": return state["vanta"]
    if url == "https://secureframe.com/sitemap.xml": return SF_SM
    if url == "https://secureframe.com/sitemap-main.xml": return SF_MAIN
    if url.startswith("https://www.vanta.com/partners/find-a-partner"):
        return (PROBE / "vanta_find.html").read_text() if "page=" not in url else "<html></html>"
    if url == "https://secureframe.com/partner-directory": return (PROBE / "sf_dir1.html").read_text()
    if "drata.com" in url: raise tg.urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
    if url.startswith("http"):
        return "<html><body>vCISO services across Europe and the UK. <a href='/careers'>Careers</a></body></html>"
    raise ValueError(url)

tg.get = fake_get
import urllib.error  # noqa
tmp = Path(tempfile.mkdtemp()); tg.DATA = tmp
os.environ["FORCE"] = "1"
assert tg.main() == 0
vc = json.loads((tmp / "vendor_customers.json").read_text())
assert vc["counts"] == {"Vanta": 2, "Secureframe": 1, "Drata": 0}, vc["counts"]
assert vc["new"] == [] and set(vc["baseline"]) == {"Vanta", "Secureframe"}
# second weekly run: one new Vanta customer appears
state["vanta"] = VANTA_SM.replace("</urlset>", "<url><loc>https://www.vanta.com/customers/gamma-pay</loc><lastmod>2026-10-19</lastmod></url></urlset>")
tg.ERRORS.clear(); assert tg.main() == 0
vc = json.loads((tmp / "vendor_customers.json").read_text())
assert [n["slug"] for n in vc["new"]] == ["gamma-pay"] and vc["new"][0]["name"] == "Gamma Pay", vc["new"]
p = json.loads((tmp / "partners.json").read_text()); a = json.loads((tmp / "auditors.json").read_text())
names = {x["name"] for x in p["partners"]}
assert "Advantage Partners" in {x["name"] for x in a["auditors"]}, a
assert any("Secureframe" in x["partnerOf"] for x in p["partners"]), names
assert all(x["careers"].endswith("/careers") for x in p["partners"] if x["web"])
assert p["emea"] > 0
run = json.loads((tmp / "run.json").read_text())
assert any("Drata" in e for e in run["triggers"]["errors"])
print("OK vendor", vc["counts"], "partners", p["count"], "auditors", a["count"], "sample", sorted(names)[:6])
