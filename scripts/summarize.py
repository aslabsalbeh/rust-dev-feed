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

# Changing this forces one fresh summary.
PROMPT_VERSION = "player-relevance-v2"


BAD_MARKERS = (
    "We need to produce",
    "Let's identify themes",
    "We have many commits",
    "<unk>",
    "AI summary temporarily unavailable",
)


# -------------------------------------------------------------------
# PLAYER-RELEVANCE FILTER
# -------------------------------------------------------------------

# Strong indicators that something affects actual Rust players.
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
    "gas station",
    "nexus",
    "map",

    # Player-facing content
    "bandage",
    "flashlight",
    "catapult",
    "ballista",
    "firework",
)


# Especially strong bug symptoms. These get priority over visual polish.
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


# Things that are commonly internal development work.
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
    "ci ",
    "compiler",
)


# Visual/asset implementation details that are usually not useful enough
# for a player digest on their own.
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


# Player-visible visual changes that can still be interesting.
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


def commit_signature(commits):
    ids = sorted(str(commit["id"]) for commit in commits)
    return ",".join(ids)


def is_bad_summary(text):
    if not text:
        return True

    lowered = text.lower()

    for marker in BAD_MARKERS:
        if marker.lower() in lowered:
            return True

    return False


def commit_search_text(commit):
    """
    Combine branch and commit message for relevance analysis.

    Branch names are useful here because Facepunch branches often contain
    descriptive phrases such as fix_scientists_not_spawning.
    """
    return (
        f"{commit.get('branch', '')} "
        f"{commit.get('message', '')}"
    ).lower().replace("_", " ")


def contains_any(text, terms):
    return any(term in text for term in terms)


def player_relevance_score(commit):
    """
    Estimate how useful a commit is to a normal Rust player.

    This does NOT decide what the final summary says.
    It prevents obviously low-value development noise from crowding out
    useful gameplay changes and bug fixes.
    """
    text = commit_search_text(commit)

    score = 0

    # Concrete bug/glitch fixes receive the strongest preference.
    if contains_any(text, BUG_TERMS):
        score += 6

    # Player-facing subject matter.
    high_matches = sum(
        1 for term in HIGH_VALUE_TERMS
        if term in text
    )
    score += min(high_matches, 4) * 2

    # New gameplay/content additions can be interesting even if they are
    # not bug fixes.
    if re.search(
        r"\b(add|added|new|introduce|introduced)\b",
        text,
    ):
        if contains_any(text, HIGH_VALUE_TERMS):
            score += 3

    # Balance / behaviour changes.
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

    # Visible UI changes get some value, but much less than gameplay fixes.
    if contains_any(text, VISIBLE_VISUAL_TERMS):
        score += 1

    # Internal development work.
    if contains_any(text, TECHNICAL_TERMS):
        score -= 5

    # Asset/rendering trivia is heavily down-ranked.
    if contains_any(text, LOW_VALUE_VISUAL_TERMS):
        score -= 5

    # Explicit tests should generally not appear as player news.
    if re.search(
        r"\b(test|tests|testing)\b",
        text,
    ):
        score -= 4

    # Cleanup alone is almost never useful to players.
    if re.search(
        r"\b(cleanup|refactor|rename|renamed)\b",
        text,
    ):
        score -= 4

    # A concrete bug fix can rescue a technical-looking commit.
    #
    # Example:
    # "Fixed scientists not spawning in underwater labs"
    # must survive regardless of implementation details.
    if (
        contains_any(text, BUG_TERMS)
        and contains_any(text, HIGH_VALUE_TERMS)
    ):
        score += 5

    return score


def filter_player_relevant_commits(commits):
    """
    Keep commits that have a reasonable chance of mattering to players.

    We deliberately use a fairly permissive threshold so the deterministic
    filter does not accidentally delete an unusual but important change.
    Groq performs the final editorial selection.
    """
    scored = []

    for commit in commits:
        score = player_relevance_score(commit)

        scored.append(
            (score, commit)
        )

    # Highest-value commits first so the AI sees important fixes first.
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
        f"{len(relevant)} candidates."
    )

    # Helpful workflow logging.
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


def build_prompt(day, commits):
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

The commits have already passed an initial player-relevance filter.
You must perform a SECOND, stricter editorial pass.

COMMITS:

{chr(10).join(commit_text)}

CORE EDITORIAL RULE:

The digest answers:

"What happened in Rust development today that an ordinary Rust player
would actually want to know?"

Do NOT try to represent every commit.

It is better to publish 8 excellent bullets from 50 commits than
25 bullets containing development trivia.

PRIORITY 1 — ALWAYS PRESERVE WHEN SUPPORTED:

Concrete player-facing bug and glitch fixes.

Examples:
- Scientists not spawning at Underwater Labs
- An item not applying its healing effect
- A vehicle seat becoming unusable
- A weapon failing to reset after firing
- Players becoming stuck
- Incorrect damage or resource yields
- Crashes, disconnects or exploits

When a commit describes the actual symptom, PRESERVE THAT SYMPTOM.

BAD:
"Improved scientist spawning reliability."

GOOD:
"Fixed scientists not spawning in Underwater Labs and Cargo Ship."

Do not generalize a specific useful bug fix into vague wording.

PRIORITY 2:

