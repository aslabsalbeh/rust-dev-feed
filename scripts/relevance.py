import re


HIGH_VALUE_TERMS = (
    # Bugs / broken behaviour
    "fix", "fixed", "bug", "glitch", "broken", "incorrect", "incorrectly",
    "not spawning", "not spawn", "not working", "couldn't", "could not",
    "unable to", "stuck", "missing", "disappear", "disappearing", "fail",
    "crash", "disconnect", "desync", "exploit",

    # Gameplay
    "damage", "healing", "health", "ammo", "weapon", "recoil", "reload",
    "melee", "projectile", "loot", "resource", "craft", "building",
    "deployable", "seat", "mountable", "mount", "vehicle",

    # Player-facing balance / configuration
    "stack size", "stack sizes", "inventory capacity", "capacity",
    "crafting cost", "crafting costs", "durability", "fire rate", "cooldown",
    "respawn time", "fuel consumption", "gather rate", "drop rate",

    # NPCs / animals
    "scientist", "npc", "animal", "livestock", "cow", "bull", "sheep",
    "horse", "dog", "bear", "wolf",

    # World / monuments
    "monument", "underwater lab", "underwater labs", "cargo ship", "cargo",
    "oilrig", "oil rig", "military base", "gas station", "nexus", "map",

    # Player-facing items/features
    "bandage", "flashlight", "catapult", "ballista", "firework",

    # Balance / buffs / nerfs
    "buff", "buffs", "buffed", "nerf", "nerfs", "nerfed", "balance",
    "rebalance",

    # Combat systems
    "sam site", "sam sites", "drone", "drones", "missile", "missiles",
    "explosive", "explosives", "proximity fuse", "aim error",
)


BUG_TERMS = (
    "fix", "fixed", "bug", "glitch", "broken", "incorrect", "incorrectly",
    "not spawning", "not spawn", "not working", "couldn't", "could not",
    "unable to", "stuck", "missing", "disappear", "crash", "disconnect",
    "desync", "exploit", "nre",
)


TECHNICAL_TERMS = (
    "refactor", "cleanup", "clean up", "codegen", "code gen", "test asset",
    "automated test", "unit test", "integration test", "debug", "logging",
    "log handler", "rename", "renamed", "naming convention", "editor tooling",
    "editor tool", "developer tool", "profiling", "instrumentation",
    "serialization", "source control", "build pipeline", "compiler",
)


LOW_VALUE_VISUAL_TERMS = (
    "atlas", "glyph", "font atlas", "dynamic font", "ao texture",
    "ambient occlusion", "texture reduced", "texture size", "texture resolution",
    "lod", "mesh collider", "shader", "render pipeline", "rendering pipeline",
    "vignette", "radial blur", "material naming", "material rename",
    "prefab cleanup", "re-export", "reexport",
)


LOW_VALUE_ASSET_OPTIMIZATION_TERMS = (
    # Asset/renderer work that can mention weapons, animals, or fixes but is still
    # implementation/cosmetic work rather than useful player-facing news.
    "texture optimisation", "texture optimisations",
    "texture optimization", "texture optimizations",
    "vram saved", "memory saved", "memory savings", "no visual difference",
    "ao pass", "ao caps", "material tweak", "material tweaks",
    "refraction scale", "transmittance", "worldmodel", "world model",
    "draws ->", "draw calls", "re-uv", "re-uv'd", "rebuilt lod",
)


EQUIPMENT_TERMS = (
    "helmet", "heavy plate", "armor", "armour", "weapon", "gun",
    "rifle", "pistol", "equipment", "equipped", "wearing", "worn",
)


PLAYER_AUDIO_EFFECT_TERMS = (
    "muffled", "muffle", "player voice", "player voices", "voice", "voices",
    "audio", "sound", "volume reduction", "volume",
)


VISIBLE_VISUAL_TERMS = (
    "animation", "model", "appearance", "icon", "effect", "visual",
    "third-person", "first-person", "viewmodel", "ui", "menu", "modal",
)


LOW_VALUE_PLAYER_POLISH_TERMS = (
    # Cosmetic / animation polish that is technically visible but not useful news
    "cosmetic polish", "visual polish", "animation polish",
    "idle animation", "idle animations", "animation jitter",
    "reaction animation", "reaction animations",
    "head icon", "icon rendering", "render order", "draw order",

    # Third-person prop/ejection details
    "third-person magazine", "third person magazine",
    "magazine drop", "magazines now drop", "magazine ejection",
    "shell ejection", "third-person ejection", "third person ejection",

    # Tiny recreational/minigame physics fixes
    "pool ball", "pool balls", "billiard", "billiards",

    # Internal disconnect/subscription bookkeeping
    "unsubscribe error", "unsubscribe errors", "duplicate unsubscribe",
    "disconnect flow", "subscription cleanup",

    # Navigation/performance implementation details
    "navmesh", "nav mesh", "full rebuild",
    "door-handling performance", "door handling performance",
)


STRATEGIC_GAMEPLAY_TERMS = (
    # Explicit balance
    "buff", "buffs", "buffed", "nerf", "nerfs", "nerfed", "rebalance",
    "balance",

    # Base / upkeep / building rules
    "upkeep", "decay", "tool cupboard", "tc auth", "code lock",
    "building privilege", "authorized", "authed",

    # Groups / player limits
    "group", "team", "player limit",

    # Inventory / economy
    "stack size", "stack sizes", "capacity", "crafting cost", "resource cost",
    "resource rate", "gather rate", "drop rate",

    # Combat / counters / defenses
    "sam site", "sam sites", "drone", "drones", "turret", "missile",
    "missiles", "proximity fuse", "target", "targeting", "counter",
    "counterplay", "explosive", "explosives",

    # Other strategic values
    "damage", "range", "speed", "fire rate", "cooldown", "respawn",
)


