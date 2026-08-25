import json


def commits_to_prompt_text(commits):
    blocks = []
    for commit in commits:
        branch = commit.get("branch", "")
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
    source_text = commits_to_prompt_text(commits)
    return f"""
Create a concise daily Rust development digest for RUST PLAYERS.

These are official Facepunch development commits from {day}.

SOURCE COMMITS:

{source_text}

The digest answers:
"What happened in Rust development today that an ordinary Rust player would actually want to know?"

Do NOT try to represent every commit.

PRIORITIZE:
- Concrete player-facing bug and glitch fixes
- Gameplay mechanic changes
- Buffs, nerfs and balance changes, including important work-in-progress changes
- Player-visible numeric/configuration changes such as stack sizes, inventory limits,
  crafting costs, durability, damage, fire rate, cooldowns, loot quantities,
  resource rates, fuel use and timers
- Strategic gameplay-rule changes, including base upkeep, decay, TC/code-lock
  authorization, group mechanics, raiding, defenses, counters and resource/economic changes
- Changes to how existing gameplay systems interact, even if no new item is added
  and no bug is being fixed
- Weapons, equipment, items and deployables
- NPC and animal behaviour
- Monuments and world changes
- Vehicles
- Loot and resource changes
- Crashes, disconnects and exploits
- Meaningful player-visible UI problems

Preserve concrete bug symptoms.
BAD: "Improved scientist spawning reliability."
GOOD: "Fixed scientists not spawning in Underwater Labs and Cargo Ship."

STRATEGIC GAMEPLAY CHANGES:
Treat changes to existing gameplay rules as HIGH PRIORITY.
Ask: "Could knowing this change alter how a Rust player builds, raids, defends,
fights, carries equipment, manages a base, organizes a group, farms resources,
or chooses a strategy?"
If YES, strongly prefer including it.
Do not require words like "buff", "nerf", "fix", or "balance".
Do not exclude important gameplay changes merely because the same commit also
contains tests, technical notes, configuration details, or implementation information.
Important WIP changes should be included but clearly described as in development.

Examples that MUST be considered important:
- Reducing grenade stack sizes from 5 to 3.
- SAM sites gaining stronger anti-drone targeting and the ability to destroy
  drone-dropped explosives.
- Group upkeep counting players authorized on code locks controlled by the TC,
  even if those players are not directly authorized on the TC.

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
- Automated tests that do not describe a meaningful gameplay change
- Logging/debugging
- Internal implementation details

Never sacrifice a concrete gameplay or strategic change to make room for cosmetic,
rendering or technical information.

CRITICAL SOURCE-ID RULES:
Every output bullet MUST include the exact source Commit IDs that support it.
If several commits describe the same underlying change, combine them into one bullet
and include all relevant Commit IDs.
Never invent a Commit ID. Only use IDs supplied above.

Return ONLY valid JSON, with no Markdown or code fence, using exactly:
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
- Aim for roughly 8 to 15 worthwhile bullets total; fewer is fine.
- Use 2 to 6 short topic sections and put the most important first.
- Keep bullet text concise and combine duplicate commits.
- Preserve useful item, NPC, monument and gameplay names and concrete bug symptoms.
- Do not mention developer names, commit IDs, or branch names inside bullet text.
- Do not speculate or imply WIP changes are live.
- Do not include a title or date.
- Return ONLY the JSON object.
"""


def build_chunk_prompt(day, commits):
    source_text = commits_to_prompt_text(commits)
    return f"""
Summarize this subset of Rust development commits for Rust players.
Date: {day}

SOURCE COMMITS:
{source_text}

This is one chunk from a larger day.

HIGH PRIORITY:
- Concrete bugs and gameplay fixes
- Buffs, nerfs and balance changes
- Strategic gameplay-rule changes
- Upkeep, decay, TC/code-lock authorization and group mechanics
- Combat counters, defenses and targeting interactions
- Inventory limits, stack sizes, crafting/resource costs and other player-facing values
- Important WIP gameplay changes, clearly labeled as work in progress

Do not dismiss an important gameplay change because the commit also mentions tests.
Exclude refactors, rendering trivia, asset optimization, logging and developer tooling
when they have no meaningful player-facing effect.
Preserve concrete bug symptoms.

Every bullet MUST include exact source Commit IDs. Never invent IDs and only use IDs above.
Combine closely related commits.

Return ONLY valid JSON:
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
"""


def build_merge_prompt(day, chunk_sections):
    input_json = json.dumps(chunk_sections, ensure_ascii=False, indent=2)
    return f"""
Merge these structured Rust development summary fragments into one final
player-focused daily digest for {day}.

INPUT:
{input_json}

Preserve all valid source commit IDs and never invent IDs.
When merging bullets, combine their commit_ids.
Merge duplicates while preserving concrete player-facing bug symptoms.
Preserve strategic gameplay changes, buffs, nerfs, economy/upkeep changes and new
gameplay interactions; do not discard them in favor of minor bug fixes or cosmetic polish.
Drop technical/internal trivia if any remains.
Aim for 2 to 6 sections and roughly 8 to 15 worthwhile bullets total; fewer is fine.
Do not mention developer names or commit IDs inside bullet text.
Do not include a title or date.

Return ONLY valid JSON:
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
"""

def build_rescue_prompt(day, commits):
    source_text = commits_to_prompt_text(commits)
    return f"""
A previous Rust player digest omitted the HIGH-IMPACT commits below.
Create concise rescue bullets for ONLY the genuinely player-impacting changes
in these commits so they can be appended to the existing daily digest for {day}.

SOURCE COMMITS:
{source_text}

These commits were preselected because their relevance score is high, but still
apply judgment. Prioritize gameplay mechanics, buffs/nerfs, strategic interactions,
upkeep/economy, combat/defense changes, stack/inventory/configuration changes,
and concrete player-facing bug fixes.

IMPORTANT:
- If a change is work in progress, explicitly say that it is WIP/in development.
- Do not speculate or imply a WIP change is live.
- Exclude purely technical/rendering/refactor/test/logging details with no meaningful
  player-facing effect.
- Every bullet MUST include exact source Commit IDs from the commits above.
- Never invent Commit IDs.
- Do not mention commit IDs or branch names inside bullet text.
- Keep the result concise.

Return ONLY valid JSON:
{{
  "sections": [
    {{
      "title": "Gameplay & Balance",
      "items": [
        {{
          "text": "Concise player-facing description.",
          "commit_ids": [615201]
        }}
      ]
    }}
  ]
}}
"""

