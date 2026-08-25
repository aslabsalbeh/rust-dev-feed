from scripts.relevance import (
    RELEVANCE_THRESHOLD,
    player_relevance_score,
)


MUST_INCLUDE_COMMITS = [
    {
        "id": 1,
        "branch": "",
        "message": (
            "Reduced stack size for F1s 5 > 3, "
            "Bee nades 5 > 3, Flashbangs 5 > 3, "
            "Molotovs 5 > 3"
        ),
        "created": "2026-08-25T12:00:00",
    },
    {
        "id": 2,
        "branch": "",
        "message": (
            "SAM site vs drone buffs wip: Missiles use a proximity "
            "fuse against drones, lead vs them without aim error at "
            "2.25x speed, and destroy drone-dropped explosives mid-air"
        ),
        "created": "2026-08-25T12:00:00",
    },
    {
        "id": 3,
        "branch": "main/tc_auth_group_tests",
        "message": (
            "Group upkeep modifier now takes into account any unique "
            "players authed on a code lock. If a player is not authed "
            "on a TC but is authed on a code lock controlled by that "
            "TC then they will contribute to upkeep costs. "
            "Added tests to verify behaviour."
        ),
        "created": "2026-08-25T12:00:00",
    },
]


def test_must_include_strategic_changes_pass_filter():
    for commit in MUST_INCLUDE_COMMITS:
        score = player_relevance_score(commit)

        assert score >= RELEVANCE_THRESHOLD, (
            f"Important commit was filtered out: "
            f"{commit['message']} (score={score})"
        )


def test_must_include_changes_are_high_impact():
    for commit in MUST_INCLUDE_COMMITS:
        score = player_relevance_score(commit)

        assert score >= 10, (
            f"Important commit did not reach high-impact threshold: "
            f"{commit['message']} (score={score})"
        )
