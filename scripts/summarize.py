import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    # Package import: used by pytest (import scripts.summarize).
    from scripts.prompts import (
        build_chunk_prompt,
        build_full_prompt,
        build_merge_prompt,
        build_rescue_prompt,
    )
    from scripts.providers import is_bad_summary, request_sections
    from scripts.relevance import (
        filter_player_relevant_commits,
        player_relevance_score,
    )
except ModuleNotFoundError:
    # Direct script execution: python scripts/summarize.py
    from prompts import (
        build_chunk_prompt,
        build_full_prompt,
        build_merge_prompt,
        build_rescue_prompt,
    )
    from providers import is_bad_summary, request_sections
    from relevance import (
        filter_player_relevant_commits,
        player_relevance_score,
    )


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")
LOCAL_TZ = ZoneInfo("America/Toronto")
CHUNK_SIZE = 25

# Prompt content now includes strategic gameplay/balance rules.
PROMPT_VERSION = "structured-read-state-v5-player-signal"



def load_json(path, default):
    if not path.exists():
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def commit_local_date(commit):
    created_utc = datetime.fromisoformat(
        commit["created"]
    ).replace(
        tzinfo=timezone.utc
    )

    created_local = created_utc.astimezone(
        LOCAL_TZ
    )

    return created_local.date().isoformat()


def group_by_day(commits):
    grouped = defaultdict(list)

    for commit in commits:
        day = commit_local_date(commit)
        grouped[day].append(commit)

    return grouped


def commit_ids(commits):
    return {
        str(commit["id"])
        for commit in commits
    }


def commit_signature(commits):
    return ",".join(
        sorted(commit_ids(commits))
    )


def parse_signature(signature):
    if not signature:
        return set()

    return {
        value
        for value in signature.split(",")
        if value
    }


def sections_to_markdown(
    sections,
):
    parts = []

    for section in sections:
        parts.append(
            f"### {section['title']}"
        )

        for item in section["items"]:
            parts.append(
                f"- {item['text']}"
            )

        parts.append("")

    return "\n".join(
        parts
    ).strip()


def items_to_markdown(
    items,
):
    if not items:
        return ""

    return "\n".join(
        f"- {item['text']}"
        for item in items
    )


def call_ai(
    groq_key,
    openrouter_key,
    day,
    commits,
    old_chunk_cache=None,
):
    """
    Generate a structured daily summary.

    For large days, successful chunk summaries are cached in summaries.json.
    If a later chunk is rate-limited or fails, the next workflow run reuses
    the completed chunks and retries only the missing chunk(s).

    Returns:
        (final_sections_or_none, chunk_cache_to_save)
    """
    allowed_ids = commit_ids(
        commits
    )

    old_chunk_cache = (
        old_chunk_cache
        if isinstance(old_chunk_cache, dict)
        else {}
    )

    # Small day: one normal request and no chunk cache is needed.
    if len(commits) <= CHUNK_SIZE:
        sections = request_sections(
            groq_key,
            openrouter_key,
            build_full_prompt(
                day,
                commits,
            ),
            allowed_ids,
            day,
        )

        if sections is not None:
            return sections, {}

        return None, old_chunk_cache

    # Large day: split into deterministic chunks.
    chunks = [
        commits[
            index:index + CHUNK_SIZE
        ]
        for index in range(
            0,
            len(commits),
            CHUNK_SIZE,
        )
    ]

    print(
        f"{day} has {len(commits)} relevant commits; "
        f"splitting into {len(chunks)} chunks "
        f"of up to {CHUNK_SIZE}."
    )

    # Cache keys are based on the exact commit IDs in each chunk.
    # If the commit set changes later, only chunks with different signatures
    # need to be regenerated.
    chunk_cache = dict(
        old_chunk_cache
    )

    active_chunk_keys = set()
    chunk_sections = []

    for index, chunk in enumerate(
        chunks,
        start=1,
    ):
        chunk_allowed_ids = commit_ids(
            chunk
        )

        chunk_key = commit_signature(
            chunk
        )

        active_chunk_keys.add(
            chunk_key
        )

        cached_sections = chunk_cache.get(
            chunk_key
        )

        if (
            isinstance(cached_sections, list)
            and cached_sections
        ):
            print(
                f"Reusing cached chunk "
                f"{index}/{len(chunks)} "
                f"({len(chunk)} commits)."
            )

            chunk_sections.extend(
                cached_sections
            )
            continue

        print(
            f"Summarizing chunk "
            f"{index}/{len(chunks)} "
            f"({len(chunk)} commits)..."
        )

        sections = request_sections(
            groq_key,
            openrouter_key,
            build_chunk_prompt(
                day,
                chunk,
            ),
            chunk_allowed_ids,
            (
                f"{day} chunk "
                f"{index}/{len(chunks)}"
            ),
        )

        if sections is None:
            print(
                f"Chunk {index} failed. "
                "Completed chunks will be cached for the next run."
            )

            # Remove stale cache entries that no longer correspond to a
            # current chunk. Keep all successful current chunks.
            chunk_cache = {
                key: value
                for key, value in chunk_cache.items()
                if key in active_chunk_keys
                or key in {
                    commit_signature(item)
                    for item in chunks[index:]
                }
            }

            return None, chunk_cache

        chunk_cache[
            chunk_key
        ] = sections

        chunk_sections.extend(
            sections
        )

    # At this point every current chunk is available. Discard any stale
    # cached chunks left over from a previous commit layout.
    chunk_cache = {
        key: value
        for key, value in chunk_cache.items()
        if key in active_chunk_keys
    }

    print(
        f"Merging {len(chunks)} "
        f"chunk summaries for {day}..."
    )

    final_sections = request_sections(
        groq_key,
        openrouter_key,
        build_merge_prompt(
            day,
            chunk_sections,
        ),
        allowed_ids,
        f"{day} final merge",
    )

    if final_sections is None:
        print(
            "Final merge failed. Cached chunk summaries will be "
            "reused on the next run."
        )
        return None, chunk_cache

    # The final structured summary now exists, so the temporary chunk cache
    # is no longer needed.
    return final_sections, {}


