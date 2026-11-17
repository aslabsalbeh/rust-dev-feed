import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
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
        RELEVANCE_THRESHOLD,
        filter_player_relevant_commits,
        player_relevance_score,
    )
    from scripts.timeutil import parse_utc_timestamp
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
        RELEVANCE_THRESHOLD,
        filter_player_relevant_commits,
        player_relevance_score,
    )
    from timeutil import parse_utc_timestamp


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")
LOCAL_TZ = ZoneInfo("America/Toronto")
CHUNK_SIZE = 25

# Bump when prompt, relevance, merge, rescue, or chunk-cache behavior changes.
PROMPT_VERSION = "structured-read-state-v8-stable-chunks"



def load_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        raise RuntimeError(f"Existing JSON state is unreadable: {path}") from error


def atomic_write_json(path, data):
    temp_path = path.with_name(path.name + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, path)


NO_SIGNIFICANT_UPDATES = (
    "No notable player-facing changes were identified in the latest development commits."
)

PENDING_SUMMARY = (
    "The AI summary for the latest development commits is still being generated. "
    "The commit archive was updated successfully; this summary will refresh on the next run."
)

UNAVAILABLE_SUMMARY = (
    "AI summary temporarily unavailable. "
    "The development commit archive was updated successfully."
)

STALE_NOTICE = (
    "This summary covers an earlier commit set; "
    "{count} relevant commit(s) are not yet included."
)


NEW_WINDOW = timedelta(hours=3)


def commit_created_utc(commit):
    """Return a commit's created timestamp as an aware UTC datetime."""
    return parse_utc_timestamp(commit["created"])


def commit_local_date(commit):
    created_local = commit_created_utc(
        commit
    ).astimezone(
        LOCAL_TZ
    )

    return created_local.date().isoformat()


def recent_commit_ids(
    commits,
    now_utc=None,
    window=NEW_WINDOW,
):
    """Return commit IDs whose created timestamps are inside the rolling NEW window."""
    if now_utc is None:
        now_utc = datetime.now(
            timezone.utc
        )
    elif now_utc.tzinfo is None:
        now_utc = now_utc.replace(
            tzinfo=timezone.utc
        )
    else:
        now_utc = now_utc.astimezone(
            timezone.utc
        )

    cutoff = now_utc - window

    return {
        str(commit["id"])
        for commit in commits
        if cutoff <= commit_created_utc(commit) <= now_utc
    }


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


def commit_order_key(commit):
    """Return a deterministic oldest-first key for a commit.

    Missing or malformed timestamps must not make chunking fail; those commits
    fall back to ID order at the beginning of the day.
    """
    try:
        created = commit_created_utc(commit)
    except (KeyError, TypeError, ValueError):
        created = datetime.min.replace(tzinfo=timezone.utc)

    try:
        numeric_id = int(commit["id"])
    except (KeyError, TypeError, ValueError):
        numeric_id = 0

    return (created, numeric_id)


def chronological_chunks(commits, size=CHUNK_SIZE):
    """Split commits oldest-first so new arrivals do not shift every chunk.

    Facepunch returns newest-first data. Slicing that order makes chunk 1
    change whenever a single new commit arrives, invalidating every cached
    chunk. Building chunks from the oldest commit keeps all completed chunks
    stable and only extends/replaces the final (newest) chunk.
    """
    ordered = sorted(commits, key=commit_order_key)
    return [
        ordered[index:index + size]
        for index in range(0, len(ordered), size)
    ]


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


