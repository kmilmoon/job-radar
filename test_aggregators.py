"""Offline test for the aggregator feeds: classification, geography filter, parsing."""
import aggregators as ag
import fetch_jobs as fj

assert ag.classify("Head of Security") == "core"
assert ag.classify("GRC Manager") == "core"
assert ag.classify("Fractional COO") == "alt"
assert ag.classify("Chief of Staff to the CEO") == "alt"
assert ag.classify("Senior Program Manager") == "alt"
assert ag.classify("AI Governance Lead") == "core" or ag.classify("AI Governance Lead") == "alt"
assert ag.classify("Cybersecurity Instructor") == "core"
assert ag.classify("Junior Operations Manager") is None
assert ag.classify("Senior Software Engineer") is None
assert ag.classify("Account Executive") is None
assert ag.geo_ok("Spain") and ag.geo_ok("Remote - EMEA") and ag.geo_ok("Worldwide") and ag.geo_ok("")
assert not ag.geo_ok("United States") and not ag.geo_ok("Remote - US only")

LEVER = [
    {"id": "aaaaaaaa-1", "text": "Jobgether - Head of Operations", "categories": {"location": "Spain", "commitment": "Full-time"},
     "createdAt": 1760000000000, "hostedUrl": "https://jobs.lever.co/jobgether/aaaaaaaa-1", "descriptionPlain": "Run ops."},
    {"id": "bbbbbbbb-2", "text": "Jobgether - Software Engineer", "categories": {"location": "Spain"}, "hostedUrl": "x"},
    {"id": "cccccccc-3", "text": "Jobgether - Program Manager", "categories": {"location": "United States"}, "hostedUrl": "y"},
]
HIMA = {"jobs": [
    {"title": "Fractional COO", "companyName": "Acme", "locationRestrictions": [], "applicationLink": "https://himalayas.app/a",
     "guid": "https://himalayas.app/companies/acme/jobs/fractional-coo", "pubDate": 1760000000, "employmentType": "Contractor",
     "excerpt": "Part-time COO", "categories": ["Operations"]},
    {"title": "Security Program Manager", "companyName": "Beta", "locationRestrictions": ["Spain", "Portugal"],
     "applicationLink": "https://himalayas.app/b", "guid": "https://himalayas.app/companies/beta/jobs/spm", "pubDate": 1760000000},
]}
WN = [{"url": "https://www.workingnomads.com/jobs/chief-of-staff-gamma", "title": "Chief of Staff", "company_name": "Gamma",
       "location": "Europe", "pub_date": "2026-10-10T00:00:00", "description": "<p>Help the CEO</p>", "tags": "operations,remote"}]


def fake(url, timeout=25):
    if "lever.co/v0/postings/jobgether" in url:
        return LEVER
    if "himalayas.app/jobs/api" in url:
        return HIMA if "offset=0" in url else {"jobs": []}
    if "workingnomads.com/api" in url:
        return WN
    return None


fj.get_json = fake
ag.probe = lambda url, timeout=40: fake(url)
import json as _json
GOB = {"data": [{"id": "head-of-security-acme-1", "attributes": {"title": "Head of Seguridad de la Información", "remote": True,
  "remote_modality": "fully_remote", "countries": [], "published_at": 1760000000, "company": {"data": {"attributes": {"name": "Acme LatAm"}}}},
  "links": {"public_url": "https://www.getonbrd.com/jobs/acme-1"}},
  {"id": "dev-2", "attributes": {"title": "Senior Software Engineer", "remote": True}}]}
TORRE = {"results": [{"id": "abc123", "objective": "Gerente de Operaciones", "organizations": [{"name": "Beta Co"}], "locations": [], "created": "2026-10-10T00:00:00Z"},
  {"id": "zzz", "objective": "Risk Manager", "organizations": [{"name": "Gamma"}], "locations": ["Colombia"]}]}
WWR = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Delta Pay: GRC Lead</title><region>Europe Only</region><pubDate>Wed, 22 Oct 2026 10:00:00 +0000</pubDate>
<link>https://weworkremotely.com/remote-jobs/delta-grc-lead</link><description>&lt;p&gt;Own SOC 2&lt;/p&gt;</description></item>
<item><title>Foo: Senior React Developer&nbsp;&rsquo;</title><region>Anywhere</region><link>https://weworkremotely.com/x</link></item>
<item><title>Bar: Head of Security</title><region>USA Only</region><link>https://weworkremotely.com/y</link></item>
</channel></rss>"""
GF_LIST = '<a href="/job/acme-fractional-ciso">x</a><a href="/job/old-closed-role">y</a>'
GF_JOB = """<html><title>Fractional CISO | GoFractional</title><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","title":"Fractional CISO","datePosted":"2026-10-20","hiringOrganization":{"@type":"Organization","name":"Acme"},"jobLocationType":"TELECOMMUTE","applicantLocationRequirements":{"@type":"Country","name":"Europe"},"description":"<p>Own SOC 2</p>"}</script></html>"""
def fake_raw(url, data=None, timeout=40, accept=None):
    if "gofractional.com/jobs/fractional-ciso" in url: return GF_LIST
    if "gofractional.com/jobs/" in url: return ""
    if url.endswith("/job/acme-fractional-ciso"): return GF_JOB
    if url.endswith("/job/old-closed-role"): return "This job was closed Jul 22 and is no longer accepting applications"
    if "weworkremotely.com/categories/remote-management" in url: return WWR
    if "getonbrd" in url: return _json.dumps(GOB if "query=security" in url else {"data": []})
    if "torre.co" in url: return _json.dumps(TORRE if "security" in _json.dumps(data) else {"results": []})
    return None
ag.probe_raw = fake_raw
items, counts, errors = ag.run()
titles = sorted((i["track"], i["title"]) for i in items)
assert titles == [("alt", "Chief of Staff"), ("alt", "Fractional COO"), ("alt", "Head of Operations"),
                  ("core", "Fractional CISO"), ("core", "GRC Lead"), ("core", "Head of Seguridad de la Información"), ("core", "Security Program Manager")], titles
assert {k: v for k, v in counts.items() if k != "_raw"} == {"jobgether": 1, "himalayas": 2, "workingnomads": 1,
    "getonboard": 1, "rss": 1, "gofractional": 1}, counts
assert ag.classify("Vigilante de seguridad") is None and ag.classify("Responsable de Cumplimiento") == "core"
assert not errors
wn = [i for i in items if i["source"] == "workingnomads"][0]
assert wn["excerpt"] == "Help the CEO" and wn["tags"] == ["operations", "remote"]
w = [i for i in items if i["source"] == "weworkremotely"][0]
assert w["company"] == "Delta Pay" and w["posted"] == "2026-10-22" and w["excerpt"] == "Own SOC 2", w
print("OK", titles)
