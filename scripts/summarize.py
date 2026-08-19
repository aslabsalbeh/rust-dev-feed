import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


# ============================================================
# FILES / SETTINGS
# ============================================================

COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")

LOCAL_TZ = ZoneInfo("America/Toronto")

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Change this whenever the summary/filter structure changes.
# This forces one fresh regeneration even when commit IDs
# themselves have not changed.
PROMPT_VERSION = "structured-read-state-v1"


BAD_MARKERS = (
    "We need to produce",
    "Let's identify themes",
    "We have many commits",
    "<unk>",
    "AI summary temporarily unavailable",
)


# ============================================================
# PLAYER RELEVANCE FILTER
# ============================================================

HIGH_VALUE_TERMS = (
    # Bugs / broken behaviour
    "fix",
    "fixed",
    "bug",
    "glitch",
    "broken",
    "incorrect",
    "incorrectly",
    "not spawning",
    "not spawn",
    "not working",
    "couldn't",
    "could not",
    "unable to",
    "stuck",
    "missing",
    "disappear",
    "disappearing",
    "fail",
    "crash",
    "disconnect",
    "desync",
    "exploit",

    # Gameplay
    "damage",
    "healing",
    "health",
    "ammo",
    "weapon",
    "recoil",
    "reload",
    "melee",
    "projectile",
    "loot",
    "resource",
    "craft",
    "building",
    "deployable",
    "seat",
    "mountable",
    "mount",
    "vehicle",

    # NPCs / animals
    "scientist",
    "npc",
    "animal",
    "livestock",
    "cow",
    "bull",
    "sheep",
    "horse",
    "dog",
    "bear",
    "wolf",

    # World / monuments
    "monument",
    "underwater lab",
    "underwater labs",
    "cargo ship",
    "cargo",
    "oilrig",
    "oil rig",
    "military base",
    "gas station",
    "nexus",
    "map",

    # Player-facing items/features
    "bandage",
    "flashlight",
    "catapult",
    "ballista",
    "firework",
)


BUG_TERMS = (
    "fix",
    "fixed",
    "bug",
    "glitch",
    "broken",
    "incorrect",
    "incorrectly",
    "not spawning",
    "not spawn",
    "not working",
    "couldn't",
    "could not",
    "unable to",
    "stuck",
    "missing",
    "disappear",
    "crash",
    "disconnect",
    "desync",
    "exploit",
    "nre",
)


TECHNICAL_TERMS = (
    "refactor",
    "cleanup",
    "clean up",
    "codegen",
    "code gen",
    "test asset",
    "automated test",
    "unit test",
    "integration test",
    "debug",
    "logging",
    "log handler",
    "rename",
    "renamed",
    "naming convention",
    "editor tooling",
    "editor tool",
    "developer tool",
    "profiling",
    "instrumentation",
    "serialization",
    "source control",
    "build pipeline",
    "compiler",
)


LOW_VALUE_VISUAL_TERMS = (
    "atlas",
    "glyph",
    "font atlas",
    "dynamic font",
    "ao texture",
    "ambient occlusion",
    "texture reduced",
    "texture size",
    "texture resolution",
    "lod",
    "mesh collider",
    "shader",
    "render pipeline",
    "rendering pipeline",
    "vignette",
    "radial blur",
    "material naming",
    "material rename",
    "prefab cleanup",
    "re-export",
    "reexport",
)


VISIBLE_VISUAL_TERMS = (
    "animation",
    "model",
    "appearance",
    "icon",
    "effect",
    "visual",
    "third-person",
    "first-person",
    "viewmodel",
    "ui",
    "menu",
    "modal",
)


# ============================================================
# GENERAL HELPERS
# ============================================================

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


def is_bad_summary(text):
    if not text:
        return True

    lowered = text.lower()

    return any(
        marker.lower() in lowered
        for marker in BAD_MARKERS
    )


# ============================================================
# PLAYER RELEVANCE SCORING
# ============================================================

def commit_search_text(commit):
    return (
        f"{commit.get('branch', '')} "
        f"{commit.get('message', '')}"
    ).lower().replace("_", " ")


def contains_any(text, terms):
    return any(
        term in text
        for term in terms
    )


