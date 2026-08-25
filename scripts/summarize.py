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

# Maximum number of relevant source commits sent in one first-pass request.
CHUNK_SIZE = 25

# Change this whenever the summary logic/prompt structure changes.
PROMPT_VERSION = "structured-read-state-v4-strategic-gameplay"


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
    
    # Balance / buffs / nerfs
    "buff",
    "buffs",
    "buffed",
    "nerf",
    "nerfs",
    "nerfed",
    "balance",
    "rebalance",

    # Combat systems
    "sam site",
    "sam sites",
    "drone",
    "drones",
    "missile",
    "missiles",
    "explosive",
    "explosives",
    "proximity fuse",
    "aim error",

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
        # Player-facing balance / configuration
    "stack size",
    "stack sizes",
    "inventory capacity",
    "capacity",
    "crafting cost",
    "crafting costs",
    "durability",
    "fire rate",
    "cooldown",
    "respawn time",
    "fuel consumption",
    "gather rate",
    "drop rate",

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

STRATEGIC_GAMEPLAY_TERMS = (
    # Explicit balance
    "buff",
    "buffs",
    "buffed",
    "nerf",
    "nerfs",
    "nerfed",
    "rebalance",
    "balance",

    # Base / upkeep / building rules
    "upkeep",
    "decay",
    "tool cupboard",
    "tc auth",
    "code lock",
    "building privilege",
    "authorized",
    "authed",

    # Groups / player limits
    "group",
    "team",
    "player limit",

    # Inventory / economy
    "stack size",
    "stack sizes",
    "capacity",
    "crafting cost",
    "resource cost",
    "resource rate",
    "gather rate",
    "drop rate",

    # Combat / counters / defenses
    "sam site",
    "sam sites",
    "drone",
    "drones",
    "turret",
    "missile",
    "missiles",
    "proximity fuse",
    "target",
    "targeting",
    "counter",
    "counterplay",
    "explosive",
    "explosives",

    # Other strategic values
    "damage",
    "range",
    "speed",
    "fire rate",
    "cooldown",
    "respawn",
)

SCORE_WEIGHTS = {
    "strategic_gameplay": 7,
    "bug": 6,
    "high_value_term": 2,
    "new_high_value": 3,
    "balance_change": 5,
    "explicit_buff_nerf": 6,
    "visible_visual": 1,
    "technical": -5,
    "low_value_visual": -5,
    "test_only": -4,
    "cleanup_refactor": -4,
    "player_facing_bug_rescue": 5,
}

