from scripts.relevance import player_relevance_score


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
        "branch": "",
        "message": (
            "Group upkeep modifier now takes into account any unique "
            "players authed on a code lock. If a player is not authed "
            "on a TC but is authed on a code lock controlled by that "
            "TC then they will contribute to upkeep costs."
        ),
        "created": "2026-08-25T12:00:00",
    },
]


def test_known_strategic_changes_clear_relevance_threshold():
    for commit in MUST_INCLUDE_COMMITS:
        assert player_relevance_score(commit) >= 2