def player_relevance_score(commit):
    text = commit_search_text(commit)

    score = 0

    # Bug/glitch fixes get strong priority.
    if contains_any(text, BUG_TERMS):
        score += 6

    # Player-facing subject matter.
    high_matches = sum(
        1
        for term in HIGH_VALUE_TERMS
        if term in text
    )

    score += min(
        high_matches,
        4,
    ) * 2

    # New player-facing content.
    if re.search(
        r"\b(add|added|new|introduce|introduced)\b",
        text,
    ):
        if contains_any(
            text,
            HIGH_VALUE_TERMS,
        ):
            score += 3

    # Gameplay/balance behaviour.
    if contains_any(
        text,
        (
            "balance",
            "balanced",
            "increase damage",
            "decrease damage",
            "resource yield",
            "spawn rate",
            "movement",
            "behaviour",
            "behavior",
        ),
    ):
        score += 3

    # Visible changes receive a little weight,
    # but are much weaker than gameplay fixes.
    if contains_any(
        text,
        VISIBLE_VISUAL_TERMS,
    ):
        score += 1

    # Internal development work.
    if contains_any(
        text,
        TECHNICAL_TERMS,
    ):
        score -= 5

    # Rendering/asset trivia.
    if contains_any(
        text,
        LOW_VALUE_VISUAL_TERMS,
    ):
        score -= 5

    # Tests normally aren't player news.
    if re.search(
        r"\b(test|tests|testing)\b",
        text,
    ):
        score -= 4

    # Cleanup/refactoring.
    if re.search(
        r"\b(cleanup|refactor|rename|renamed)\b",
        text,
    ):
        score -= 4

    # Concrete player-facing bugs should survive even if
    # the commit also contains technical language.
    if (
        contains_any(text, BUG_TERMS)
        and contains_any(
            text,
            HIGH_VALUE_TERMS,
        )
    ):
        score += 5

    return score


def filter_player_relevant_commits(
    commits,
    log_filtered=False,
):
    scored = []

    for commit in commits:
        score = player_relevance_score(
            commit
        )

        scored.append(
            (score, commit)
        )

    scored.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    relevant = [
        commit
        for score, commit in scored
        if score >= 2
    ]

    print(
        f"Player relevance filter: "
        f"{len(commits)} raw commits -> "
        f"{len(relevant)} useful candidates."
    )

    if log_filtered:
        for score, commit in scored:
            if score < 2:
                message = (
                    commit.get(
                        "message",
                        "",
                    )
                    .replace("\n", " ")
                    .replace("\r", " ")
                )

                print(
                    f"  Filtered ({score:+d}): "
                    f"{message[:100]}"
                )

    return relevant


# ============================================================
# AI PROMPT
# ============================================================

def build_prompt(day, commits):
    commit_blocks = []

    for commit in commits:
        branch = commit.get(
            "branch",
            "",
        )

        if branch.startswith("main/"):
            branch = branch[5:]

        commit_blocks.append(
            "\n".join(
                [
                    f"Commit ID: {commit['id']}",
                    f"Branch context: {branch}",
                    f"Message: {commit.get('message', '')}",
                ]
            )
        )

    return f"""
Create a concise daily Rust development digest for RUST PLAYERS.

These are official Facepunch development commits from {day}.

Each source commit has a numeric Commit ID.

SOURCE COMMITS:

{chr(10).join(commit_blocks)}

The digest answers:

"What happened in Rust development today that an ordinary Rust player
would actually want to know?"

Do NOT try to represent every commit.

PRIORITIZE:
- Concrete player-facing bug and glitch fixes
- Gameplay mechanic changes
- Balance changes
- Weapons, equipment, items and deployables
- NPC and animal behaviour
- Monuments and world changes
- Vehicles
- Loot and resource changes
- Crashes, disconnects and exploits
- Meaningful player-visible UI problems

Preserve concrete bug symptoms.

BAD:
"Improved scientist spawning reliability."

GOOD:
"Fixed scientists not spawning in Underwater Labs and Cargo Ship."

AGGRESSIVELY EXCLUDE:
- Texture resolution changes
- AO texture changes
- Font atlas changes
- Glyph generation
- LOD implementation details
- Radial blur or vignette tuning
- Shader/render-pipeline implementation details
- Asset optimization with no stated gameplay impact
- Memory reductions with no stated player impact
- Prefab cleanup
- Naming conventions
- Code cleanup
- Refactoring
- Developer/editor tools
- Automated tests
- Logging/debugging
- Internal implementation details

Something being visible does NOT automatically make it useful enough
for this digest.

Never sacrifice a concrete gameplay bug fix to make room for cosmetic,
rendering or technical information.

Development commits may describe unreleased work.
Clearly label work-in-progress or upcoming features when needed.

CRITICAL SOURCE-ID RULES:

Every output bullet MUST include the exact source Commit IDs that support it.

If several commits describe the same underlying change, combine them
into one bullet and include all relevant Commit IDs.

Never invent a Commit ID.

Only use Commit IDs from SOURCE COMMITS above.

Do not include a commit ID just because it is about a similar topic.
The ID must genuinely support that exact bullet.

A source commit should normally appear in only one output bullet.

It is acceptable to omit source commits that are not important enough
for the player digest.

OUTPUT FORMAT:

Return ONLY valid JSON.

Do not return Markdown.
Do not return a code fence.
Do not return commentary before or after the JSON.

Use exactly this structure:

{{
  "sections": [
    {{
      "title": "NPC & AI",
      "items": [
        {{
          "text": "Fixed scientists not spawning in Underwater Labs and Cargo Ship.",
          "commit_ids": [615201, 615204]
        }}
      ]
    }}
  ]
}}

OUTPUT RULES:
- Aim for roughly 8 to 15 worthwhile bullets total.
- Fewer is fine when little meaningful happened.
- Use 2 to 6 short topic sections.
- Put the most important sections first.
- Keep bullet text concise.
- Combine duplicate commits.
- Preserve useful item, NPC, monument and gameplay names.
- Preserve concrete bug symptoms.
- Do not mention developer names in text.
- Do not mention commit IDs inside bullet text.
- Do not mention branch names in bullet text.
- Do not speculate.
- Do not include a title or date.
- Return ONLY the JSON object.
"""


