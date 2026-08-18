import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


COMMITS_FILE = Path("site/commits.json")
SUMMARY_FILE = Path("site/summaries.json")

LOCAL_TZ = ZoneInfo("America/Toronto")

GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

OPENROUTER_MODEL = "google/gemma-4-31b-it:free"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

PROMPT_VERSION = "player-relevance-v3-new3h"


BAD_MARKERS = (
    "We need to produce",
    "Let's identify themes",
    "We have many commits",
    "<unk>",
    "AI summary temporarily unavailable",
)


HIGH_VALUE_TERMS = (
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
    "monument",
    "underwater lab",
    "underwater labs",
    "cargo ship",
    "cargo",
    "oilrig",
    "oil rig",
    "gas station",
    "nexus",
    "map",
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
    ).replace(tzinfo=timezone.utc)

    created_local = created_utc.astimezone(LOCAL_TZ)

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
        item
        for item in signature.split(",")
        if item
    }


def is_bad_summary(text):
    if not text:
        return True

    lowered = text.lower()

    return any(
        marker.lower() in lowered
        for marker in BAD_MARKERS
    )


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

    if contains_any(text, BUG_TERMS):
        score += 6

    high_matches = sum(
        1
        for term in HIGH_VALUE_TERMS
        if term in text
    )

    score += min(high_matches, 4) * 2

    if re.search(
        r"\b(add|added|new|introduce|introduced)\b",
        text,
    ):
        if contains_any(text, HIGH_VALUE_TERMS):
            score += 3

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

    if contains_any(text, VISIBLE_VISUAL_TERMS):
        score += 1

    if contains_any(text, TECHNICAL_TERMS):
        score -= 5

    if contains_any(text, LOW_VALUE_VISUAL_TERMS):
        score -= 5

    if re.search(
        r"\b(test|tests|testing)\b",
        text,
    ):
        score -= 4

    if re.search(
        r"\b(cleanup|refactor|rename|renamed)\b",
        text,
    ):
        score -= 4

    if (
        contains_any(text, BUG_TERMS)
        and contains_any(text, HIGH_VALUE_TERMS)
    ):
        score += 5

    return score


def filter_player_relevant_commits(
    commits,
    log_filtered=False,
):
    scored = []

    for commit in commits:
        score = player_relevance_score(commit)
        scored.append((score, commit))

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
                    commit.get("message", "")
                    .replace("\n", " ")
                    .replace("\r", " ")
                )

                print(
                    f"  Filtered ({score:+d}): "
                    f"{message[:100]}"
                )

    return relevant


def build_full_prompt(day, commits):
    commit_text = []

    for commit in commits:
        branch = commit.get("branch", "")

        if branch.startswith("main/"):
            branch = branch[5:]

        commit_text.append(
            "\n".join(
                [
                    f"Branch context: {branch}",
                    f"Message: {commit.get('message', '')}",
                ]
            )
        )

    return f"""
Create a concise daily Rust development digest for RUST PLAYERS.

These are official Facepunch development commits from {day}.

COMMITS:

{chr(10).join(commit_text)}

The digest answers:

"What happened in Rust development today that an ordinary Rust player
would actually want to know?"

Do NOT try to represent every commit.

PRIORITIZE:
- Concrete player-facing bug and glitch fixes
- Gameplay mechanic changes
- Balance changes
- Weapons, equipment, items and deployables
- NPC and animal behavior
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

OUTPUT:
- Aim for roughly 8 to 15 worthwhile bullets.
- Fewer is fine when little meaningful happened.
- Use 2 to 6 short topic sections.
- Put the most important sections first.
- Use Markdown headings beginning with ###.
- Use "-" bullets.
- Keep bullets concise.
- Combine duplicate commits.
- Preserve useful item, NPC, monument and gameplay names.
- Preserve concrete bug symptoms.
- Do not mention developers, commit IDs or branch names.
- Do not speculate.
- Do not include a title or date.
- Start directly with the first section.
- Return ONLY the finished digest.
"""


def build_new_prompt(commits):
    commit_text = []

    for commit in commits:
        branch = commit.get("branch", "")

        if branch.startswith("main/"):
            branch = branch[5:]

        commit_text.append(
            "\n".join(
                [
                    f"Branch context: {branch}",
                    f"Message: {commit.get('message', '')}",
                ]
            )
        )

    return f"""
Summarize ONLY these newly-added Rust development commits for players.

These commits appeared since the previous feed update.

NEW COMMITS:

{chr(10).join(commit_text)}

This will appear under:

NEW — LAST 3 HRS

Rules:
- Include only genuinely player-relevant information.
- Preserve concrete bug symptoms.
- Prefer gameplay fixes, bugs, content, NPCs, animals, weapons,
  vehicles, monuments, items and balance changes.
- Exclude technical implementation details.
- Exclude tests, refactors, rendering trivia, asset optimization,
  debugging and developer tooling.
- Do not mention commit IDs, developers or branch names.
- Combine commits that describe the same underlying change.
- Do not create sections or headings.
- Return ONLY a short Markdown bullet list.
- Use "-" for every bullet.
- 1 to 5 bullets is ideal.
- Do not add filler just to reach a number.
"""


