#!/usr/bin/env python3
"""Add companies to companies.json without duplicates (used by the daily radar task).

Usage:
  python3 tools/add_companies.py '[{"name": "Kord", "careers": "https://kord.teamtailor.com/"}, {"name": "Mindgard"}]'

Each entry needs "name"; optional "ats" ("ashby" | "greenhouse" | "lever") and "slugs" when known.
Names are compared ignoring case, accents, punctuation and anything in brackets, so
"MyComplianceOffice (MCO)" and "mycomplianceoffice" are the same company.
Prints a JSON summary: {"added": [...], "skipped": [...]}.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "companies.json"


def key(name):
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"\b(inc|ltd|gmbh|sas|sl|bv|ag|ab|oy|as|group|labs)\b", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    new = json.loads(argv[1])
    companies = json.loads(PATH.read_text(encoding="utf-8"))
    seen = {key(c["name"]) for c in companies}
    added, skipped = [], []
    for item in new:
        name = (item.get("name") or "").strip()
        k = key(name)
        if not k or k in seen:
            skipped.append(name)
            continue
        entry = {"name": name}
        if item.get("ats") in ("ashby", "greenhouse", "lever"):
            entry["ats"] = item["ats"]
        if item.get("slugs"):
            entry["slugs"] = [s for s in item["slugs"] if isinstance(s, str) and s]
        companies.append(entry)
        seen.add(k)
        added.append(name)
    if added:
        PATH.write_text(json.dumps(companies, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"added": added, "skipped": skipped}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