# ============================================================
# STRUCTURED AI RESPONSE PARSING
# ============================================================

def strip_code_fence(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return text


def parse_structured_summary(
    text,
    allowed_commit_ids,
):
    text = strip_code_fence(text)

    try:
        data = json.loads(text)
    except Exception as error:
        print(
            f"Could not parse AI JSON: {error}"
        )
        return None

    raw_sections = data.get(
        "sections"
    )

    if not isinstance(
        raw_sections,
        list,
    ):
        return None

    sections = []

    for raw_section in raw_sections:
        if not isinstance(
            raw_section,
            dict,
        ):
            continue

        title = str(
            raw_section.get(
                "title",
                "",
            )
        ).strip()

        raw_items = raw_section.get(
            "items",
            [],
        )

        if (
            not title
            or not isinstance(
                raw_items,
                list,
            )
        ):
            continue

        items = []

        for raw_item in raw_items:
            if not isinstance(
                raw_item,
                dict,
            ):
                continue

            item_text = str(
                raw_item.get(
                    "text",
                    "",
                )
            ).strip()

            raw_ids = raw_item.get(
                "commit_ids",
                [],
            )

            if (
                not item_text
                or not isinstance(
                    raw_ids,
                    list,
                )
            ):
                continue

            valid_ids = []

            for raw_id in raw_ids:
                try:
                    commit_id = str(
                        int(raw_id)
                    )
                except Exception:
                    continue

                if (
                    commit_id
                    in allowed_commit_ids
                    and commit_id
                    not in valid_ids
                ):
                    valid_ids.append(
                        commit_id
                    )

            # Every bullet must map to at least one real source commit.
            if not valid_ids:
                print(
                    "Dropped AI bullet with no "
                    "valid source commit IDs: "
                    f"{item_text[:80]}"
                )
                continue

            items.append(
                {
                    "text": item_text,
                    "commit_ids": [
                        int(value)
                        for value in valid_ids
                    ],
                }
            )

        if items:
            sections.append(
                {
                    "title": title,
                    "items": items,
                }
            )

    if not sections:
        return None

    return sections


# ============================================================
# MARKDOWN BACKWARD-COMPATIBILITY
# ============================================================

def sections_to_markdown(sections):
    """
    Keep generating the old Markdown summary as well.

    This means the existing RSS generator continues working
    until we upgrade it to use structured section metadata.
    """

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


def items_to_markdown(items):
    if not items:
        return ""

    return "\n".join(
        f"- {item['text']}"
        for item in items
    )


# ============================================================
# AI PROVIDERS
# ============================================================

def call_chat_api(
    url,
    api_key,
    model,
    prompt,
    provider_name,
    allowed_commit_ids,
):
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": (
                    f"Bearer {api_key}"
                ),
                "Content-Type": (
                    "application/json"
                ),
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": 0.1,
            },
            timeout=90,
        )

    except requests.RequestException as error:
        print(
            f"{provider_name} network error: "
            f"{error}"
        )
        return None

    if response.status_code == 429:
        print(
            f"{provider_name} rate-limited."
        )
        return None

    if not response.ok:
        print(
            f"{provider_name} error "
            f"{response.status_code}: "
            f"{response.text[:300]}"
        )
        return None

    try:
        data = response.json()

        text = (
            data["choices"][0]
            ["message"]["content"]
            .strip()
        )

    except Exception:
        print(
            f"{provider_name} returned "
            "an invalid API response."
        )
        return None

    if is_bad_summary(text):
        print(
            f"{provider_name} returned "
            "rejected AI output."
        )
        return None

    sections = parse_structured_summary(
        text,
        allowed_commit_ids,
    )

    if sections is None:
        print(
            f"{provider_name} returned "
            "invalid structured summary JSON."
        )
        return None

    return sections