RELEVANCE_THRESHOLD = 2

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

    strategic_change = contains_any(
        text,
        STRATEGIC_GAMEPLAY_TERMS,
    )

    if strategic_change:
        score += SCORE_WEIGHTS["strategic_gameplay"]

    if contains_any(text, BUG_TERMS):
        score += SCORE_WEIGHTS["bug"]

    high_matches = sum(
        1
        for term in HIGH_VALUE_TERMS
        if term in text
    )

    score += min(
        high_matches,
        4,
    ) * SCORE_WEIGHTS["high_value_term"]

    if re.search(
        r"\b(add|added|new|introduce|introduced)\b",
        text,
    ):
        if contains_any(
            text,
            HIGH_VALUE_TERMS,
        ):
            score += SCORE_WEIGHTS["new_high_value"]

    
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
            "buff",
            "buffs",
            "buffed",
            "nerf",
            "nerfs",
            "nerfed",
            "rebalance",
            "sam site",
            "sam sites",
            "drone",
            "drones",
            "proximity fuse",
            "stack size",
            "stack sizes",
            "inventory capacity",
            "crafting cost",
            "durability",
            "fire rate",
            "cooldown",
            "respawn time",
            "fuel consumption",
            "gather rate",
            "drop rate",
        ),
    ):
        score += SCORE_WEIGHTS["balance_change"]

    # Explicit buffs/nerfs and meaningful combat interaction changes
    # are high-priority player information.
    if contains_any(
        text,
        (
            "buff",
            "buffs",
            "buffed",
            "nerf",
            "nerfs",
            "nerfed",
            "rebalance",
        ),
    ):
        score += SCORE_WEIGHTS["explicit_buff_nerf"]

    if contains_any(
        text,
        VISIBLE_VISUAL_TERMS,
    ):
        score += SCORE_WEIGHTS["visible_visual"]

    if contains_any(
        text,
        TECHNICAL_TERMS,
    ):
        score += SCORE_WEIGHTS["technical"]

    if contains_any(
        text,
        LOW_VALUE_VISUAL_TERMS,
    ):
        score += SCORE_WEIGHTS["low_value_visual"]

    # Test-related wording should only be penalized when the commit
    # does not also describe a meaningful player-facing gameplay change.
    if (
        re.search(
            r"\b(test|tests|testing)\b",
            text,
        )
        and not strategic_change
    ):
        score += SCORE_WEIGHTS["test_only"]

    if re.search(
        r"\b(cleanup|refactor|rename|renamed)\b",
        text,
    ):
        score += SCORE_WEIGHTS["cleanup_refactor"]

    # Strong rescue rule for concrete player-facing bug fixes.
    if (
        contains_any(text, BUG_TERMS)
        and contains_any(
            text,
            HIGH_VALUE_TERMS,
        )
    ):
        score += SCORE_WEIGHTS["player_facing_bug_rescue"]

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
        if score >= RELEVANCE_THRESHOLD
    ]

    print(
        f"Player relevance filter: "
        f"{len(commits)} raw commits -> "
        f"{len(relevant)} useful candidates."
    )

    if log_filtered:
        for score, commit in scored:
            if score < RELEVANCE_THRESHOLD:
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
# PROMPTS
# ============================================================

def commits_to_prompt_text(commits):
    blocks = []

    for commit in commits:
        branch = commit.get(
            "branch",
            "",
        )

        if branch.startswith("main/"):
            branch = branch[5:]

        blocks.append(
            "\n".join(
                [
                    f"Commit ID: {commit['id']}",
                    f"Branch context: {branch}",
                    f"Message: {commit.get('message', '')}",
                ]
            )
        )

    return "\n\n".join(blocks)