def find_new_items(
    sections,
    new_commit_ids,
):
    if not new_commit_ids:
        return []

    new_items = []

    for section in sections:
        for item in section["items"]:
            item_ids = {
                str(value)
                for value
                in item["commit_ids"]
            }

            if (
                item_ids
                & new_commit_ids
            ):
                new_items.append(
                    {
                        "text": item["text"],
                        "commit_ids": (
                            item["commit_ids"]
                        ),
                        "section": (
                            section["title"]
                        ),
                    }
                )

    return new_items




def represented_commit_ids_from_sections(sections):
    """Return source commit IDs represented by structured summary sections."""
    ids = set()

    for section in sections:
        for item in section.get("items", []):
            for commit_id in item.get("commit_ids", []):
                ids.add(str(commit_id))

    return ids

def represented_commit_ids_from_items(
    items,
):
    """Return source commit IDs represented by a flat list of summary items."""
    represented = set()

    for item in items:
        for commit_id in item.get(
            "commit_ids",
            [],
        ):
            represented.add(
                str(commit_id)
            )

    return represented



def normalize_section_title(title):
    """Normalize a section title for case-insensitive, whitespace-insensitive matching."""
    return " ".join(
        str(title).strip().casefold().split()
    )


def merge_sections_by_title(
    sections,
    extra_sections,
):
    """
    Merge extra structured sections into existing sections by normalized title.

    The title spelling/casing from the first occurrence is preserved.
    Items are copied into a new result so callers' input lists are not mutated.
    """
    merged = []
    by_title = {}

    for section in list(sections) + list(extra_sections):
        if not isinstance(section, dict):
            continue

        title = str(
            section.get("title", "")
        ).strip()

        if not title:
            continue

        items = section.get(
            "items",
            [],
        )

        if not isinstance(items, list):
            continue

        key = normalize_section_title(
            title
        )

        if key in by_title:
            by_title[key]["items"].extend(
                list(items)
            )
            continue

        merged_section = {
            "title": title,
            "items": list(items),
        }

        merged.append(
            merged_section
        )

        by_title[key] = merged_section

    return merged


HIGH_IMPACT_THRESHOLD = 10


def high_impact_missing_commits(commits, sections):
    represented_ids = represented_commit_ids_from_sections(sections)

    return [
        commit
        for commit in commits
        if (
            player_relevance_score(commit) >= HIGH_IMPACT_THRESHOLD
            and str(commit["id"]) not in represented_ids
        )
    ]


def rescue_missing_high_impact_commits(
    groq_key,
    openrouter_key,
    day,
    commits,
    sections,
):
    missing = high_impact_missing_commits(
        commits,
        sections,
    )

    if not missing:
        return sections

    print(
        "WARNING: High-impact relevant commits were "
        "not represented in the final summary:"
    )

    for commit in missing:
        message = (
            commit.get("message", "")
            .replace("\n", " ")
            .replace("\r", " ")
        )
        print(
            f"  {commit['id']}: {message[:140]}"
        )

    missing_ids = commit_ids(missing)

    rescue_sections = request_sections(
        groq_key,
        openrouter_key,
        build_rescue_prompt(
            day,
            missing,
        ),
        missing_ids,
        f"{day} high-impact rescue",
    )

    if rescue_sections is None:
        print(
            "High-impact rescue failed; keeping the "
            "existing good summary."
        )
        return sections

    rescued_ids = represented_commit_ids_from_sections(
        rescue_sections
    )

    if not rescued_ids:
        print(
            "High-impact rescue returned no usable "
            "player-facing bullets."
        )
        return sections

    print(
        f"High-impact rescue added "
        f"{len(rescued_ids)} source commit(s)."
    )

    return merge_sections_by_title(
        sections,
        rescue_sections,
    )

