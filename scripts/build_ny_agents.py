#!/usr/bin/env python3
import csv
import hashlib
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

DATASET_ID = "yg7h-zjbf"
DOMAIN = "data.ny.gov"
SOURCE_PAGE = f"https://{DOMAIN}/d/{DATASET_ID}"
API = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
INDIVIDUAL_TYPES = {
    "ASSOCIATE BROKER",
    "CORPORATE BROKER",
    "INDIVIDUAL BROKER",
    "LIMITED LIABILITY BROKER",
    "PARTNERSHIP BROKER",
    "REAL ESTATE SALESPERSON",
    "TRADENAME BROKER",
}


def clean(value):
    value = "" if value is None else str(value)
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip()


def fetch_page(offset, limit=50000):
    params = {
        "$select": "license_holder_name,license_number,license_type",
        "$where": "license_holder_name is not null",
        "$order": "license_number,license_holder_name",
        "$limit": str(limit),
        "$offset": str(offset),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OfficialRealEstateLicenseCollector/1.0",
            "Accept": "application/json",
        },
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.load(response)
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)


records = {}
conflicts = []
raw_rows = 0
raw_type_counts = Counter()
skipped_type_counts = Counter()
offset = 0
page_size = 50000

while True:
    page = fetch_page(offset, page_size)
    if not isinstance(page, list):
        raise RuntimeError(f"Unexpected API response type: {type(page).__name__}")
    if not page:
        break
    raw_rows += len(page)
    for row in page:
        name = clean(row.get("license_holder_name"))
        license_number = clean(row.get("license_number"))
        license_type = clean(row.get("license_type")).upper()
        raw_type_counts[license_type] += 1
        if license_type not in INDIVIDUAL_TYPES:
            skipped_type_counts[license_type] += 1
            continue
        if not name or not license_number:
            continue
        candidate = {
            "name": name,
            "state": "NY",
            "image_url": "",
            "license_number": license_number,
            "license_type": license_type,
        }
        existing = records.get(license_number)
        if existing is None:
            records[license_number] = candidate
        elif existing["name"] != name:
            conflicts.append({
                "license_number": license_number,
                "existing_name": existing["name"],
                "new_name": name,
                "existing_type": existing["license_type"],
                "new_type": license_type,
            })
            if (len(name), name.casefold()) > (
                len(existing["name"]),
                existing["name"].casefold(),
            ):
                records[license_number] = candidate
    offset += len(page)
    if len(page) < page_size:
        break

rows = sorted(records.values(), key=lambda r: (r["name"].casefold(), r["license_number"]))
output = Path("new_york_real_estate_agents_official.csv")
with output.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=["name", "state", "image_url", "license_number"])
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row[key] for key in writer.fieldnames})

with output.open("rb") as handle:
    sha256 = hashlib.file_digest(handle, "sha256").hexdigest()

accepted_type_counts = Counter(row["license_type"] for row in rows)
report = {
    "source_provider": "New York State Department of State (DOS)",
    "source_dataset": "Active Real Estate Salespersons and Brokers",
    "source_dataset_id": DATASET_ID,
    "source_page": SOURCE_PAGE,
    "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "raw_named_rows": raw_rows,
    "accepted_unique_license_rows": len(rows),
    "raw_type_counts": dict(sorted(raw_type_counts.items())),
    "accepted_type_counts": dict(sorted(accepted_type_counts.items())),
    "skipped_type_counts": dict(sorted(skipped_type_counts.items())),
    "duplicate_name_conflicts": len(conflicts),
    "output_sha256": sha256,
    "normalization": {
        "license_number": "Official value preserved; uniqueness is (state, license_number)",
        "name": "Official license_holder_name preserved with Unicode NFKC and whitespace cleanup",
        "image_url": "Blank because the official roster does not publish headshots",
    },
}
Path("new_york_real_estate_agents_report.json").write_text(
    json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)
with Path("new_york_real_estate_agents_conflicts.csv").open(
    "w", encoding="utf-8", newline=""
) as handle:
    fieldnames = [
        "license_number",
        "existing_name",
        "new_name",
        "existing_type",
        "new_type",
    ]
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(conflicts)

print(json.dumps(report, indent=2))