def build_full_prompt(day, commits):
    source_text = commits_to_prompt_text(
        commits
    )

    return f"""
Create a concise daily Rust development digest for RUST PLAYERS.

These are official Facepunch development commits from {day}.

SOURCE COMMITS:

{source_text}

The digest answers:

"What happened in Rust development today that an ordinary Rust player
would actually want to know?"

Do NOT try to represent every commit.

PRIORITIZE:
- Concrete player-facing bug and glitch fixes
- Gameplay mechanic changes
- Balance changes
- Player-visible numeric/configuration changes such as stack sizes,
  inventory limits, crafting costs, durability, damage, fire rate,
  cooldowns, loot quantities, resource rates, fuel use, and timers
- Weapons, equipment, items and deployables
- NPC and animal behaviour
- Monuments and world changes
- Vehicles
- Loot and resource changes
- Crashes, disconnects and exploits
- Meaningful player-visible UI problems
- Buffs, nerfs and balance changes, including work-in-progress changes
- Changes to combat interactions between existing systems, weapons,
  defenses, vehicles, drones, explosives, NPCs or deployables
- Buffs, nerfs and balance changes
- Strategic gameplay-rule changes, including base upkeep, decay,
  TC/code-lock authorization, group mechanics, raiding, defenses,
  counters, inventory limits and resource/economic changes
- Changes to how existing gameplay systems interact, even if no
  new item is added and no bug is being fixed

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

BUFFS / NERFS / GAMEPLAY INTERACTIONS:

Buffs and nerfs are HIGH-PRIORITY information for Rust players.

Include meaningful changes to how existing gameplay systems interact,
even when no new item is being added and no bug is being fixed.

Do not exclude a change merely because it is marked WIP.
If it is work in progress, include it when player-relevant and clearly
label it as work in progress rather than implying it is live.

For example, this MUST be considered important:

"SAM site vs drone buffs wip: Missiles use a proximity fuse against
drones, lead vs them without aim error at 2.25x speed, and destroy
drone-dropped explosives mid-air."

A suitable summary would be:

"SAM site anti-drone buffs are in development: missiles now use
proximity fuses against drones, lead them at 2.25× speed without aim
error, and can destroy drone-dropped explosives in mid-air."

PLAYER-FACING NUMERIC CHANGES:

Do not exclude a commit merely because it is a simple numeric,
configuration, prefab, or data-value change.

If the changed value materially affects what players can carry, craft,
use, damage, loot, gather, consume, or wait for, it belongs in the digest.

For example, this MUST be included:

"Reduced stack size for F1s 5 > 3, Bee nades 5 > 3,
Flashbangs 5 > 3, Molotovs 5 > 3"

A good summary would be:

"Reduced F1 grenade, Bee grenade, Flashbang, and Molotov
stack sizes from 5 to 3."

Development commits may describe unreleased work.
Clearly label work-in-progress or upcoming features when needed.

CRITICAL SOURCE-ID RULES:

Every output bullet MUST include the exact source Commit IDs that support it.

If several commits describe the same underlying change, combine them
into one bullet and include all relevant Commit IDs.

Never invent a Commit ID.

Only use Commit IDs from SOURCE COMMITS above.

Do not include a commit ID merely because it is about a similar topic.
The ID must genuinely support that exact bullet.

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

STRATEGIC GAMEPLAY CHANGES:

Treat changes to existing gameplay rules as HIGH PRIORITY.

Ask:

"Could knowing this change alter how a Rust player builds, raids,
defends, fights, carries equipment, manages a base, organizes a group,
farms resources, or chooses a strategy?"

If YES, strongly prefer including it.

Do not require the commit to use words like "buff", "nerf", "fix",
or "balance".

Do not exclude important gameplay changes merely because the same
commit also contains tests, technical notes, configuration details,
or implementation information.

Work-in-progress changes may still be important to players.
Include important WIP changes, but clearly describe them as
in development rather than implying they are live.

Examples that MUST be considered important:

- Reducing grenade stack sizes from 5 to 3.
- SAM sites gaining stronger anti-drone targeting and the ability
  to destroy drone-dropped explosives.
- Group upkeep counting players authorized on code locks controlled
  by the TC even when they are not directly authorized on the TC.
  
OUTPUT RULES:
- Aim for roughly 8 to 15 worthwhile bullets total.
- Fewer is fine when little meaningful happened.
- Use 2 to 6 short topic sections.
- Put the most important sections first.
- Keep bullet text concise.
- Combine duplicate commits.
- Preserve useful item, NPC, monument and gameplay names.
- Preserve concrete bug symptoms.
- Do not mention developer names.
- Do not mention commit IDs inside bullet text.
- Do not mention branch names inside bullet text.
- Do not speculate.
- Do not include a title or date.
- Return ONLY the JSON object.
"""


def build_chunk_prompt(day, commits):
    source_text = commits_to_prompt_text(
        commits
    )

    return f"""
Summarize this subset of Rust development commits for Rust players.

Date:
{day}

SOURCE COMMITS:

{source_text}

This is only one chunk from a larger day.

Return ONLY valid JSON using this structure:

{{
  "sections": [
    {{
      "title": "NPC & AI",
      "items": [
        {{
          "text": "Fixed scientists not spawning in Underwater Labs.",
          "commit_ids": [615201]
        }}
      ]
    }}
  ]
}}

Rules:
- Keep only genuinely player-relevant changes.
- Prefer bugs, gameplay, items, NPCs, animals, vehicles,
  monuments, UI issues, exploits, crashes and balance changes.
- Exclude tests, refactors, rendering trivia, asset optimization,
  logging and developer tooling.
- Preserve concrete bug symptoms.
- Every bullet MUST include exact source Commit IDs.
- Never invent commit IDs.
- Only use Commit IDs supplied above.
- Combine closely related commits.
- HIGH PRIORITY: buffs, nerfs, balance changes and strategic gameplay-rule changes.
- Include changes to upkeep, decay, TC/code-lock authorization, group mechanics,
  combat counters, defenses, inventory limits, resource costs and other rules
  that could change player strategy.
- Do not dismiss an important gameplay change because the commit also mentions tests.
- Include important WIP gameplay changes, but clearly identify them as work in progress.
- Do not mention developer names.
- Do not mention commit IDs inside bullet text.
- Do not mention branch names inside bullet text.
- Return ONLY JSON.
"""