def main():
    groq_key = os.environ.get(
        "GROQ_API_KEY"
    )

    openrouter_key = os.environ.get(
        "OPENROUTER_API_KEY"
    )

    if (
        not groq_key
        and not openrouter_key
    ):
        raise RuntimeError(
            "Neither GROQ_API_KEY nor "
            "OPENROUTER_API_KEY is set."
        )

    commits = load_json(
        COMMITS_FILE,
        [],
    )

    old_summaries = load_json(
        SUMMARY_FILE,
        {},
    )

    grouped = group_by_day(
        commits
    )

    today = datetime.now(
        LOCAL_TZ
    ).date().isoformat()

    valid_days = sorted(
        grouped.keys(),
        reverse=True,
    )[:3]

    summaries = {}

    for day in valid_days:
        raw_commits = grouped[
            day
        ]

        relevant_commits = (
            filter_player_relevant_commits(
                raw_commits,
                log_filtered=(
                    day == today
                ),
            )
        )

        current_signature = (
            commit_signature(
                relevant_commits
            )
        )

        current_ids = commit_ids(
            relevant_commits
        )

        old_entry = old_summaries.get(
            day
        )

        # ----------------------------------------------------
        # OLD FULL SUMMARY STATE
        # ----------------------------------------------------

        if old_entry:
            old_full_signature = (
                old_entry.get(
                    "relevant_signature",
                    old_entry.get(
                        "commit_signature",
                        "",
                    ),
                )
            )
        else:
            old_full_signature = ""

        if old_entry:
            old_new_baseline = (
                old_entry.get(
                    "new_baseline_signature",
                    old_full_signature,
                )
            )
        else:
            # First structured run: don't mark the entire existing day NEW.
            old_new_baseline = (
                current_signature
            )

        old_new_ids = parse_signature(
            old_new_baseline
        )

        newly_added_ids = (
            current_ids
            - old_new_ids
        )

        old_chunk_cache = (
            old_entry.get(
                "chunk_cache",
                {},
            )
            if old_entry
            else {}
        )

        # ----------------------------------------------------
        # CACHE STATE
        # ----------------------------------------------------

        old_summary_text = (
            old_entry.get(
                "summary",
                "",
            )
            if old_entry
            else ""
        )

        old_is_good = (
            old_entry
            and not is_bad_summary(
                old_summary_text
            )
        )

        old_sections = (
            old_entry.get(
                "sections"
            )
            if old_entry
            else None
        )

        old_has_structured_sections = (
            isinstance(
                old_sections,
                list,
            )
            and len(old_sections) > 0
        )

        prompt_matches = (
            old_entry
            and old_entry.get(
                "prompt_version"
            ) == PROMPT_VERSION
        )

        relevant_changed = (
            current_signature
            != old_full_signature
        )

        needs_refresh = (
            not old_is_good
            or not old_has_structured_sections
            or not prompt_matches
            or relevant_changed
        )

        generation_succeeded = False
        chunk_cache_out = old_chunk_cache

        # ----------------------------------------------------
        # FULL DAILY SUMMARY
        # ----------------------------------------------------

        if (
            not needs_refresh
            and old_entry
        ):
            sections = old_sections

            summary_markdown = (
                old_entry["summary"]
            )

            full_signature_out = (
                old_full_signature
            )

            # A completed summary never needs temporary chunks.
            chunk_cache_out = {}

            print(
                f"No player-relevant changes for "
                f"{day}; reusing structured "
                "daily summary."
            )

        elif not relevant_commits:
            sections = []

            summary_markdown = (
                "No significant player-facing "
                "updates."
            )

            full_signature_out = (
                current_signature
            )

            generation_succeeded = True
            chunk_cache_out = {}

        else:
            if relevant_changed:
                reason = (
                    "player-relevant commits changed"
                )
            elif not prompt_matches:
                reason = (
                    "summary structure changed"
                )
            elif not old_has_structured_sections:
                reason = (
                    "structured commit metadata missing"
                )
            else:
                reason = (
                    "cached summary invalid"
                )

            print(
                f"Refreshing {day} summary "
                f"({reason}); "
                f"{len(relevant_commits)} "
                "relevant commits."
            )

            (
                generated_sections,
                chunk_cache_out,
            ) = call_ai(
                groq_key,
                openrouter_key,
                day,
                relevant_commits,
                old_chunk_cache,
            )

            if (
                generated_sections
                is not None
            ):
                sections = (
                    generated_sections
                )

                sections = rescue_missing_high_impact_commits(
                    groq_key,
                    openrouter_key,
                    day,
                    relevant_commits,
                    sections,
                )

                summary_markdown = (
                    sections_to_markdown(
                        sections
                    )
                )

                full_signature_out = (
                    current_signature
                )

                generation_succeeded = (
                    True
                )

                print(
                    f"Saved new structured "
                    f"summary for {day}."
                )

            elif old_is_good:
                sections = (
                    old_sections
                    if old_has_structured_sections
                    else []
                )

                summary_markdown = (
                    old_summary_text
                )

                # IMPORTANT: the new commit set has NOT been fully
                # summarized yet, so keep the last successful signature.
                full_signature_out = (
                    old_full_signature
                )

                print(
                    f"Preserved previous good "
                    f"summary for {day}."
                )

            else:
                sections = []

                summary_markdown = (
                    "AI summary temporarily "
                    "unavailable. "
                    "The development commit archive "
                    "was updated successfully."
                )

                full_signature_out = ""

                print(
                    f"No previous valid summary "
                    f"available for {day}."
                )

        # ----------------------------------------------------
        # NEW — LAST 3 HRS
        # ----------------------------------------------------

        new_items = []
        new_summary_markdown = ""
        new_relevant_count = 0

        if day == today:
            if (
                generation_succeeded
                and sections
            ):
                new_items = (
                    find_new_items(
                        sections,
                        newly_added_ids,
                    )
                )

                new_summary_markdown = (
                    items_to_markdown(
                        new_items
                    )
                )

                represented_new_ids = (
                    represented_commit_ids_from_items(
                        new_items
                    )
                )

                new_relevant_count = len(
                    represented_new_ids
                )

                # Advance NEW only after the complete structured summary
                # successfully includes the current relevant commit set.
                new_baseline_out = (
                    current_signature
                )

                if new_items:
                    print(
                        f"NEW — LAST 3 HRS: "
                        f"{len(new_items)} "
                        "summary item(s), "
                        f"{new_relevant_count} "
                        "source commit(s)."
                    )
                else:
                    print(
                        "No summarized player-facing "
                        "items for NEW — LAST 3 HRS."
                    )

            elif not needs_refresh:
                new_items = []
                new_summary_markdown = ""
                new_relevant_count = 0

                new_baseline_out = (
                    current_signature
                )

                print(
                    "No new player-relevant commits "
                    "in this update window."
                )

            else:
                # Full structured generation failed. Do NOT advance the
                # baseline; the same unsummarized commits must remain NEW
                # candidates on the next retry.
                new_baseline_out = (
                    old_new_baseline
                )

                print(
                    "NEW tracking baseline preserved "
                    "because full summary generation failed."
                )

        else:
            new_items = []
            new_summary_markdown = ""
            new_relevant_count = 0

            # Historical days do not display NEW. Still keep this aligned
            # with the last successfully structured full-summary signature,
            # not with an unsuccessfully attempted newer commit set.
            new_baseline_out = (
                full_signature_out
            )

        # ----------------------------------------------------
        # SAVE DAY
        # ----------------------------------------------------

        summaries[day] = {
            "commit_count": len(
                raw_commits
            ),

            "relevant_commit_count": len(
                relevant_commits
            ),

            "relevant_signature": (
                full_signature_out
            ),

            "new_baseline_signature": (
                new_baseline_out
            ),

            "prompt_version": (
                PROMPT_VERSION
            ),

            # Temporary successful chunk results. This remains populated
            # only while a large-day generation is incomplete.
            "chunk_cache": (
                chunk_cache_out
            ),

            # Structured form used for Mark as Read.
            "sections": sections,

            # Existing Markdown form used by the current RSS.
            "summary": summary_markdown,

            # Structured NEW metadata.
            "new_items": new_items,

            "new_relevant_count": (
                new_relevant_count
            ),

            # Existing Markdown NEW form used by current RSS.
            "new_summary": (
                new_summary_markdown
            ),
        }

    with open(
        SUMMARY_FILE,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summaries,
            file,
            indent=2,
            ensure_ascii=False,
        )

    print(
        f"Saved {len(summaries)} "
        "daily summaries."
    )


if __name__ == "__main__":
    main()