def call_chat_api(
    url,
    api_key,
    model,
    prompt,
    provider_name,
):
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
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
            f"{provider_name} network error: {error}"
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
            data["choices"][0]["message"]["content"]
            .strip()
        )

    except Exception:
        print(
            f"{provider_name} returned "
            "an invalid response."
        )
        return None

    if is_bad_summary(text):
        print(
            f"{provider_name} returned "
            "rejected AI output."
        )
        return None

    return text


def call_ai(
    groq_key,
    openrouter_key,
    prompt,
    label,
):
    if groq_key:
        print(
            f"Trying Groq for {label}..."
        )

        summary = call_chat_api(
            GROQ_URL,
            groq_key,
            GROQ_MODEL,
            prompt,
            "Groq",
        )

        if summary is not None:
            print(
                f"Groq succeeded for {label}."
            )
            return summary

    if openrouter_key:
        print(
            f"Trying OpenRouter fallback "
            f"for {label}..."
        )

        summary = call_chat_api(
            OPENROUTER_URL,
            openrouter_key,
            OPENROUTER_MODEL,
            prompt,
            "OpenRouter",
        )

        if summary is not None:
            print(
                f"OpenRouter succeeded for {label}."
            )
            return summary

    return None


def main():
    groq_key = os.environ.get(
        "GROQ_API_KEY"
    )

    openrouter_key = os.environ.get(
        "OPENROUTER_API_KEY"
    )

    if not groq_key and not openrouter_key:
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

    grouped = group_by_day(commits)

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
                log_filtered=(day == today),
            )
        )

        relevant_signature = commit_signature(
            relevant_commits
        )

        old_entry = old_summaries.get(day)

        old_is_good = (
            old_entry
            and not is_bad_summary(
                old_entry.get(
                    "summary",
                    "",
                )
            )
        )

        old_signature = (
            old_entry.get(
                "relevant_signature",
                old_entry.get(
                    "commit_signature",
                    "",
                ),
            )
            if old_entry
            else ""
        )

        old_ids = parse_signature(
            old_signature
        )

        current_ids = commit_ids(
            relevant_commits
        )

        new_ids = (
            current_ids - old_ids
            if old_entry
            else set()
        )

        newly_relevant_commits = [
            commit
            for commit in relevant_commits
            if str(commit["id"]) in new_ids
        ]

        prompt_matches = (
            old_entry
            and old_entry.get(
                "prompt_version"
            ) == PROMPT_VERSION
        )

        relevant_changed = (
            relevant_signature
            != old_signature
        )

        # ------------------------------------------------------------
        # FULL DAILY SUMMARY
        # ------------------------------------------------------------

        if (
            old_is_good
            and not relevant_changed
            and prompt_matches
        ):
            full_summary = old_entry["summary"]

            print(
                f"No player-relevant changes for {day}; "
                "reusing full daily summary."
            )

        else:
            if not relevant_commits:
                full_summary = (
                    old_entry.get("summary")
                    if old_is_good
                    else "No significant player-facing updates."
                )

            else:
                print(
                    f"Refreshing full summary for {day}; "
                    f"{len(relevant_commits)} relevant commits."
                )

                full_summary = call_ai(
                    groq_key,
                    openrouter_key,
                    build_full_prompt(
                        day,
                        relevant_commits,
                    ),
                    f"{day} full digest",
                )

                if full_summary is None:
                    if old_is_good:
                        full_summary = old_entry["summary"]
                    else:
                        full_summary = (
                            "AI summary temporarily unavailable. "
                            "The development commit archive "
                            "was updated successfully."
                        )

        # ------------------------------------------------------------
        # NEW — LAST 3 HRS
        # ------------------------------------------------------------

        new_summary = ""
        new_relevant_count = 0

        # Only the current day gets a NEW section.
        if day == today:
            if newly_relevant_commits:
                new_relevant_count = len(
                    newly_relevant_commits
                )

                print(
                    f"{new_relevant_count} new player-relevant "
                    f"commit(s) since previous update."
                )

                new_summary = call_ai(
                    groq_key,
                    openrouter_key,
                    build_new_prompt(
                        newly_relevant_commits
                    ),
                    f"{day} NEW — LAST 3 HRS",
                )

                if new_summary is None:
                    # Better to omit NEW than show stale/incorrect data.
                    new_summary = ""
                    new_relevant_count = 0

            else:
                print(
                    f"No new player-relevant commits "
                    f"for {day}."
                )

        summaries[day] = {
            # Raw development activity count
            "commit_count": len(raw_commits),

            # Number that actually passed our relevance filter
            "relevant_commit_count": len(
                relevant_commits
            ),

            # Signature is now based on player-relevant commits.
            # Trivial commits therefore don't trigger AI unnecessarily.
            "relevant_signature": relevant_signature,

            "prompt_version": PROMPT_VERSION,
            "summary": full_summary,

            # NEW section for the current 3-hour update window
            "new_relevant_count": new_relevant_count,
            "new_summary": new_summary,
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