def usable_cached_sections(cached_sections, allowed_ids):
    """Return validated cached chunk sections, or None when unusable.

    An explicit empty chunk result is a valid cached assessment. Non-empty
    fragments are only trusted when every referenced commit belongs to the
    current chunk, which prevents a stale cache entry from leaking commits
    into the wrong chunk after boundaries change.
    """
    if not isinstance(cached_sections, list):
        return None

    if not cached_sections:
        return []

    represented = represented_commit_ids_from_sections(
        cached_sections
    )

    if not represented or not represented <= allowed_ids:
        return None

    return cached_sections


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

    # Large day: split into stable chronological chunks. New (newer) commits
    # extend the end of the list, so completed older chunks stay reusable.
    chunks = chronological_chunks(
        commits,
        CHUNK_SIZE,
    )

    print(
        f"{day} has {len(commits)} relevant commits; "
        f"splitting into {len(chunks)} chunks "
        f"of up to {CHUNK_SIZE} (oldest first)."
    )

    # Cache keys are based on the exact commit IDs in each chunk.
    # If the commit set changes later, only chunks with different signatures
    # need to be regenerated.
    chunk_cache = dict(
        old_chunk_cache
    )

    current_chunk_keys = {
        commit_signature(chunk)
        for chunk in chunks
    }

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

        cached_sections = usable_cached_sections(
            chunk_cache.get(chunk_key),
            chunk_allowed_ids,
        )

        if cached_sections is not None:
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

            # Keep every successful chunk for the current layout and drop
            # stale entries from older commit layouts.
            chunk_cache = {
                key: value
                for key, value in chunk_cache.items()
                if key in current_chunk_keys
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

    if not chunk_sections:
        return [], {}

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


def previously_published_missing_commits(commits, old_sections, new_sections):
    """Return relevant commits that were published before but disappeared."""
    dropped_ids = (
        represented_commit_ids_from_sections(old_sections or [])
        - represented_commit_ids_from_sections(new_sections or [])
    )
    return [
        commit
        for commit in commits
        if (
            str(commit["id"]) in dropped_ids
            and player_relevance_score(commit) >= RELEVANCE_THRESHOLD
        )
    ]


def rescue_previously_published_commits(
    groq_key,
    openrouter_key,
    day,
    commits,
    old_sections,
    sections,
):
    missing = previously_published_missing_commits(
        commits, old_sections, sections
    )
    if not missing:
        return sections

    print(
        "WARNING: Previously published relevant commits disappeared "
        "during regeneration; attempting stability rescue:"
    )
    for commit in missing:
        message = commit.get("message", "").replace("\n", " ").replace("\r", " ")
        print(f"  {commit['id']}: {message[:140]}")

    rescue_sections = request_sections(
        groq_key,
        openrouter_key,
        build_rescue_prompt(day, missing),
        commit_ids(missing),
        f"{day} published-item stability rescue",
    )
    if rescue_sections is None:
        print("Published-item stability rescue failed; keeping new summary.")
        return sections

    rescued_ids = represented_commit_ids_from_sections(rescue_sections)
    if not rescued_ids:
        return sections

    print(
        f"Published-item stability rescue restored "
        f"{len(rescued_ids)} source commit(s)."
    )
    return merge_sections_by_title(sections, rescue_sections)


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
            old_status = old_entry.get(
                "status"
            )
            old_prompt_version = old_entry.get(
                "prompt_version"
            )
        else:
            old_full_signature = ""
            old_status = None
            old_prompt_version = None

        old_chunk_cache = (
            old_entry.get(
                "chunk_cache",
                {},
            )
            if old_entry
            else {}
        )

        if not isinstance(
            old_chunk_cache,
            dict,
        ):
            old_chunk_cache = {}

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

        old_sections_list = (
            old_sections
            if isinstance(old_sections, list)
            else []
        )

        old_has_structured_sections = (
            len(old_sections_list) > 0
        )

        prompt_matches = (
            old_entry
            and old_prompt_version == PROMPT_VERSION
        )

        relevant_changed = (
            current_signature
            != old_full_signature
        )

        old_explicit_empty = (
            old_entry is not None
            and old_status == "no_significant_updates"
            and old_sections_list == []
            and old_summary_text == NO_SIGNIFICANT_UPDATES
        )

        # A partial/pending entry means generation was already in progress.
        # Its cached chunks must keep the day in the pending state instead of
        # falling back to "unavailable".
        old_in_progress = (
            old_status == "pending"
            or bool(old_chunk_cache)
        )

        old_has_usable_content = bool(
            old_is_good
            and (
                old_has_structured_sections
                or old_explicit_empty
            )
        )

        needs_refresh = (
            not old_is_good
            or not (old_has_structured_sections or old_explicit_empty)
            or not prompt_matches
            or relevant_changed
        )

        generation_succeeded = False
        chunk_cache_out = old_chunk_cache
        summary_status = None
        summary_notice = ""
        pending_relevant_count = 0
        prompt_version_out = PROMPT_VERSION

        # ----------------------------------------------------
        # FULL DAILY SUMMARY
        # ----------------------------------------------------

        if (
            not needs_refresh
            and old_entry
        ):
            sections = old_sections_list

            summary_markdown = (
                old_entry["summary"]
            )

            full_signature_out = (
                old_full_signature
            )

            # A completed summary never needs temporary chunks.
            chunk_cache_out = {}

            summary_status = (
                "ok" if sections
                else "no_significant_updates"
            )

            prompt_version_out = (
                old_prompt_version
                or PROMPT_VERSION
            )

            print(
                f"Reusing structured daily summary "
                f"for {day} "
                f"({len(relevant_commits)} relevant "
                "commits; commit set unchanged)."
            )

        elif not relevant_commits:
            sections = []

            summary_markdown = NO_SIGNIFICANT_UPDATES

            full_signature_out = (
                current_signature
            )

            generation_succeeded = True
            chunk_cache_out = {}

            summary_status = (
                "no_significant_updates"
            )

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

                if sections:
                    sections = rescue_missing_high_impact_commits(
                        groq_key,
                        openrouter_key,
                        day,
                        relevant_commits,
                        sections,
                    )

                    if old_has_structured_sections:
                        sections = rescue_previously_published_commits(
                            groq_key,
                            openrouter_key,
                            day,
                            relevant_commits,
                            old_sections_list,
                            sections,
                        )

                represented_count = len(
                    represented_commit_ids_from_sections(sections)
                )
                print(
                    f"Summary coverage for {day}: "
                    f"{represented_count}/{len(relevant_commits)} "
                    "relevant source commit(s) represented."
                )

                summary_markdown = (
                    sections_to_markdown(sections) if sections
                    else NO_SIGNIFICANT_UPDATES
                )

                full_signature_out = (
                    current_signature
                )

                generation_succeeded = (
                    True
                )

                summary_status = (
                    "ok" if sections
                    else "no_significant_updates"
                )

                prompt_version_out = PROMPT_VERSION

                print(
                    f"Saved new structured "
                    f"summary for {day}."
                )

            elif old_has_usable_content and not relevant_changed:
                # The preserved content already covers the current commit
                # set. Only an optional prompt/structure refresh failed, so
                # this is still a complete summary for this day.
                sections = old_sections_list

                summary_markdown = old_summary_text

                full_signature_out = old_full_signature

                summary_status = (
                    "ok" if sections
                    else "no_significant_updates"
                )

                prompt_version_out = (
                    old_prompt_version
                    or PROMPT_VERSION
                )

                print(
                    f"Preserved complete previous "
                    f"summary for {day}."
                )

            elif (
                relevant_changed
                and old_has_usable_content
                and old_has_structured_sections
            ):
                # Previously published content is real, but it does not
                # cover the current commit set. Preserve it and label it
                # clearly as stale instead of presenting it as new.
                sections = old_sections_list

                summary_markdown = old_summary_text

                full_signature_out = old_full_signature

                summary_status = "partial"

                represented_ids = (
                    represented_commit_ids_from_sections(
                        sections
                    )
                )

                pending_relevant_count = len(
                    commit_ids(relevant_commits)
                    - represented_ids
                )

                if pending_relevant_count == 0:
                    # The preserved content already represents every current
                    # relevant commit; only the stored signature was stale.
                    summary_status = "ok"

                    full_signature_out = (
                        current_signature
                    )

                    summary_notice = ""
                else:
                    summary_notice = STALE_NOTICE.format(
                        count=pending_relevant_count
                    )

                prompt_version_out = (
                    old_prompt_version
                    or PROMPT_VERSION
                )

                print(
                    f"Preserved earlier summary for "
                    f"{day}; {pending_relevant_count} "
                    "newer relevant commit(s) are "
                    "still pending."
                )

            elif (
                (relevant_changed and old_explicit_empty)
                or old_in_progress
            ):
                # An older explicit-empty result must never be presented as
                # current when newer commits exist but generation failed.
                sections = []

                summary_markdown = PENDING_SUMMARY

                full_signature_out = (
                    old_full_signature
                )

                summary_status = "pending"

                pending_relevant_count = len(
                    relevant_commits
                )

                prompt_version_out = (
                    old_prompt_version
                    or PROMPT_VERSION
                )

                print(
                    f"Summary for {day} is pending; "
                    f"{pending_relevant_count} relevant "
                    "commit(s) are not yet summarized."
                )

            else:
                sections = []

                summary_markdown = (
                    UNAVAILABLE_SUMMARY
                )

                full_signature_out = ""

                summary_status = "unavailable"

                pending_relevant_count = len(
                    relevant_commits
                )

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

        if (
            day == today
            and sections
            and summary_status == "ok"
        ):
            # NEW is a true rolling time window. Recalculate it on every
            # workflow run, even when the full AI summary is reused.
            recent_ids = recent_commit_ids(
                relevant_commits,
            )

            new_items = find_new_items(
                sections,
                recent_ids,
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
                    "items currently inside the "
                    "rolling 3-hour NEW window."
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


            "prompt_version": (
                prompt_version_out
            ),

            # Temporary successful chunk results. This remains populated
            # only while a large-day generation is incomplete.
            "chunk_cache": (
                chunk_cache_out
            ),

            # Structured form used for Mark as Read.
            "sections": sections,
            "status": summary_status,

            # Explains why displayed content does not cover the newest
            # commits. Empty for complete summaries.
            "notice": summary_notice,

            # Relevant commits not represented by the displayed content.
            "pending_relevant_count": (
                pending_relevant_count
            ),

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

    atomic_write_json(
        SUMMARY_FILE,
        summaries,
    )

    print(
        f"Saved {len(summaries)} "
        "daily summaries."
    )


if __name__ == "__main__":
    main()