SCORE_WEIGHTS = {
    "strategic_gameplay": 7,
    "bug": 6,
    "high_value_term": 2,
    "new_high_value": 3,
    "balance_change": 5,
    "explicit_buff_nerf": 6,
    "visible_visual": 0,
    "technical": -5,
    "low_value_visual": -5,
    "low_value_asset_optimization": -20,
    "equipment_audio_change": 7,
    "low_value_player_polish": -20,
    "test_only": -4,
    "cleanup_refactor": -4,
    "player_facing_bug_rescue": 5,
}

RELEVANCE_THRESHOLD = 2


def commit_search_text(commit):
    return (
        f"{commit.get('branch', '')} "
        f"{commit.get('message', '')}"
    ).lower().replace("_", " ")


AMBIGUOUS_SINGLE_WORD_TERMS = {"team", "map", "cow", "dog", "gun"}


def contains_term(text, term):
    if term in AMBIGUOUS_SINGLE_WORD_TERMS:
        return re.search(rf"\\b{re.escape(term)}\\b", text) is not None
    return term in text


def contains_any(text, terms):
    return any(contains_term(text, term) for term in terms)


def player_relevance_score(commit):
    text = commit_search_text(commit)
    score = 0

    strategic_change = contains_any(text, STRATEGIC_GAMEPLAY_TERMS)
    if strategic_change:
        score += SCORE_WEIGHTS["strategic_gameplay"]

    equipment_audio_change = (
        contains_any(text, EQUIPMENT_TERMS)
        and contains_any(text, PLAYER_AUDIO_EFFECT_TERMS)
    )
    if equipment_audio_change:
        score += SCORE_WEIGHTS["equipment_audio_change"]

    if contains_any(text, BUG_TERMS):
        score += SCORE_WEIGHTS["bug"]

    high_matches = sum(1 for term in HIGH_VALUE_TERMS if term in text)
    score += min(high_matches, 4) * SCORE_WEIGHTS["high_value_term"]

    if re.search(r"\b(add|added|new|introduce|introduced)\b", text):
        if contains_any(text, HIGH_VALUE_TERMS):
            score += SCORE_WEIGHTS["new_high_value"]

    if contains_any(
        text,
        (
            "balance", "balanced", "increase damage", "decrease damage",
            "resource yield", "spawn rate", "movement", "behaviour", "behavior",
            "buff", "buffs", "buffed", "nerf", "nerfs", "nerfed", "rebalance",
            "sam site", "sam sites", "drone", "drones", "proximity fuse",
            "stack size", "stack sizes", "inventory capacity", "crafting cost",
            "durability", "fire rate", "cooldown", "respawn time",
            "fuel consumption", "gather rate", "drop rate",
        ),
    ):
        score += SCORE_WEIGHTS["balance_change"]

    if contains_any(
        text,
        ("buff", "buffs", "buffed", "nerf", "nerfs", "nerfed", "rebalance"),
    ):
        score += SCORE_WEIGHTS["explicit_buff_nerf"]

    if contains_any(text, VISIBLE_VISUAL_TERMS):
        score += SCORE_WEIGHTS["visible_visual"]

    if contains_any(text, TECHNICAL_TERMS):
        score += SCORE_WEIGHTS["technical"]

    if contains_any(text, LOW_VALUE_VISUAL_TERMS):
        score += SCORE_WEIGHTS["low_value_visual"]

    if contains_any(text, LOW_VALUE_ASSET_OPTIMIZATION_TERMS):
        score += SCORE_WEIGHTS["low_value_asset_optimization"]

    if contains_any(text, LOW_VALUE_PLAYER_POLISH_TERMS):
        score += SCORE_WEIGHTS["low_value_player_polish"]

    # Test wording should not penalize a meaningful strategic gameplay change.
    if re.search(r"\b(test|tests|testing)\b", text) and not strategic_change:
        score += SCORE_WEIGHTS["test_only"]

    if re.search(r"\b(cleanup|refactor|rename|renamed)\b", text):
        score += SCORE_WEIGHTS["cleanup_refactor"]

    if contains_any(text, BUG_TERMS) and contains_any(text, HIGH_VALUE_TERMS):
        score += SCORE_WEIGHTS["player_facing_bug_rescue"]

    return score


def filter_player_relevant_commits(commits, log_filtered=False):
    scored = [(player_relevance_score(commit), commit) for commit in commits]

    # Preserve source order so new arrivals do not reshuffle chunk boundaries.
    relevant = [
        commit
        for score, commit in scored
        if score >= RELEVANCE_THRESHOLD
    ]

    print(
        f"Player relevance filter: {len(commits)} raw commits -> "
        f"{len(relevant)} useful candidates."
    )

    if log_filtered:
        for score, commit in sorted(
            scored,
            key=lambda item: item[0],
            reverse=True,
        ):
            if score < RELEVANCE_THRESHOLD:
                message = (
                    commit.get("message", "")
                    .replace("\n", " ")
                    .replace("\r", " ")
                )
                print(f"  Filtered ({score:+d}): {message[:100]}")

    return relevant
