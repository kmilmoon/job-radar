"""Offline test: fakes the three ATS APIs and checks detection, filtering and output."""
import json
import shutil
import tempfile
from pathlib import Path

import fetch_jobs as fj

ASHBY = {"jobs": [
    {"id": "3b308afe-aa98", "title": "Head of Security", "location": "Berlin", "secondaryLocations": [{"location": "Spain"}],
     "isRemote": True, "workplaceType": "Remote", "employmentType": "FullTime", "publishedAt": "2026-10-10T10:00:00Z",
     "jobUrl": "https://jobs.ashbyhq.com/n8n/3b308afe-aa98", "isListed": True, "descriptionPlain": "Build the security function."},
    {"id": "aaaa1111", "title": "Product Designer", "location": "Berlin", "isListed": True, "jobUrl": "x"},
]}
GH = {"jobs": [
    {"id": 4092090009, "title": "Head of Compliance & GRC", "location": {"name": "Remote - US"},
     "first_published": "2026-10-01T00:00:00Z", "absolute_url": "https://job-boards.greenhouse.io/nametag/jobs/4092090009",
     "content": "&lt;p&gt;Own SOC 2&lt;/p&gt;"},
    {"id": 1, "title": "Armed Security Guard", "location": {"name": "OR"}, "absolute_url": "y", "content": ""},
]}
LEVER = [{"id": "cd786589-b9b8", "text": "GRC Manager", "categories": {"location": "Madrid", "commitment": "Contract"},
          "workplaceType": "remote", "createdAt": 1760000000000, "hostedUrl": "https://jobs.lever.co/acme/cd786589",
          "descriptionPlain": "Lead ISO 27001."}]


def fake_get_json(url, timeout=25):
    if "ashbyhq.com/posting-api/job-board/n8n" in url:
        return ASHBY
    if "boards-api.greenhouse.io/v1/boards/nametag/" in url:
        return GH
    if "api.lever.co/v0/postings/acme?" in url:
        return LEVER
    return None


def run():
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(Path(fj.__file__), tmp / "fetch_jobs.py")
    (tmp / "companies.json").write_text(json.dumps([
        {"name": "n8n"}, {"name": "Nametag"}, {"name": "Acme Security"}, {"name": "Ghost Co"}]))
    fj.ROOT, fj.DATA = tmp, tmp / "data"
    fj.get_json = fake_get_json
    fj.time.sleep = lambda s: None
    assert fj.main() == 0
    jobs = json.loads((tmp / "data/jobs.json").read_text())
    titles = sorted(j["title"] for j in jobs)
    assert titles == ["GRC Manager", "Head of Compliance & GRC", "Head of Security"], titles
    by = {j["title"]: j for j in jobs}
    assert by["Head of Security"]["id"] == "ashby-n8n-3b308afe"
    assert "Spain" in by["Head of Security"]["location"]
    assert by["Head of Compliance & GRC"]["excerpt"] == "Own SOC 2"
    assert by["GRC Manager"]["ats"] == "lever" and by["GRC Manager"]["employment"] == "Contract"
    amap = json.loads((tmp / "data/ats_map.json").read_text())
    assert amap["Acme Security"] == {"ats": "lever", "slug": "acme"}, amap
    run_info = json.loads((tmp / "data/run.json").read_text())
    assert run_info["noBoardFound"] == ["Ghost Co"] and run_info["boardsRead"] == 3
    print("OK", titles)


if __name__ == "__main__":
    run()