- Gameplay mechanic changes
- Balance changes
- New weapons, items or usable content
- NPC and animal behaviour changes
- Monument and map changes
- Vehicle changes
- Weapons and equipment changes
- Loot/resource changes
- Meaningful server or client performance fixes with a stated
  player-visible impact

PRIORITY 3:

Player-visible UI, animation, model, audio or visual changes ONLY when
they are substantial enough that a normal player would reasonably notice
or care about them.

AGGRESSIVELY EXCLUDE:

- Texture resolution changes
- AO texture changes
- Font atlas changes
- Glyph generation
- LOD implementation details
- Radial blur implementation
- Vignette tuning
- Shader/render-pipeline implementation details
- Collider implementation changes unless they fix a gameplay problem
- Asset optimization with no stated gameplay impact
- Memory-size reductions with no stated gameplay impact
- Prefab cleanup
- Naming conventions
- Code cleanup
- Refactoring
- Developer/editor tools
- Automated tests
- Test assets
- Logging/debugging
- Code generation
- Internal implementation details
- Branch-management work

IMPORTANT:

Something being visible does NOT automatically make it worth reporting.

For example:

"Radial blur added to the rendering pipeline and vignette toned down"

is normally NOT useful enough for this player digest.

Likewise:

"AO texture reduced from 1k to 512px"

is NOT useful unless the source explicitly connects it to a meaningful
player-facing improvement.

Never sacrifice a concrete gameplay bug fix to make room for cosmetic,
rendering or technical information.

WORK IN PROGRESS:

Development commits may describe unreleased work.

Do not imply that a feature is currently live merely because developers
are working on it.

When necessary, describe it as:
- development work
- work in progress
- upcoming content
- being developed

OUTPUT:

- Aim for roughly 8 to 15 bullets total when enough worthwhile changes exist.
- Fewer than 8 is completely acceptable when little meaningful happened.
- Never add weak bullets just to reach a number.
- Use 2 to 6 short topic sections.
- Put the most player-important sections first.
- Use Markdown headings beginning with ###.
- Use "-" bullets.
- Keep each bullet concise.
- Combine duplicate commits describing the same underlying change.
- Preserve specific item, NPC, monument and gameplay names.
- Preserve useful concrete symptoms from bug-fix commits.
- Do not mention developer names.
- Do not mention commit IDs.
- Do not mention branch names in the output.
- Do not speculate.
- Do not invent effects or benefits not stated by the commits.
- Do not include a title.
- Do not include the date.
- Start directly with the first section.
- Return ONLY the finished digest.
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


def summarize_day(
    groq_key,
    openrouter_key,
    day,
    commits,
):
    relevant_commits = filter_player_relevant_commits(
        commits
    )

    # Safety fallback:
    # If our deterministic filter somehow rejects everything,
    # let the AI inspect the raw commits rather than publishing nothing.
    if not relevant_commits:
        print(
            "Relevance filter found no candidates; "
            "using raw commits as safety fallback."
        )
        relevant_commits = commits

    prompt = build_prompt(
        day,
        relevant_commits,
    )

    if groq_key:
        print(
            f"Trying Groq for {day}..."
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
                f"Groq succeeded for {day}."
            )
            return summary

    if openrouter_key:
        print(
            f"Trying OpenRouter fallback "
            f"for {day}..."
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
                f"OpenRouter succeeded "
                f"for {day}."
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
        commits_for_day = grouped[day]

        signature = commit_signature(
            commits_for_day
        )

        old_entry = old_summaries.get(
            day
        )

        old_is_good = (
            old_entry
            and not is_bad_summary(
                old_entry.get(
                    "summary",
                    "",
                )
            )
        )

        signature_matches = (
            old_entry
            and old_entry.get(
                "commit_signature"
            ) == signature
        )

        prompt_matches = (
            old_entry
            and old_entry.get(
                "prompt_version"
            ) == PROMPT_VERSION
        )

        if (
            old_is_good
            and signature_matches
            and prompt_matches
        ):
            summaries[day] = old_entry

            if day == today:
                print(
                    f"No new commits for {day}; "
                    "reusing cached summary."
                )
            else:
                print(
                    f"Keeping cached summary "
                    f"for {day}."
                )

            continue

        if not signature_matches:
            reason = "commits changed"
        elif not prompt_matches:
            reason = "prompt/filter changed"
        else:
            reason = "cached summary invalid"

        print(
            f"Summary refresh needed for {day} "
            f"({reason}); evaluating "
            f"{len(commits_for_day)} commits..."
        )

        new_summary = summarize_day(
            groq_key,
            openrouter_key,
            day,
            commits_for_day,
        )

        if new_summary is not None:
            summaries[day] = {
                "commit_count": len(
                    commits_for_day
                ),
                "commit_signature": signature,
                "prompt_version": PROMPT_VERSION,
                "summary": new_summary,
            }

            print(
                f"Saved new summary for {day}."
            )

        elif old_is_good:
            # Preserve the previous good summary.
            #
            # Its old prompt/signature values remain unchanged,
            # so a future workflow run will automatically retry.
            summaries[day] = old_entry

            print(
                f"Preserved previous good "
                f"summary for {day}."
            )

        else:
            summaries[day] = {
                "commit_count": len(
                    commits_for_day
                ),
                "commit_signature": "",
                "prompt_version": "",
                "summary": (
                    "AI summary temporarily unavailable. "
                    "The development commit archive was "
                    "updated successfully."
                ),
            }

            print(
                f"No previous valid summary "
                f"available for {day}."
            )

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
