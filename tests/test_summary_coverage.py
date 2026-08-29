from scripts.relevance import (
    RELEVANCE_THRESHOLD,
    player_relevance_score,
)


MUST_INCLUDE_COMMITS = [
    {
        "id": 615001,
        "branch": "main",
        "message": (
            "Reduced F1 Grenade, Bee Grenade, Flashbang and Molotov "
            "stack sizes from 5 to 3"
        ),
    },
    {
        "id": 615002,
        "branch": "main/sam_drone_changes",
        "message": (
            "WIP SAM site buffs: added proximity fuse, lead drones without aim "
            "error at 2.25x speed, destroy drone-dropped explosives mid-air"
        ),
    },
    {
        "id": 615003,
        "branch": "main/tc_auth_group_tests",
        "message": (
            "Group upkeep modifier now counts players authed on code locks "
            "controlled by the TC. Added tests for TC auth group behavior."
        ),
    },
]


def test_must_include_strategic_changes_pass_filter():
    for item in MUST_INCLUDE_COMMITS:
        score = player_relevance_score(item)
        assert score >= RELEVANCE_THRESHOLD, (item["message"], score)


def test_must_include_changes_are_high_impact():
    for item in MUST_INCLUDE_COMMITS:
        score = player_relevance_score(item)
        assert score >= 10, (item["message"], score)
