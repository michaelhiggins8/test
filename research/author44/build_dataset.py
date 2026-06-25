#!/usr/bin/env python3
"""Build a reproducible author mortality dataset from Pantheon 2025 + Wikidata.

This script is intentionally isolated under research/author44. It downloads the official
Pantheon 2025 person archive, selects the highest-HPI deceased writers, enriches them
with machine-readable Wikidata fields, and exports the requested CSV plus provenance
and age-frequency analysis files.
"""
from __future__ import annotations

import bz2
import csv
import json
import math
import os
import re
import time
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

PANTHEON_URL = "https://storage.googleapis.com/pantheon-public-data/person_2025_update.csv.bz2"
PANTHEON_DATA_PAGE = "https://pantheon.world/data/datasets"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(parents=True, exist_ok=True)
ARCHIVE = OUT / "person_2025_update.csv.bz2"
SAMPLE_SIZE = 1500
USER_AGENT = "Author44ClubResearch/1.0 (reproducible public-interest research)"


def download(url: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 1_000_000:
        return
    with requests.get(url, stream=True, timeout=180, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def chunks(seq: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def fetch_entities(ids: list[str], retries: int = 5) -> dict[str, Any]:
    ids = [x for x in ids if x]
    if not ids:
        return {}
    params = {
        "action": "wbgetentities",
        "ids": "|".join(ids),
        "props": "labels|claims",
        "languages": "en",
        "languagefallback": "1",
        "format": "json",
        "formatversion": "2",
    }
    for attempt in range(retries):
        try:
            r = requests.get(WIKIDATA_API, params=params, timeout=120, headers={"User-Agent": USER_AGENT})
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            data = r.json()
            return {e["id"]: e for e in data.get("entities", []) if "id" in e}
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def claim_entity_ids(entity: dict[str, Any], prop: str) -> list[str]:
    vals: list[str] = []
    for claim in entity.get("claims", {}).get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("entity-type") == "item" and value.get("id"):
            vals.append(value["id"])
    return vals


def claim_time_years(entity: dict[str, Any], prop: str) -> list[int]:
    years: list[int] = []
    for claim in entity.get("claims", {}).get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("time"):
            m = re.match(r"([+-])(\d{1,})-", value["time"])
            if m:
                y = int(m.group(2))
                if m.group(1) == "-":
                    y = -y
                years.append(y)
    return years


def label(entity: dict[str, Any] | None) -> str:
    if not entity:
        return ""
    labels = entity.get("labels", {})
    if isinstance(labels, dict):
        en = labels.get("en")
        if isinstance(en, dict):
            return en.get("value", "")
        if isinstance(en, str):
            return en
        for v in labels.values():
            if isinstance(v, dict) and v.get("value"):
                return v["value"]
    return ""


def parse_iso_date(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str) or not value:
        return None
    # Pantheon may append BC; exact month/day is not reliable for those rows.
    if "BC" in value.upper():
        return None
    m = re.match(r"^(\d{1,4})-(\d{2})-(\d{2})", value)
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    if y < 1 or not (1 <= mo <= 12) or not (1 <= d <= 31):
        return None
    return y, mo, d


def compute_age(row: pd.Series) -> tuple[int | None, str]:
    by = row.get("birthyear")
    dy = row.get("deathyear")
    if pd.isna(by) or pd.isna(dy):
        return None, "missing"
    by_i, dy_i = int(by), int(dy)
    b = parse_iso_date(row.get("birthdate"))
    d = parse_iso_date(row.get("deathdate"))
    if b and d:
        age = d[0] - b[0] - ((d[1], d[2]) < (b[1], b[2]))
        return age, "exact dates"
    # Astronomical arithmetic across BCE/CE has no year zero in conventional dates.
    age = dy_i - by_i
    if by_i < 0 < dy_i:
        age -= 1
    return age, "year difference"


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def choose_labels(ids: list[str], entities: dict[str, Any], limit: int = 3) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for qid in ids:
        txt = label(entities.get(qid)).strip()
        key = txt.lower()
        if txt and key not in seen:
            out.append(txt)
            seen.add(key)
        if len(out) >= limit:
            break
    return out


def infer_work_type(occupation_labels: list[str], work_labels: list[str]) -> str:
    text = " | ".join(work_labels + occupation_labels).lower()
    rules = [
        (("short story", "short-story"), "Short story"),
        (("novel", "novelist"), "Novel"),
        (("poem", "poetry", "poet"), "Poem"),
        (("play", "playwright", "dramatist"), "Play"),
        (("essay", "essayist"), "Essay"),
        (("screenplay", "screenwriter"), "Screenplay"),
        (("academic article", "scholarly article", "academic"), "Academic article"),
        (("non-fiction", "nonfiction", "biographer", "historian", "journalist"), "Nonfiction book"),
    ]
    for needles, result in rules:
        if any(x in text for x in needles):
            return result
    if "book" in text:
        return "Book"
    return "Other / mixed writing"


def poisson_tail(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k <= 0 else 0.0
    # P(X >= k) = 1 - sum_{i=0}^{k-1} exp(-lam) lam^i / i!
    term = math.exp(-lam)
    cdf = term
    for i in range(1, max(k, 1)):
        term *= lam / i
        cdf += term
    return max(0.0, min(1.0, 1.0 - cdf)) if k > 0 else 1.0


def clean_string(v: Any) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    return str(v).strip()


def main() -> None:
    download(PANTHEON_URL, ARCHIVE)
    print(f"Downloaded {ARCHIVE.stat().st_size:,} bytes")

    # pandas transparently reads bzip2; low_memory avoids mixed-type inference warnings.
    df = pd.read_csv(ARCHIVE, compression="bz2", low_memory=False)
    print("Pantheon rows:", len(df), "columns:", list(df.columns))

    occ = df.get("occupation", pd.Series(dtype=str)).astype(str).str.upper().str.strip()
    alive = df.get("alive", False)
    if alive.dtype != bool:
        alive = alive.astype(str).str.lower().isin(["true", "1", "t", "yes"])
    writers = df[(occ == "WRITER") & (~alive) & df["birthyear"].notna() & df["deathyear"].notna()].copy()
    writers["hpi_numeric"] = pd.to_numeric(writers.get("hpi"), errors="coerce")
    writers = writers.sort_values(["hpi_numeric", "name"], ascending=[False, True], na_position="last").reset_index(drop=True)
    writers["rank_numeric"] = range(1, len(writers) + 1)
    print("Deceased Pantheon writers:", len(writers))

    sample = writers.head(SAMPLE_SIZE).copy()
    ages = sample.apply(compute_age, axis=1, result_type="expand")
    sample["age_at_death"] = ages[0]
    sample["age_method"] = ages[1]
    sample = sample[(sample["age_at_death"].notna()) & (sample["age_at_death"].between(10, 120))].copy()
    print("Selected plausible-age sample:", len(sample))

    # Fetch person-level Wikidata entities.
    qids = [q for q in sample.get("wd_id", pd.Series(dtype=str)).astype(str).tolist() if re.fullmatch(r"Q\d+", q)]
    person_entities: dict[str, Any] = {}
    for batch in chunks(qids, 50):
        person_entities.update(fetch_entities(batch))
        time.sleep(0.15)
    print("Wikidata person entities:", len(person_entities))

    related_ids: set[str] = set()
    person_meta: dict[str, dict[str, list[str]]] = {}
    for qid in qids:
        ent = person_entities.get(qid, {})
        meta = {
            "occupations": claim_entity_ids(ent, "P106"),
            "languages": claim_entity_ids(ent, "P1412"),
            "works": claim_entity_ids(ent, "P800"),
            "genres": claim_entity_ids(ent, "P136"),
        }
        person_meta[qid] = meta
        for vals in meta.values():
            related_ids.update(vals)

    related_entities: dict[str, Any] = {}
    for batch in chunks(sorted(related_ids), 50):
        related_entities.update(fetch_entities(batch))
        time.sleep(0.15)
    print("Initial related entities:", len(related_entities))

    # Gather work types/genres from the notable-work entities, then fetch their labels.
    second_level_ids: set[str] = set()
    for qid, meta in person_meta.items():
        for wid in meta["works"]:
            went = related_entities.get(wid, {})
            second_level_ids.update(claim_entity_ids(went, "P31"))
            second_level_ids.update(claim_entity_ids(went, "P136"))
    missing_second = sorted(second_level_ids - set(related_entities))
    for batch in chunks(missing_second, 50):
        related_entities.update(fetch_entities(batch))
        time.sleep(0.15)
    print("All related entities:", len(related_entities))

    records: list[dict[str, Any]] = []
    extended: list[dict[str, Any]] = []
    for _, row in sample.iterrows():
        qid = clean_string(row.get("wd_id"))
        meta = person_meta.get(qid, {"occupations": [], "languages": [], "works": [], "genres": []})
        occupation_labels = choose_labels(meta["occupations"], related_entities, 3)
        language_labels = choose_labels(meta["languages"], related_entities, 3)
        person_genres = choose_labels(meta["genres"], related_entities, 3)

        work_candidates: list[tuple[int | None, str, str, list[str], list[str]]] = []
        for wid in meta["works"]:
            went = related_entities.get(wid, {})
            years = claim_time_years(went, "P577")
            year = min(years) if years else None
            wlabel = label(went)
            type_labels = choose_labels(claim_entity_ids(went, "P31"), related_entities, 4)
            genre_labels = choose_labels(claim_entity_ids(went, "P136"), related_entities, 4)
            work_candidates.append((year, wlabel, wid, type_labels, genre_labels))
        dated = [x for x in work_candidates if x[0] is not None]
        chosen = min(dated, key=lambda x: x[0]) if dated else (work_candidates[0] if work_candidates else None)

        first_success = chosen[1] if chosen else ""
        first_success_year = chosen[0] if chosen else None
        birth_year = int(row["birthyear"])
        first_success_age: int | str = ""
        if first_success_year is not None:
            calc = int(first_success_year) - birth_year
            if birth_year < 0 < int(first_success_year):
                calc -= 1
            if 0 <= calc <= 100:
                first_success_age = calc
        chosen_types = chosen[3] if chosen else []
        chosen_genres = chosen[4] if chosen else []
        genre_labels = person_genres or chosen_genres
        work_type = infer_work_type(occupation_labels, chosen_types)

        gender_raw = clean_string(row.get("gender")).upper()
        gender = {"M": "Male", "F": "Female"}.get(gender_raw, gender_raw.title() if gender_raw else "Unknown")
        occupation = "; ".join(occupation_labels) if occupation_labels else "Writer"
        primary_language = "; ".join(language_labels)
        genre = "; ".join(genre_labels)
        rank_n = int(row["rank_numeric"])

        rec = {
            "author": clean_string(row.get("name")),
            "age_at_death": int(row["age_at_death"]),
            "year_or_birth": birth_year,
            "year_of_death": int(row["deathyear"]),
            "country": clean_string(row.get("bplace_country")),
            "ranking": ordinal(rank_n),
            "gender": gender,
            "occupation": occupation,
            "primary_language": primary_language,
            "work_type": work_type,
            "age_of_first_successes": first_success_age,
            "first_success": first_success,
            "genre": genre,
        }
        records.append(rec)
        ext = dict(rec)
        ext.update({
            "pantheon_rank_numeric": rank_n,
            "pantheon_hpi": row.get("hpi_numeric"),
            "pantheon_wikidata_id": qid,
            "birthdate": clean_string(row.get("birthdate")),
            "deathdate": clean_string(row.get("deathdate")),
            "age_method": row.get("age_method"),
            "first_success_year_proxy": first_success_year if first_success_year is not None else "",
            "first_success_method": "earliest dated Wikidata notable work (P800/P577); proxy, not a verified breakthrough date" if chosen else "missing",
            "work_type_method": "rule-based classification from Wikidata occupations and notable-work instance types",
            "occupation_method": "Wikidata occupation (P106); not guaranteed to be the author's income source",
            "primary_language_method": "Wikidata languages spoken/written/signed (P1412)",
            "pantheon_source": PANTHEON_DATA_PAGE,
            "pantheon_archive": PANTHEON_URL,
            "wikidata_source": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
        })
        extended.append(ext)

    requested_cols = [
        "author", "age_at_death", "year_or_birth", "year_of_death", "country", "ranking",
        "gender", "occupation", "primary_language", "work_type", "age_of_first_successes",
        "first_success", "genre"
    ]
    req_path = OUT / "authors_44_club.csv"
    pd.DataFrame(records, columns=requested_cols).to_csv(req_path, index=False, encoding="utf-8")
    ext_path = OUT / "authors_44_club_with_sources.csv"
    pd.DataFrame(extended).to_csv(ext_path, index=False, encoding="utf-8")

    # Full age-frequency table for the selected sample.
    freq = Counter(int(r["age_at_death"]) for r in records)
    freq_rows = [{"age_at_death": age, "author_count": freq[age]} for age in sorted(freq)]
    pd.DataFrame(freq_rows).to_csv(OUT / "age_at_death_counts.csv", index=False)

    age44 = [r for r in records if r["age_at_death"] == 44]
    pd.DataFrame(age44, columns=requested_cols).to_csv(OUT / "authors_who_died_at_44.csv", index=False, encoding="utf-8")

    # Sensitivity analysis at several HPI cutoffs. Recompute ages for all deceased writers once.
    all_ages = writers.apply(compute_age, axis=1, result_type="expand")
    writers["age_calc"] = all_ages[0]
    plausible = writers[writers["age_calc"].notna() & writers["age_calc"].between(10, 120)].copy()
    sensitivity: list[dict[str, Any]] = []
    for label_name, frame in [
        ("top_1000_by_HPI", plausible.head(1000)),
        ("top_1500_by_HPI", plausible.head(1500)),
        ("top_2000_by_HPI", plausible.head(2000)),
        ("all_deceased_Pantheon_writers", plausible),
    ]:
        counts = Counter(frame["age_calc"].astype(int))
        observed = counts.get(44, 0)
        expected_adjacent = (counts.get(43, 0) + counts.get(45, 0)) / 2
        expected_window = sum(counts.get(a, 0) for a in range(40, 49) if a != 44) / 8
        p_adjacent = poisson_tail(observed, expected_adjacent)
        p_window = poisson_tail(observed, expected_window)
        sensitivity.append({
            "sample": label_name,
            "n_with_plausible_age": len(frame),
            "deaths_at_44": observed,
            "share_at_44": observed / len(frame) if len(frame) else 0,
            "expected_from_ages_43_and_45": expected_adjacent,
            "observed_to_expected_adjacent_ratio": observed / expected_adjacent if expected_adjacent else "",
            "one_sided_poisson_p_adjacent": p_adjacent,
            "expected_from_ages_40_to_48_excluding_44": expected_window,
            "observed_to_expected_window_ratio": observed / expected_window if expected_window else "",
            "one_sided_poisson_p_window": p_window,
        })
    pd.DataFrame(sensitivity).to_csv(OUT / "44_club_sensitivity_analysis.csv", index=False)

    # Determine how unusual 44 is descriptively among adult ages 20-90 in requested sample.
    adult_counts = {age: freq.get(age, 0) for age in range(20, 91)}
    age_rank = 1 + sum(1 for v in adult_counts.values() if v > adult_counts[44])
    top_ages = sorted(adult_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:15]
    sens = sensitivity[1]
    conclusion = (
        "The age-44 count is above both local expectations."
        if sens["deaths_at_44"] > sens["expected_from_ages_43_and_45"] and sens["deaths_at_44"] > sens["expected_from_ages_40_to_48_excluding_44"]
        else "The age-44 count is not above both local expectations."
    )
    if sens["one_sided_poisson_p_adjacent"] < 0.05 and sens["one_sided_poisson_p_window"] < 0.05:
        inference = "Both local Poisson checks are below 0.05 before correcting for the fact that many possible ages could have been examined."
    else:
        inference = "At least one local Poisson check is not below 0.05; this sample does not provide robust evidence of an age-44 spike."

    methodology = f"""# Author '44 Club' dataset and preliminary test

## Result snapshot

- Requested dataset rows: **{len(records):,}** (top deceased Pantheon writers by HPI with plausible ages).
- Authors in this sample who died at 44: **{len(age44)}**.
- Age 44's frequency rank among ages 20–90: **#{age_rank}** (ties share counts but this simple rank counts only strictly higher frequencies).
- Adjacent-age expected count, mean of ages 43 and 45: **{sens['expected_from_ages_43_and_45']:.2f}**.
- Wider local expected count, mean of ages 40–48 excluding 44: **{sens['expected_from_ages_40_to_48_excluding_44']:.2f}**.
- One-sided Poisson p-value using adjacent expectation: **{sens['one_sided_poisson_p_adjacent']:.4g}**.
- One-sided Poisson p-value using wider local expectation: **{sens['one_sided_poisson_p_window']:.4g}**.

**Preliminary interpretation:** {conclusion} {inference} This should not be treated as proof of a '44 Club': the sample is selected for notability, mortality changes strongly by birth cohort, some historical dates are approximate, and testing a memorable age after looking at the data creates a multiple-comparisons problem.

## Sampling rule

1. Download Pantheon's official 2025 person dataset from `{PANTHEON_URL}`.
2. Keep rows whose Pantheon occupation is `WRITER`, who are deceased, and have birth/death years.
3. Rank all eligible deceased writers by Pantheon Historical Popularity Index (HPI), descending.
4. Take the top {SAMPLE_SIZE:,}, then exclude implausible calculated ages outside 10–120. The final requested CSV contains {len(records):,} rows.

This creates a reproducible fame/notability sample instead of starting from people known to have died young. HPI is a multilingual Wikipedia-based historical-popularity measure, not an official literary-quality ranking.

## Column rules and important limitations

- `ranking`: ordinal rank among all deceased Pantheon writers by 2025 HPI.
- `age_at_death`: exact completed age when Pantheon has parseable full dates; otherwise year-of-death minus year-of-birth. See `age_method` in the sourced CSV.
- `country`: Pantheon's modern birth-place country field.
- `occupation`: Wikidata P106 labels. This is a documented occupation, **not reliably the method by which the author earned most income**.
- `primary_language`: Wikidata P1412. Blank means no machine-readable value was present; it is not an inference from country.
- `work_type`: rule-based classification from Wikidata occupation labels and the chosen notable work's instance type.
- `first_success`: the earliest dated Wikidata notable work (P800 with P577), or the first listed notable work if none has a date. This is a **proxy for first success**, not a biographically verified breakthrough work.
- `age_of_first_successes`: publication year of that proxy minus birth year; blank when no dated notable work is available.
- `genre`: Wikidata P136 from the author, falling back to the chosen notable work.

The exact 13-column file follows the user's requested schema. `authors_44_club_with_sources.csv` adds provenance and method fields so uncertain or proxy-derived values can be audited rather than mistaken for hand-verified facts.

## Top adult death ages in the requested sample

""" + "\n".join(f"- Age {age}: {count}" for age, count in top_ages) + "\n"
    (OUT / "44_club_methodology.md").write_text(methodology, encoding="utf-8")

    manifest = {
        "pantheon_rows": len(df),
        "deceased_writer_rows": len(writers),
        "requested_csv_rows": len(records),
        "authors_died_at_44": len(age44),
        "files": sorted(p.name for p in OUT.iterdir() if p.is_file()),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