def build_merge_prompt(day, chunk_sections):
    input_json = json.dumps(
        chunk_sections,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
Merge these structured Rust development summary fragments into one final
player-focused daily digest for {day}.

INPUT:

{input_json}

Return ONLY valid JSON using exactly this structure:

{{
  "sections": [
    {{
      "title": "NPC & AI",
      "items": [
        {{
          "text": "Fixed scientists not spawning in Underwater Labs.",
          "commit_ids": [615201]
        }}
      ]
    }}
  ]
}}

Rules:
- Preserve all valid source commit IDs.
- Never invent commit IDs.
- When merging bullets, combine their commit_ids.
- Merge duplicate or overlapping bullets.
- Preserve strategic gameplay changes, buffs, nerfs, economy/upkeep changes
  and new gameplay interactions; do not discard them in favor of minor bug fixes.
- Preserve concrete player-facing bug symptoms.
- Prefer gameplay, bugs, NPCs, animals, items, weapons,
  vehicles, monuments and meaningful UI fixes.
- Include player-facing numeric/configuration changes such as
  stack sizes, inventory limits, crafting costs, durability,
  damage, fire rate, cooldowns, loot quantities and resource rates.
- Do not dismiss a change just because it is a simple numeric value edit.
- Drop technical/internal trivia if any remains.
- Aim for 2 to 6 sections.
- Aim for roughly 8 to 15 worthwhile bullets total.
- Fewer is fine.
- Do not mention developer names.
- Do not mention commit IDs inside bullet text.
- Do not include a title or date.
- Return ONLY JSON.
"""


# ============================================================
# STRUCTURED RESPONSE PARSING
# ============================================================

def strip_code_fence(text):
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1].strip() == "```"
        ):
            lines = lines[:-1]

        text = "\n".join(
            lines
        ).strip()

    return text


def parse_structured_summary(
    text,
    allowed_commit_ids,
):
    text = strip_code_fence(
        text
    )

    try:
        data = json.loads(
            text
        )
    except Exception as error:
        print(
            f"Could not parse AI JSON: "
            f"{error}"
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
# MARKDOWN BACKWARD COMPATIBILITY
# ============================================================

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


# ============================================================
# API CALL
# ============================================================

def call_chat_api(
    url,
    api_key,
    model,
    prompt,
    provider_name,
    allowed_commit_ids,
):
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.1,
    }

    # Groq supports JSON mode, which makes large structured
    # responses much more reliable.
    if provider_name == "Groq":
        payload[
            "response_format"
        ] = {
            "type": "json_object"
        }

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
            json=payload,
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


# ============================================================
# PROVIDER WRAPPER
# ============================================================

def request_sections(
    groq_key,
    openrouter_key,
    prompt,
    allowed_ids,
    label,
):
    if groq_key:
        print(
            f"Trying Groq for {label}..."
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
                f"Groq succeeded for {label}."
            )
            return sections

    if openrouter_key:
        print(
            f"Trying OpenRouter fallback "
            f"for {label}..."
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
                f"for {label}."
            )
            return sections

    return None


# ============================================================
# CHUNKED SUMMARIZATION
# ============================================================

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


# ============================================================
# NEW — LAST 3 HRS
# ============================================================

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


def represented_commit_ids(
    items,
):
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
                    represented_commit_ids(
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
