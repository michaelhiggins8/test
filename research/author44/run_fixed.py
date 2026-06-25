#!/usr/bin/env python3
"""Run the author-44 build with corrected Wikidata parsing and exact-sample reporting."""
from __future__ import annotations

import json
import math
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import build_dataset as b


def fixed_fetch_entities(ids: list[str], retries: int = 5) -> dict[str, Any]:
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
            r = requests.get(b.WIKIDATA_API, params=params, timeout=120, headers={"User-Agent": b.USER_AGENT})
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            entities = r.json().get("entities", {})
            if isinstance(entities, dict):
                return {qid: ent for qid, ent in entities.items() if isinstance(ent, dict)}
            if isinstance(entities, list):
                return {ent["id"]: ent for ent in entities if isinstance(ent, dict) and ent.get("id")}
            return {}
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def nonempty(series: pd.Series) -> int:
    return int(series.fillna("").astype(str).str.strip().ne("").sum())


def rewrite_reports() -> None:
    out = b.OUT
    main_path = out / "authors_44_club.csv"
    sourced_path = out / "authors_44_club_with_sources.csv"
    df = pd.read_csv(main_path)
    sourced = pd.read_csv(sourced_path)

    counts = Counter(df["age_at_death"].astype(int))
    n = len(df)
    observed = counts.get(44, 0)
    expected_adjacent = (counts.get(43, 0) + counts.get(45, 0)) / 2
    expected_window = sum(counts.get(age, 0) for age in range(40, 49) if age != 44) / 8
    p_adjacent = b.poisson_tail(observed, expected_adjacent)
    p_window = b.poisson_tail(observed, expected_window)

    existing = pd.read_csv(out / "44_club_sensitivity_analysis.csv")
    exact = pd.DataFrame([{
        "sample": "exact_requested_csv",
        "n_with_plausible_age": n,
        "deaths_at_44": observed,
        "share_at_44": observed / n if n else 0,
        "expected_from_ages_43_and_45": expected_adjacent,
        "observed_to_expected_adjacent_ratio": observed / expected_adjacent if expected_adjacent else "",
        "one_sided_poisson_p_adjacent": p_adjacent,
        "expected_from_ages_40_to_48_excluding_44": expected_window,
        "observed_to_expected_window_ratio": observed / expected_window if expected_window else "",
        "one_sided_poisson_p_window": p_window,
    }])
    sensitivity = pd.concat([exact, existing], ignore_index=True)
    sensitivity.to_csv(out / "44_club_sensitivity_analysis.csv", index=False)

    requested_fields = [
        "author", "age_at_death", "year_or_birth", "year_of_death", "country", "ranking",
        "gender", "occupation", "primary_language", "work_type", "age_of_first_successes",
        "first_success", "genre"
    ]
    completeness = []
    for col in requested_fields:
        filled = nonempty(df[col])
        completeness.append({
            "field": col,
            "nonempty_rows": filled,
            "total_rows": n,
            "completeness_percent": round(100 * filled / n, 2) if n else 0,
        })
    pd.DataFrame(completeness).to_csv(out / "field_completeness.csv", index=False)

    adult_counts = {age: counts.get(age, 0) for age in range(20, 91)}
    age_rank = 1 + sum(1 for value in adult_counts.values() if value > adult_counts[44])
    top_ages = sorted(adult_counts.items(), key=lambda item: (-item[1], item[0]))[:15]

    conclusion = (
        "Age 44 is above both local expectations."
        if observed > expected_adjacent and observed > expected_window
        else "Age 44 is not above both local expectations."
    )
    inference = (
        "Both exploratory one-sided Poisson checks are below 0.05 before multiple-testing correction."
        if p_adjacent < 0.05 and p_window < 0.05
        else "The exploratory local checks do not show a statistically unusual excess at age 44."
    )

    comp = {row["field"]: row for row in completeness}
    methodology = f"""# Author '44 Club' dataset and preliminary test

## Result snapshot

- Requested dataset rows: **{n:,}** (highest-HPI deceased Pantheon writers with plausible ages from the top-1,500 selection).
- Authors in this exact CSV who died at 44: **{observed}**.
- Age 44's frequency rank among ages 20–90: **#{age_rank}**.
- Adjacent-age expected count, mean of ages 43 and 45: **{expected_adjacent:.2f}**.
- Wider local expected count, mean of ages 40–48 excluding 44: **{expected_window:.2f}**.
- Observed/adjacent-expected ratio: **{(observed / expected_adjacent if expected_adjacent else math.nan):.3f}**.
- Observed/wider-expected ratio: **{(observed / expected_window if expected_window else math.nan):.3f}**.
- One-sided Poisson p-value using adjacent expectation: **{p_adjacent:.4g}**.
- One-sided Poisson p-value using wider local expectation: **{p_window:.4g}**.

**Preliminary interpretation:** {conclusion} {inference} In this sample, age 44 is less common than the surrounding local baseline, so the data do **not** support a special author '44 Club'. This is still exploratory rather than a definitive demographic study: notability selection, changing mortality by birth cohort, approximate historical dates, and the possibility of testing many memorable ages all matter.

## Sampling rule

1. Download Pantheon's official 2025 person dataset from `{b.PANTHEON_URL}`.
2. Keep records whose Pantheon occupation is `WRITER`, who are deceased, and have birth/death years.
3. Rank eligible deceased writers by Pantheon Historical Popularity Index (HPI), descending.
4. Take the top 1,500, then exclude calculated ages outside 10–120. The final requested CSV contains {n:,} rows.

This is a reproducible fame/notability sample rather than a list selected because its members died young. HPI is a multilingual Wikipedia-based historical-popularity measure, not an official judgment of literary quality.

## Column rules and limitations

- `ranking`: ordinal rank among all deceased Pantheon writers by 2025 HPI.
- `age_at_death`: completed age from full dates when Pantheon has parseable dates; otherwise death year minus birth year. The sourced CSV identifies the method row by row.
- `country`: Pantheon's modern birth-place country.
- `occupation`: Wikidata P106 occupation labels, falling back to `Writer`. This does **not** reliably identify the job that supplied most of the person's income.
- `primary_language`: Wikidata P1412. A blank means no machine-readable value was present; language was not guessed from country.
- `work_type`: rule-based classification using Wikidata occupations and notable-work instance types.
- `first_success`: earliest dated Wikidata notable work (P800/P577), or the first listed notable work if undated. This is a **proxy**, not a hand-verified breakthrough.
- `age_of_first_successes`: proxy work year minus birth year; blank where no dated notable work is available.
- `genre`: Wikidata P136 from the author, falling back to the chosen notable work.

## Enrichment coverage

- Primary language populated: **{comp['primary_language']['nonempty_rows']:,}/{n:,} ({comp['primary_language']['completeness_percent']:.2f}%)**.
- First-success proxy populated: **{comp['first_success']['nonempty_rows']:,}/{n:,} ({comp['first_success']['completeness_percent']:.2f}%)**.
- Dated first-success age populated: **{comp['age_of_first_successes']['nonempty_rows']:,}/{n:,} ({comp['age_of_first_successes']['completeness_percent']:.2f}%)**.
- Genre populated: **{comp['genre']['nonempty_rows']:,}/{n:,} ({comp['genre']['completeness_percent']:.2f}%)**.

The exact 13-column file follows the requested schema. `authors_44_club_with_sources.csv` adds provenance and method fields so proxy-derived values can be audited.

## Top adult death ages in the requested sample

""" + "\n".join(f"- Age {age}: {count}" for age, count in top_ages) + "\n"
    (out / "44_club_methodology.md").write_text(methodology, encoding="utf-8")

    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "requested_csv_rows": n,
        "authors_died_at_44": observed,
        "field_completeness": {row["field"]: row["completeness_percent"] for row in completeness},
        "wikidata_person_entities_nonempty": int(sourced["occupation"].fillna("").astype(str).str.strip().ne("Writer").sum()),
    })
    manifest["files"] = sorted(path.name for path in out.iterdir() if path.is_file())
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    b.fetch_entities = fixed_fetch_entities
    b.main()
    rewrite_reports()