def call_ai(
    groq_key,
    openrouter_key,
    day,
    commits,
):
    prompt = build_prompt(
        day,
        commits,
    )

    allowed_ids = commit_ids(
        commits
    )

    if groq_key:
        print(
            f"Trying Groq for {day}..."
        )

        sections = call_chat_api(
            GROQ_URL,
            groq_key,
            GROQ_MODEL,
            prompt,
            "Groq",
            allowed_ids,
        )

        if sections is not None:
            print(
                f"Groq succeeded for {day}."
            )

            return sections

    if openrouter_key:
        print(
            f"Trying OpenRouter fallback "
            f"for {day}..."
        )

        sections = call_chat_api(
            OPENROUTER_URL,
            openrouter_key,
            OPENROUTER_MODEL,
            prompt,
            "OpenRouter",
            allowed_ids,
        )

        if sections is not None:
            print(
                f"OpenRouter succeeded "
                f"for {day}."
            )

            return sections

    return None


# ============================================================
# NEW — LAST 3 HRS
# ============================================================

def find_new_items(
    sections,
    new_commit_ids,
):
    """
    A summary item appears in NEW when at least one of its
    underlying source commit IDs arrived since the previous
    successful summary update.

    This means a bullet combining an old commit and a new
    commit still appears in NEW, which is exactly what we want.
    """

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
                        "commit_ids": item["commit_ids"],
                        "section": section["title"],
                    }
                )

    return new_items


def represented_commit_ids(items):
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


# ============================================================
# MAIN
# ============================================================

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
        raw_commits = grouped[day]

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
        # PREVIOUS FULL-SUMMARY STATE
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

        old_full_ids = parse_signature(
            old_full_signature
        )

        # NEW tracking has its own baseline.
        #
        # Older versions won't have this key, so fall back
        # to the previous summary signature.
        if old_entry:
            old_new_baseline = (
                old_entry.get(
                    "new_baseline_signature",
                    old_full_signature,
                )
            )
        else:
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

        # ----------------------------------------------------
        # CACHE VALIDITY
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

        # ----------------------------------------------------
        # GENERATE / REUSE FULL SUMMARY
        # ----------------------------------------------------

        generation_succeeded = False

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

            generated_sections = call_ai(
                groq_key,
                openrouter_key,
                day,
                relevant_commits,
            )

            if generated_sections is not None:
                sections = generated_sections

                summary_markdown = (
                    sections_to_markdown(
                        sections
                    )
                )

                full_signature_out = (
                    current_signature
                )

                generation_succeeded = True

                print(
                    f"Saved new structured "
                    f"summary for {day}."
                )

            elif old_is_good:
                # Keep the previous digest if AI fails.
                sections = (
                    old_sections
                    if old_has_structured_sections
                    else []
                )

                summary_markdown = (
                    old_summary_text
                )

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
        # BUILD NEW — LAST 3 HRS
        # ----------------------------------------------------

        new_items = []
        new_summary_markdown = ""
        new_relevant_count = 0

        if day == today:
            # Only advance the NEW baseline after a successful
            # full summary that actually contains the new data.
            if (
                generation_succeeded
                and sections
            ):
                new_items = find_new_items(
                    sections,
                    newly_added_ids,
                )

                new_summary_markdown = (
                    items_to_markdown(
                        new_items
                    )
                )

                represented_new_ids = (
                    represented_commit_ids(
                        new_items
                    )
                )

                new_relevant_count = len(
                    represented_new_ids
                )

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
                # No relevant commits changed during this run.
                #
                # The previous NEW block is now older than
                # the current 3-hour window, so clear it.
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
                # AI refresh failed.
                #
                # Keep the OLD baseline so the same newly-added
                # commits will be retried on the next run.
                new_baseline_out = (
                    old_new_baseline
                )

                print(
                    "NEW tracking baseline preserved "
                    "because summary generation failed."
                )

        else:
            # Historical days never display NEW.
            new_items = []
            new_summary_markdown = ""
            new_relevant_count = 0
            new_baseline_out = (
                current_signature
            )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        summaries[day] = {
            # Total development activity.
            "commit_count": len(
                raw_commits
            ),

            # Commits surviving the deterministic
            # player-relevance filter.
            "relevant_commit_count": len(
                relevant_commits
            ),

            # Stable source commit list represented by
            # the full day's input.
            "relevant_signature": (
                full_signature_out
            ),

            # Baseline used to calculate NEW on the
            # next 3-hour update.
            "new_baseline_signature": (
                new_baseline_out
            ),

            "prompt_version": (
                PROMPT_VERSION
            ),

            # NEW structured format.
            "sections": sections,

            # Backward-compatible Markdown.
            "summary": summary_markdown,

            # NEW — LAST 3 HRS metadata.
            "new_items": new_items,
            "new_relevant_count": (
                new_relevant_count
            ),

            # Backward-compatible Markdown for the
            # existing RSS generator.
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
